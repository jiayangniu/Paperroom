# Paperroom

[English](README.md) · 中文

用 Claude 或 Codex 写论文时，你可以在原对话里讨论研究。准备动笔时，Paperroom 会打开本地写作间。你亲手写下每一段、每一句要让读者理解什么，AI 据此起草，再由你审阅排版后的稿件。

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
| 一个聊天客户端 | macOS 上的 Claude 桌面版（Chat）、Claude Code（含 VS Code 扩展）或 Codex。使用你聊天中已有的模型。 |
| LaTeX（审阅排版时需要） | pdfLaTeX 或 Tectonic。装有 ChatGPT 桌面应用时，会自动使用它自带的 Tectonic。只写大纲时不需要。 |
| Poppler（仅非 macOS） | 提供 `pdftoppm` 和 `pdftotext`，用于显示审阅页图。macOS 使用系统自带的 PDFKit。 |

### Claude 桌面版 Chat（macOS）

1. 下载 [Paperroom.mcpb](packages/Paperroom.mcpb)。
2. 打开 Claude 桌面版，进入「设置 → 桌面应用 → 扩展」，把文件拖进页面，按提示确认安装。
3. 新开一个对话，输入「调用 Paperroom 的 get_usage」。能读到使用说明，就说明安装成功。

### Claude Code 或 Codex

1. 下载 [Paperroom-Plugin-0.6.14.zip](packages/Paperroom-Plugin-0.6.14.zip)，**完整解压**。不要只拷出其中几个文件。
2. 在 macOS 上双击解压目录里的 `Install-Paperroom.command`；或在终端进入解压目录，运行：

   ```bash
   python3 install.py
   ```

   安装器会自动找到本机的 Claude Code 和 Codex，并为两者都装上 Paperroom。只想装其中一个时，加上 `--client claude` 或 `--client codex`。插件文件复制到 `~/.local/share/paperroom/`，解压目录之后可以删除。
3. 完全退出并重新打开客户端。Codex 第一次使用时，会请你在 `/hooks` 中批准 Paperroom 的写作检查，批准一次即可。
4. 在论文项目文件夹里打开会话，输入「调用 Paperroom 的 get_usage」确认已安装的版本。

### 先试一试

解压目录里的 `Try-Paperroom.command` 会用一篇虚构的示例论文打开写作间，可以先体验三级大纲和排版审阅，不会改动你的任何文件。

### 更新

- **Claude 桌面版 Chat**：下载新版 `Paperroom.mcpb`，重新拖进「扩展」页面。
- **Claude Code 或 Codex**：下载新版压缩包，解压后再运行一次 `install.py`，然后重新打开客户端。Claude Code 用户也可以双击 `Enable-Claude-Updates.command`，之后自动获取更新。

你的大纲、草稿和审阅记录都在论文项目里，更新插件不会影响它们。

### 安装遇到问题

| 提示 | 处理 |
| --- | --- |
| `未找到本机 Claude Code 或 Codex CLI` | 先安装并打开过一次客户端；如果 `claude` 或 `codex` 装在不常见的位置，把它加入 PATH 后重试。 |
| `未发现 codex，已跳过。` | 正常提示：本机只装了另一个客户端。 |
| 聊天里找不到 Paperroom 的工具 | 确认已完全退出并重开客户端；Codex 还需在 `/hooks` 中批准一次。 |
| 写作间网页显示「暂时离线」 | 在任意一个对话里让 AI 打开写作间，原网页会自动重连，不用关掉。 |

表里没有你遇到的情况？坦白说，作者也是个菜鸟，这个插件多半也是和 AI 聊出来的。把报错原样贴给 Claude 或 GPT，它们大概比作者更快帮你解决。

## 第一次写作

1. **带上已有资产开启项目。** 在聊天中输入「用 Paperroom 在 `~/papers/my-paper` 开始写一篇论文。实验数据在 `results/`，我大致想说明……，`main.tex` 里有一版初稿。」AI 会和你一起理清研究问题和已有证据。
2. **讨论并确定整篇大纲。** 讨论到差不多时，请 AI 草拟整篇大纲。在浏览器里修改，点 **采用这份章节安排**。
3. **选一节，多轮讨论它的结构。** 比如 Method 起什么作用、分几个小节、每段想表达什么。讨论清楚后说「把这一节的段落安排放到参考栏」。
4. **对照参考，亲手写段落大纲。** 在浏览器里用自己的话写下小标题和每段的作用，点 **保存段落大纲**。需要时请 AI「润色第 2 段的作用」。
5. **逐句意图同理。** 讨论一段怎么展开，请 AI 生成逐句参考，再亲手写下每句的意图，点 **保存并允许起草本段**。
6. **起草、审阅、对照。** 说「按我保存的意图起草这一段」。觉得某一版值得留下时说「把这一版放进 Paperroom」，在 **排版与审阅** 里标注意见；之后用 **排版版本** 只看最新版或对照两版。

每一步的细节、聊天里怎么说、图表怎么查看，见 **[写作指导](docs/writing-guide.zh-CN.md)**。

AI 在聊天中调用 `get_usage()` 会读到插件附带的[操作说明](plugins/paperroom/runtime/README-workflow.md)，那份是写给 AI 的。

## 许可

见 [LICENSE](LICENSE)。
