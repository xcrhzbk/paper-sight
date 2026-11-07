import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("storage", Path(__file__).resolve().parents[1] / "scripts/storage.py")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.a, self.b = self.root / "a", self.root / "b"

    def concept(self, directory, state, device="device"):
        return s.record(directory, "concept", "attention", {"state": state, "evidence": device}, device)

    def test_config_paths_follow_config_location_and_cli_wins(self):
        config = self.root / "settings.json"
        config.write_text(json.dumps({"memory_dir": "data", "output_dir": "library"}))
        with patch.dict(os.environ, {}, clear=True):
            result = s.settings(config)
            self.assertEqual(result["memory_dir"], str(self.root / "data"))
            self.assertEqual(result["output_dir"], str(self.root / "library"))
            with patch.dict(os.environ, {"PAPER_SIGHT_MEMORY_DIR": str(self.b)}):
                self.assertEqual(s.settings(config)["memory_dir"], str(self.b))
                self.assertEqual(s.settings(config, memory_dir=str(self.a))["memory_dir"], str(self.a))

    def test_missing_explicit_config_fails(self):
        with self.assertRaises(ValueError):
            s.settings(self.root / "missing.json")

    def test_moved_installation_and_pdf_default(self):
        with patch.object(s, "SKILL_DIR", self.root / "moved"), patch.dict(os.environ, {}, clear=True):
            result = s.settings(pdf=self.root / "papers" / "paper.pdf")
            self.assertEqual(result["memory_dir"], str(self.root / "moved" / "user"))
            self.assertEqual(result["output_dir"], str(self.root / "papers"))

    def test_offline_conflict_survives_merge_and_explicit_update_resolves(self):
        base = self.concept(self.a, "confused", "first")
        s.merge(self.b, self.a)
        left = self.concept(self.a, "known", "laptop")
        right = self.concept(self.b, "confused", "desktop")
        # A clock skew cannot turn a concurrent edit into a later observation.
        right["created"] = "2099-01-01T00:00:00+00:00"
        (self.b / "events" / (right["id"] + ".json")).write_text(json.dumps(right))
        self.assertEqual(s.merge(self.a, self.b), 1)
        self.assertEqual(len(s.state_view(self.a)["conflicts"]), 1)
        confirmed = self.concept(self.a, "known", "confirmed-by-user")
        self.assertEqual(set(confirmed["parents"]), {left["id"], right["id"]})
        self.assertEqual(s.state_view(self.a)["conflicts"], [])
        self.assertIn(base["id"], s.load_events(self.a))

    def test_merge_is_idempotent_commutative_and_preserves_distinct_keys(self):
        self.concept(self.a, "known")
        s.record(self.b, "preference", "language", {"text": "中文"}, "b")
        self.assertEqual(s.merge(self.a, self.b), 1)
        self.assertEqual(s.merge(self.a, self.b), 0)
        s.merge(self.b, self.a)
        self.assertEqual(s.state_view(self.a), s.state_view(self.b))

    def test_same_concept_state_with_different_evidence_is_not_conflict(self):
        self.concept(self.a, "known", "a")
        self.concept(self.b, "known", "b")
        s.merge(self.a, self.b)
        view = s.state_view(self.a)
        self.assertEqual(view["conflicts"], [])
        self.assertEqual(len(view["entries"][0]["events"]), 2)

    def test_duplicate_uuid_with_different_contents_rejected_before_copy(self):
        event = self.concept(self.a, "known")
        s.merge(self.b, self.a)
        event["value"]["state"] = "confused"
        (self.b / "events" / (event["id"] + ".json")).write_text(json.dumps(event))
        s.record(self.b, "preference", "other", {"text": "something"}, "b")
        before = s.load_events(self.a)
        with self.assertRaises(ValueError):
            s.merge(self.a, self.b)
        self.assertEqual(s.load_events(self.a), before)

    def test_missing_parent_rejected_before_copy(self):
        event = self.concept(self.b, "known")
        event["parents"] = ["not-yet-synced"]
        (self.b / "events" / (event["id"] + ".json")).write_text(json.dumps(event))
        with self.assertRaises(ValueError):
            s.merge(self.a, self.b)
        self.assertFalse((self.a / "events").exists())

    def test_cycle_rejected(self):
        event = self.concept(self.a, "known")
        event["parents"] = [event["id"]]
        with self.assertRaisesRegex(ValueError, "Cycle"):
            s.validate_graph({event["id"]: event})

    def test_render_preserves_unmigrated_legacy_profile(self):
        self.a.mkdir()
        legacy = self.a / "profile.md"
        legacy.write_text("# 旧档案\n明确的偏好")
        with self.assertRaises(ValueError):
            s.render(self.a)
        self.assertEqual(legacy.read_text(), "# 旧档案\n明确的偏好")

    def test_legacy_import_is_lossless_and_cross_device_idempotent(self):
        old = self.root / "old"
        old.mkdir()
        text = "# 旧档案\n- 数学：熟悉线代\n"
        (old / "profile.md").write_text(text)
        self.assertEqual(s.migrate(self.a, old, "a"), 1)
        self.assertEqual(s.migrate(self.a, old, "a"), 0)
        s.migrate(self.b, old, "b")
        self.assertEqual(s.merge(self.a, self.b), 0)
        self.assertEqual(next(iter(s.load_events(self.a).values()))["value"]["text"], text)
        self.assertEqual((old / "profile.md").read_text(), text)

    def notes(self, path, text="问题", updated="2026-11-07"):
        data = {"doc": {"id": "same-document"}, "marks": [{"id": "same-mark", "type": "note", "quote": "原文", "note": text, "t": "2026-11-06"}], "updated": updated}
        path.write_text('<script type="application/json" id="xray-notes">' + json.dumps(data) + '</script>')

    def test_annotation_import_is_deduplicated_across_devices(self):
        html = self.root / "a.html"
        self.notes(html)
        self.assertEqual(len(s.import_notes(self.a, html, "a")), 1)
        self.assertEqual(len(s.import_notes(self.a, html, "a")), 0)
        self.notes(html, updated="2099-01-01")
        s.import_notes(self.b, html, "b")
        self.assertEqual(s.merge(self.a, self.b), 0)

    def test_divergent_annotation_edits_remain_visible(self):
        html = self.root / "paper.html"
        self.notes(html, "左端问题")
        s.import_notes(self.a, html, "a")
        self.notes(html, "右端问题")
        s.import_notes(self.b, html, "b")
        s.merge(self.a, self.b)
        self.assertEqual(len(s.render(self.a)["conflicts"]), 1)
        profile = (self.a / "profile.md").read_text()
        self.assertIn("左端问题", profile)
        self.assertIn("右端问题", profile)

    def test_annotation_without_portable_doc_id_is_rejected(self):
        html = self.root / "legacy.html"
        html.write_text('<script id="xray-notes">{"doc":{},"marks":[]}</script>')
        with self.assertRaises(ValueError):
            s.import_notes(self.a, html, "a")
        self.assertFalse((self.a / "events").exists())

    def test_same_reading_id_is_counted_once_after_merge(self):
        s.record(self.a, "reading", "doc-one", {"title": "paper", "artifact": "paper-sight-uuid/paper.html"}, "a")
        s.merge(self.b, self.a)
        s.merge(self.a, self.b)
        text = (s.render(self.a), (self.a / "log.md").read_text())[1]
        self.assertEqual(text.count("doc-one"), 1)


if __name__ == "__main__":
    unittest.main()
