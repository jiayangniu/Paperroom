# Paperroom

[English](README.md) · 中文

在原来的 Claude、Codex 或 Antigravity 对话里说「用 Paperroom 管理这篇论文」，点击返回的链接进入本地写作间。你亲手写下每一段、每一句要让读者理解什么，AI 据此起草，再由你审阅排版后的稿件。

和 AI 多轮讨论能让思路越来越清楚，但人容易犯懒，让 AI 大段生成，之后再花大量时间返工。Paperroom 的规则是：**讨论尽管放开，框架必须亲手敲。**

- **讨论和参考交给 AI。** 在聊天里想聊几轮都行，AI 的建议可以随时放进写作间右侧的参考栏。
- **框架由你来写。** 每节分几段、每段想表达什么、每句说什么，都由你在写作间里亲手敲下。不求精确，但必须是你自己的输出。参考里的文字不能粘贴过来。
- **写完再让 AI 帮忙。** 你写下的大纲可以请 AI 润色；AI 只起草你允许的段落。
- **在排版页上审阅。** 每节按论文模板排版，你在页面上标注意见，AI 逐条回应。新旧两版可以并排对照，图片和表格也能在写作间里直接查看。
- **一切留在本地。** 大纲、草稿和审阅记录都保存在论文项目文件夹里。

## 安装

### 准备

| 需要 | 说明 |
| --- | --- |
| Python 3.9 或更高版本 | 在终端运行 `python3 --version` 检查。macOS 若提示安装命令行开发者工具，按提示安装即可。 |
| 一个聊天客户端 | macOS 上的 Claude 桌面版（Chat）、Claude Code（含 VS Code 扩展）、Codex 或 Google Antigravity。使用你聊天中已有的模型。 |
| LaTeX（审阅排版时需要） | pdfLaTeX 或 Tectonic。装有 ChatGPT 桌面应用时，会自动使用它自带的 Tectonic。只写大纲时不需要。 |
| Poppler（仅非 macOS） | 提供 `pdftoppm` 和 `pdftotext`，用于显示审阅页图。macOS 使用系统自带的 PDFKit。 |

### Claude 桌面版 Chat（macOS）

1. 下载 [Paperroom.mcpb](packages/Paperroom.mcpb)。
2. 打开 Claude 桌面版，进入「设置 → 桌面应用 → 扩展」，把文件拖进页面，按提示确认安装。
3. 新开一个对话，输入「调用 Paperroom 的 get_usage」。能读到使用说明，就说明安装成功。

### Claude Code 或 Codex

1. 下载 [Paperroom-Plugin-0.7.3.zip](packages/Paperroom-Plugin-0.7.3.zip)，**完整解压**。不要只拷出其中几个文件。
2. 在 macOS 上双击解压目录里的 `Install-Paperroom.command`；或在终端进入解压目录，运行：

   ```bash
   python3 install.py
   ```

   安装器会自动找到本机的 Claude Code 和 Codex，并为两者都装上 Paperroom。只想装其中一个时，加上 `--client claude` 或 `--client codex`。插件文件复制到 `~/.local/share/paperroom/`，解压目录之后可以删除。
3. 新开一个会话。要让 Codex 在编辑器里执行逐句意图检查，可在 `/hooks` 中审阅并启用 Paperroom 的钩子。钩子定义更新后，客户端可能要求再次审阅。
4. 在论文项目文件夹里打开会话，输入「调用 Paperroom 的 get_usage」确认已安装的版本。

### Google Antigravity（反重力）

下载并解压 [插件 ZIP](packages/Paperroom-Plugin-0.7.3.zip)，在 Mac 上双击 `Install-Antigravity.command`，或运行 `python3 install.py --client antigravity`。重新打开 Antigravity，在论文目录的对话里说「打开这篇论文的 Paperroom」。新论文首次使用说「用 Paperroom 管理这篇论文」。本地 MCP 提供写作间和写作工具；直接通过编辑器或终端修改文件不经过 Paperroom 的写入检查。

### 先试一试

解压目录里的 `Try-Paperroom.command` 会用一篇虚构的示例论文打开写作间，可以先体验三级大纲和排版审阅，不会改动你的任何文件。

### 更新

- **Claude 桌面版 Chat**：下载新版 `Paperroom.mcpb`，重新拖进「扩展」页面。
- **macOS 上的 Codex** — 双击解压目录中的 `Enable-Codex-Updates.command`（或运行 `python3 install.py --client codex --auto-update`），安装当前版本，并自动跟随 GitHub 的 `main` 分支获取后续新版。更新后新开一个 Codex 会话即可。要关闭 Codex 自动更新，运行 `python3 install.py --client codex --disable-auto-update`。

- **Claude Code** — 双击一次 `Enable-Claude-Updates.command` 可启用自动更新。两个客户端也都可以使用新版压缩包的安装器手动更新。

你的大纲、草稿和审阅记录都在论文项目里，更新插件不会影响它们。

### 安装遇到问题

| 提示 | 处理 |
| --- | --- |
| `未找到本机 Claude Code 或 Codex CLI` | 先安装并打开过一次客户端；如果 `claude` 或 `codex` 装在不常见的位置，把它加入 PATH 后重试。 |
| `未发现 codex，已跳过。` | 正常提示：本机只装了另一个客户端。 |
| 聊天里找不到 Paperroom 的工具 | 新开会话，让 AI 调用 Paperroom 的 `get_usage` 核对版本，并确认这个客户端已启用插件。 |
| 更新研究问题时报 `Operation not permitted`，但能读回新内容 | 在原对话里让 Paperroom 用 `workspace_status` 读回同一篇论文的研究问题和证据摘要。如果两项都对，直接继续。0.6.19 修复了文件已写入、同步父目录时却被拒绝而误报失败的情况。 |
| 写作间网页显示「暂时离线」 | 在任意一个对话里让 AI 打开写作间，原网页会自动重连，不用关掉。 |
| AI 说打不开写作间 | 在客户端里允许 Paperroom 的工具。在那之前，可以直接双击 `~/.local/share/paperroom/Open-Paperroom.command`（在访达里按 Command-Shift-G 输入这个路径），选择论文即可打开，不需要 AI。 |

表里没有你遇到的情况？坦白说，作者也是个菜鸟，这个插件多半也是和 AI 聊出来的。把报错原样贴给 Claude 或 GPT，它们大概比作者更快帮你解决。

## 从聊天打开论文

第一次在论文目录里说 **「用 Paperroom 管理这篇论文」**。以后新开一个对话，说 **「打开 SG-ADAPT 的 Paperroom」**，点击带论文名的链接即可。两篇论文同名时，告诉 AI 要打开哪个目录。Claude Code 也可以输入 `/paperroom:open`，Codex 可以输入 `$paperroom:open`；首次使用时在命令后说明「管理这篇论文」。其他论文照常讨论和起草。写作间链接在运行 Paperroom 的那台电脑上使用。

## 第一次写作

1. **带上已有资产开启项目。** 在聊天中输入「用 Paperroom 在 `~/papers/my-paper` 开始写一篇论文。实验数据在 `results/`，我大致想说明……，`main.tex` 里有一版初稿。」AI 会和你一起理清研究问题和已有证据。
2. **讨论并确定整篇大纲。** 讨论到差不多时，请 AI 草拟整篇大纲。在浏览器里修改，点 **采用这份章节安排**。
3. **选一节，多轮讨论它的结构。** 比如 Method 起什么作用、分几个小节、每段想表达什么。讨论清楚后说「把这一节的段落安排放到参考栏」。
4. **对照参考，亲手写段落大纲。** 在浏览器里用自己的话写下小标题和每段的作用，点 **保存段落大纲**。需要时请 AI「润色第 2 段的作用」。
5. **逐句意图同理。** 讨论一段怎么展开，请 AI 生成逐句参考，再亲手写下每句的意图，点 **保存并允许起草本段**。
6. **起草、审阅、对照。** 说「按我保存的意图起草这一段」。觉得某一版值得留下时说「把这一版放进 Paperroom」，在 **排版与审阅** 里标注意见；之后用 **排版版本** 单独看某一版或对照任意两版。

**给整篇论文存档。** 想试另一种写法时，点右上角 **存档**，写一句备注，保存项目副本。切回旧稿时，Paperroom 会先为当前项目另存一份，两种写法以后都能接着写。

每一步的细节、聊天里怎么说、图表怎么查看，见 **[写作指导](docs/writing-guide.zh-CN.md)**。

AI 在聊天中调用 `get_usage()` 会读到插件附带的[操作说明](plugins/paperroom/runtime/README-workflow.md)，那份是写给 AI 的。

## 交给合作者

在写作间右上角点 **存档 → 导出给合作者**，即可下载当前论文的 ZIP。需要让对方切回以前的整项目副本时，勾选 **包含历史存档**。对方完整解压后，在论文文件夹里打开 Paperroom 即可。导出遇到符号链接会提示具体文件，请先将它替换为需要分享的实际文件。

交接包包含已同步但尚未提交的大纲和批注草稿。导出前请保存外部编辑器里的修改。

## 许可

见 [LICENSE](LICENSE)。
