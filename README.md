# Paper Sight

按审稿人的视角读论文，围绕 **Research Problem、Prior Work、Core Intuition、Method** 展开。阅读核心使用仓库所有者提供的完整 prompt，保留 HTML 交互图、划线、边注和阅读反馈。

基于 [Wang-auspicious/paper-xray](https://github.com/Wang-auspicious/paper-xray) 修改。网页与绘图组件保留原项目实现；旧版论文阅读指令整体替换。许可证为 MIT，原作者版权声明见 [LICENSE](LICENSE)。

## 安装与使用

把本仓库放入所用代理的 skills 目录，目录名为 `paper-sight`，入口是 `SKILL.md`。例如 Codex：

```sh
git clone https://github.com/xcrhzbk/paper-sight.git ~/.codex/skills/paper-sight
```

使用时提供本地 PDF、arXiv 链接或论文正文，并选择 `html` 或 `md`。例如：

```text
用 paper-sight 讲解这篇论文：https://arxiv.org/abs/1706.03762，输出 HTML。
```

HTML 中开启 ✎ 可以划线、写边注、标记不懂或已懂；用 ⤓ 保存后，下次运行才能从文件读取新批注。页面公式使用 KaTeX CDN，离线时公式会显示源码。

## 自选目录

安装目录可以移动。把 `config.example.json` 复制成 `.paper-sight.json`，填写当前设备的目录：

```json
{
  "memory_dir": "~/PaperSight/memory",
  "output_dir": "~/PaperSight/library",
  "device_id": "my-laptop"
}
```

也可以每次直接指定保存位置，或使用 `PAPER_SIGHT_MEMORY_DIR`、`PAPER_SIGHT_OUTPUT_DIR`。未配置时，记忆保存在 skill 的 `user/`，文档放在 PDF 所在目录或当前工作目录。代码、记忆和文档可分别存放。

## 多端阅读

各端使用同一个记忆库的同步副本，本机路径分别配置。每条阅读或反馈记录有独立 UUID，合并采用新增记录的并集。两端同时修改同一概念或偏好时保留冲突，用户确认后再追加状态，不以设备时间覆盖。

```sh
python3 scripts/storage.py --memory-dir "/local/memory" merge "/other-device/memory"
```

同步盘或独立私有 Git 仓库可以负责传输 `events/`；脚本本身不联网。`profile.md` 和 `log.md` 是可以重新生成的视图。公共仓库只发布 skill 代码，默认忽略个人记忆、本机配置和论文输出。

HTML 的批注先保存到各自的文件，再分别运行 `import-notes`。不同副本的批注证据可以合并；HTML 页面本身不会自动合成一个文件。配置优先级、迁移和冲突处理见 [存储说明](references/storage.md)。

## 验证

Python 存储工具无需额外依赖：

```sh
python3 -m unittest discover -s tests -v
```

自动测试覆盖配置目录、离线双端合并、重复导入、因果更新、冲突确认、旧档案迁移和批注导入。论文讲解质量需要用实际论文检查，自动测试不能代替阅读效果评估。

已用 Socratic-SWE（arXiv:2606.07412v1）生成实际试读并检查页面、图表与批注往返，详见[实测记录](docs/smoke-test.md)。
