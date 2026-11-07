# 目录、记录和多端合并

`scripts/storage.py` 只使用 Python 3 标准库，不联网。下面的脚本路径以 skill 目录为基准，执行时保留用户任务的工作目录。路径含空格时正常加引号。

## 配置

把 `config.example.json` 复制为 skill 目录中的 `.paper-sight.json`，或用 `--config` / `PAPER_SIGHT_CONFIG` 指定其他位置。相对配置路径按配置文件所在目录解析；CLI 和环境变量的相对路径按当前工作目录解析。`~` 和路径中的环境变量会展开。

| 配置 | 环境变量 | CLI | 默认 |
|---|---|---|---|
| `memory_dir` | `PAPER_SIGHT_MEMORY_DIR` | `--memory-dir` | 当前 skill 目录的 `user/` |
| `output_dir` | `PAPER_SIGHT_OUTPUT_DIR` | `--output-dir` | 本地 PDF 所在目录；其余用当前工作目录 |
| `device_id` | `PAPER_SIGHT_DEVICE_ID` | 配置或环境变量 | 本机名称，仅保存在私有事件中 |

优先级：本次 CLI 参数 > 环境变量 > 配置文件 > 默认。所有全局参数放在子命令前。输入是本地 PDF 时，`paths` 加 `--pdf <路径>`。

```sh
python3 scripts/storage.py paths
python3 scripts/storage.py --config "/path/to/local-settings.json" paths
python3 scripts/storage.py --memory-dir "/path/to/memory" --output-dir "/path/to/library" paths
```

脚本从自身位置寻找资源，不依赖固定的安装路径。不同设备的安装目录、记忆目录和文档根目录都可以不同。每端的本地配置不上传公共 skill 仓库。

## 记录与回读

```sh
python3 scripts/storage.py view
python3 scripts/storage.py record --kind concept --key "self-attention" --value '{"state":"confused","evidence":"用户说没看懂","explanation":"此前使用矩阵乘法解释"}'
python3 scripts/storage.py record --kind preference --key "language" --value '{"text":"默认用中文","evidence":"用户明确要求"}'
python3 scripts/storage.py render
```

长段文字先写 JSON 临时文件，用 `--value-file` 读取，不拼进 shell。value 必须为 JSON 对象。概念的状态只取 `known` 或 `confused`。

`reading` 的 key 是文档 UUID，value 例如：

```json
{
  "title": "论文标题",
  "source": "论文 URL 或标识",
  "artifact": "paper-sight-文档UUID/paper.html",
  "format": "html",
  "direction": "论文方向"
}
```

交付目录名包含 UUID，避免两端各读一次后文件互相覆盖。同一交付的 HTML 复制到其他端时保留 `xray-notes.doc.id`。文档元数据的 `file` 和阅读事件的 `artifact` 都相对输出根目录；当前对话中的文件链接使用本机实际绝对路径。

```sh
python3 scripts/storage.py import-notes "/path/to/paper.html"
```

返回 `new_annotations`，重复导入相同批注不会重复记忆。不同端对同一个批注的不同编辑会保留为冲突候选；脚本无法仅凭保存时间证明编辑顺序。保存两个 HTML 副本并分别导入，记忆里可以看到两边的批注。此命令合并批注证据，不重写 HTML 页面；未保存到文件的浏览器本地批注无法由脚本读取。批注的删除也不被解释为忘记该概念。

## 多端同步和冲突

每个变更独立保存为 `events/<UUID>.json`，文件写入后不修改。`profile.md`、`log.md`、`conflicts.json` 是派生视图，合并后重新生成，不合并它们的文本。

可把记忆目录放进用户自己的同步盘或独立私有 Git 仓库；同步方式由用户选择，本工具不会自动拉取或推送个人记忆。同步盘传输完成后运行 `render`。各端也可以保留本地副本，再手动合并：

```sh
python3 scripts/storage.py --memory-dir "/local/memory" merge "/other-device/memory"
```

该命令只把另一端缺少的事件复制到本地。需要双向同步时，交换新增事件或反向再合并一次。

- 不同 key 的修改独立保留，同一事件按 UUID 去重。
- 新记录带有当时已看到的同 key 记录作为 `parents`，因此后续明确反馈可以接续先前状态。
- 两端离线修改同一 key 时，互相没见过的新状态是并发候选。不同状态列在 `conflicts.json`；设备时钟不决定谁覆盖谁。
- 合并后，用户明确确认哪个状态有效，再对同 key 追加事件。它接续所有当前候选，冲突随之解决。
- 事件内容损坏、同 UUID 内容不同、缺少父记录或出现循环时，停止合并并报告；完整校验通过前不复制事件。

从旧版档案迁移：

```sh
python3 scripts/storage.py --memory-dir "/new/memory" migrate "/old/skill/user"
```

旧档案原文保存在 `legacy` 事件中，便于模型回读，不自动猜测其中每个概念的掌握状态。迁移不会改动旧目录。
