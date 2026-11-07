#!/usr/bin/env python3
"""Portable Paper Sight settings and immutable, causally merged reader events.

Uses only Python's standard library. This tool does not access the network.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import sys
import uuid

SKILL_DIR = Path(__file__).resolve().parent.parent
KINDS = {"base", "preference", "concept", "reading", "density", "annotation", "legacy"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def settings(config=None, memory_dir=None, output_dir=None, pdf=None):
    config_path = Path(config or os.environ.get("PAPER_SIGHT_CONFIG") or SKILL_DIR / ".paper-sight.json").expanduser().resolve()
    if config and not config_path.is_file():
        raise ValueError(f"Config does not exist: {config_path}")
    if os.environ.get("PAPER_SIGHT_CONFIG") and not config_path.is_file():
        raise ValueError(f"Config does not exist: {config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("Config must be a JSON object")

    def path_value(cli, env, key, fallback):
        raw = cli or os.environ.get(env) or data.get(key)
        if raw is None:
            return Path(fallback).expanduser().resolve()
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{key} must be a non-empty path or null")
        path = Path(os.path.expandvars(raw)).expanduser()
        # CLI/env paths use the caller's cwd; config paths use the config's directory.
        if not path.is_absolute() and not (cli or os.environ.get(env)):
            path = config_path.parent / path
        return path.resolve()

    memory = path_value(memory_dir, "PAPER_SIGHT_MEMORY_DIR", "memory_dir", SKILL_DIR / "user")
    output = path_value(output_dir, "PAPER_SIGHT_OUTPUT_DIR", "output_dir", Path(pdf).expanduser().resolve().parent if pdf else Path.cwd())
    return {"config": str(config_path), "memory_dir": str(memory), "output_dir": str(output),
            "device_id": os.environ.get("PAPER_SIGHT_DEVICE_ID") or data.get("device_id") or socket.gethostname()}


def validate_event(event):
    if not isinstance(event, dict) or event.get("v") != 1 or event.get("kind") not in KINDS:
        raise ValueError("Invalid memory event version/kind")
    try:
        if str(uuid.UUID(event["id"])) != event["id"]:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError("Invalid event UUID") from None
    if not isinstance(event.get("key"), str) or not event["key"].strip():
        raise ValueError("Event key must be non-empty")
    if not isinstance(event.get("parents"), list) or any(not isinstance(p, str) for p in event["parents"]):
        raise ValueError("Invalid event parents")
    if len(set(event["parents"])) != len(event["parents"]):
        raise ValueError("Duplicate event parents")
    if not isinstance(event.get("value"), dict):
        raise ValueError("Event value must be a JSON object")
    if not isinstance(event.get("device"), str) or not isinstance(event.get("created"), str):
        raise ValueError("Event device/created must be strings")
    if event["kind"] == "concept" and event["value"].get("state") not in {"known", "confused"}:
        raise ValueError("Concept state must be known or confused")
    canonical(event)


def validate_graph(events):
    for event in events.values():
        for parent in event["parents"]:
            if parent not in events:
                raise ValueError(f"Missing parent {parent}; sync all event files before rendering")
            if (events[parent]["kind"], events[parent]["key"]) != (event["kind"], event["key"]):
                raise ValueError("Parent belongs to another memory key")
    # Iterative traversal supports long histories without a recursion limit.
    done = set()
    for root in events:
        active = set()
        stack = [(root, False)]
        while stack:
            node, exiting = stack.pop()
            if exiting:
                active.remove(node)
                done.add(node)
            elif node not in done:
                if node in active:
                    raise ValueError("Cycle in memory events")
                active.add(node)
                stack.append((node, True))
                stack.extend((p, False) for p in events[node]["parents"])


def load_events(root, check=True):
    events = {}
    for path in sorted((Path(root) / "events").rglob("*.json")):
        event = json.loads(path.read_text(encoding="utf-8"))
        validate_event(event)
        if event["id"] in events and canonical(events[event["id"]]) != canonical(event):
            raise ValueError(f"Conflicting contents for event {event['id']}")
        events[event["id"]] = event
    if check:
        validate_graph(events)
    return events


def heads(events, kind, key):
    group = {i: e for i, e in events.items() if (e["kind"], e["key"]) == (kind, key)}
    superseded = {p for e in group.values() for p in e["parents"]}
    return [group[i] for i in sorted(set(group) - superseded)]


def write_event(root, event):
    validate_event(event)
    directory = Path(root) / "events"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (event["id"] + ".json")
    content = json.dumps(event, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if canonical(existing) != canonical(event):
            raise ValueError(f"Refusing to overwrite event {event['id']}") from None


def record(root, kind, key, value, device, event_id=None, parents=None):
    events = load_events(root)
    event = {"v": 1, "id": event_id or str(uuid.uuid4()), "kind": kind, "key": key,
             "value": value, "device": device,
             "created": datetime.now(timezone.utc).isoformat(),
             "parents": [e["id"] for e in heads(events, kind, key)] if parents is None else parents}
    validate_event(event)
    validate_graph({**events, event["id"]: event})
    write_event(root, event)
    return event


def merge(destination, source):
    target_events = load_events(destination, check=False)
    source_events = load_events(source, check=False)
    if not (Path(source) / "events").is_dir():
        raise ValueError(f"No events directory in {source}")
    combined = dict(target_events)
    for key, event in source_events.items():
        if key in combined and canonical(combined[key]) != canonical(event):
            raise ValueError(f"Conflicting contents for event {key}")
        combined[key] = event
    validate_graph(combined)  # Validate the whole union before any write.
    for key in sorted(set(source_events) - set(target_events)):
        write_event(destination, source_events[key])
    return len(set(source_events) - set(target_events))


def state_view(root):
    events = load_events(root)
    entries, conflicts = [], []
    for kind, key in sorted({(e["kind"], e["key"]) for e in events.values()}):
        frontier = heads(events, kind, key)
        values = {canonical(e["value"].get("state") if kind == "concept" else e["value"]) for e in frontier}
        item = {"kind": kind, "key": key, "conflict": len(values) > 1, "events": frontier}
        entries.append(item)
        if item["conflict"]:
            conflicts.append(item)
    return {"event_count": len(events), "entries": entries, "conflicts": conflicts}


def md_cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render(root):
    view = state_view(root)
    root = Path(root)
    preserved = {canonical(e["value"]) for entry in view["entries"] if entry["kind"] == "legacy" for e in entry["events"]}
    for name in ["profile.md", "log.md"]:
        old = root / name
        if old.exists():
            text = old.read_text(encoding="utf-8")
            if not text.startswith(("# Paper Sight 读者档案", "# 阅读记录")) and canonical({"file": name, "text": text}) not in preserved:
                raise ValueError("Legacy Markdown found; run 'migrate <old-user-directory>' before rendering")
    root.mkdir(parents=True, exist_ok=True)
    profile = ["# Paper Sight 读者档案", "", "由 events/ 生成；修改状态请追加事件，不直接编辑本文件。", ""]
    history = ["# 阅读记录", "", "| 文档 ID | 标题 | 来源 | 文档相对位置 |", "|---|---|---|---|"]
    for item in view["entries"]:
        kind, key = item["kind"], item["key"]
        if kind == "reading":
            for event in item["events"]:
                value = event["value"]
                history.append("| " + " | ".join(md_cell(x) for x in [key, value.get("title", ""), value.get("source", ""), value.get("artifact", "")]) + " |")
        else:
            profile.append(f"## {md_cell(kind)} · {md_cell(key)}" + (" · 待确认冲突" if item["conflict"] else ""))
            for event in item["events"]:
                profile.append("- " + canonical(event["value"]))
            profile.append("")
    for name, value in [("profile.md", "\n".join(profile) + "\n"), ("log.md", "\n".join(history) + "\n"),
                        ("conflicts.json", json.dumps(view["conflicts"], ensure_ascii=False, indent=2) + "\n")]:
        (root / name).write_text(value, encoding="utf-8")
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text("/profile.md\n/log.md\n/conflicts.json\n", encoding="utf-8")
    return view


def import_notes(root, html_path, device):
    content = Path(html_path).read_text(encoding="utf-8")
    block = re.search(r'<script\b(?=[^>]*\bid=["\']xray-notes["\'])[^>]*>(.*?)</script>', content, re.S | re.I)
    if not block:
        raise ValueError("Missing xray-notes block")
    notes = json.loads(block.group(1))
    doc = notes.get("doc", {})
    doc_id = doc.get("id")
    if not doc_id:
        raise ValueError("doc.id is required; assign the same ID to copies of this document before importing")
    marks = notes.get("marks", [])
    if not isinstance(marks, list) or any(not isinstance(m, dict) or not m.get("id") for m in marks):
        raise ValueError("Invalid annotation list")
    existing = load_events(root)
    imported = []
    for mark in marks:
        value = {"doc_id": doc_id, "mark": mark}
        identity = str(uuid.uuid5(uuid.NAMESPACE_URL, canonical(value)))
        if identity in existing:
            continue
        # Saved HTML snapshots do not prove which offline edit followed which.
        # Keep distinct revisions as concurrent candidates instead of inventing order.
        event = {"v": 1, "id": identity, "kind": "annotation", "key": doc_id + ":" + str(mark["id"]),
                 "value": value, "device": "html-import", "created": str(mark.get("t", "")), "parents": []}
        validate_event(event)
        imported.append(event)
    for event in imported:
        write_event(root, event)
    return imported


def migrate(root, directory, device):
    """Preserve legacy Markdown verbatim; do not infer conceptual mastery from it."""
    imported = 0
    existing = load_events(root)
    if Path(root).resolve() == Path(directory).resolve() and existing:
        return 0
    for name in ["profile.md", "log.md"]:
        path = Path(directory) / name
        if path.exists():
            value = {"file": name, "text": path.read_text(encoding="utf-8")}
            identity = str(uuid.uuid5(uuid.NAMESPACE_URL, canonical(value)))
            if identity not in existing:
                write_event(root, {"v": 1, "id": identity, "kind": "legacy", "key": name,
                                   "value": value, "device": "legacy-import", "created": "", "parents": []})
                imported += 1
    return imported


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--memory-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--pdf")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("paths")
    sub.add_parser("view")
    sub.add_parser("render")
    add = sub.add_parser("record")
    add.add_argument("--kind", choices=sorted(KINDS), required=True)
    add.add_argument("--key", required=True)
    add.add_argument("--value", help="JSON object; use --value-file for multiline content")
    add.add_argument("--value-file")
    join = sub.add_parser("merge")
    join.add_argument("source")
    notes = sub.add_parser("import-notes")
    notes.add_argument("html")
    old = sub.add_parser("migrate")
    old.add_argument("directory")
    args = parser.parse_args()
    config = settings(args.config, args.memory_dir, args.output_dir, args.pdf)
    root = config["memory_dir"]
    if args.command == "paths":
        result = config
    elif args.command == "view":
        result = state_view(root)
    elif args.command == "render":
        result = render(root)
    elif args.command == "record":
        if bool(args.value) == bool(args.value_file):
            raise ValueError("Provide exactly one of --value and --value-file")
        value = json.loads(Path(args.value_file).read_text(encoding="utf-8") if args.value_file else args.value)
        result = record(root, args.kind, args.key, value, config["device_id"])
        render(root)
    elif args.command == "merge":
        result = {"added": merge(root, Path(args.source).expanduser().resolve())}
        result["conflicts"] = render(root)["conflicts"]
    elif args.command == "import-notes":
        result = {"new_annotations": import_notes(root, args.html, config["device_id"])}
        render(root)
    elif args.command == "migrate":
        result = {"imported": migrate(root, args.directory, config["device_id"])}
        render(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"paper-sight: {error}", file=sys.stderr)
        sys.exit(1)
