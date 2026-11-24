# Paperroom

[English](README.md) · 中文

**让 AI 陪你把论文想透，但别让它替你思考。**

在常用的 Claude、Codex 或 Antigravity 对话里说一句「用 Paperroom 来写这篇论文」，打开返回的本地链接，就能进入这篇论文的写作间。你在里面亲手写下每一段、每一句想表达的逻辑，AI 按你的意图起草 LaTeX 正文，再由你在排版好的页面上审阅修改。

## 为什么做 Paperroom

用 AI 写论文很容易掉进一个坑：明明一开始只是想聊思路，聊着聊着人就犯懒了，顺手让 AI「把这一节直接写出来」。几秒钟后它吐出一大段看起来很顺的文字，但你得花更多时间去读、去核对有没有胡说、去大改——最糟的是，因为跳过了自己梳理逻辑的那一步，最后连你自己都说不清这一段为什么这么写。

Paperroom 的想法很简单：**讨论尽管放开，框架必须亲手敲。**

- **讨论和参考交给 AI**：在聊天里想聊几轮都行，随时让 AI 把讨论结果整理到写作间右侧的参考栏里。
- **结构必须自己写**：这一节分几段、每段要让读者明白什么、每句话怎么承接上一句，都在写作间里亲手敲下来。输入框禁用了复制粘贴，写得粗糙没关系，但得是你自己过了一遍脑子的输出。
- **把脏活累活交给 AI**：大纲敲完后，可以让 AI 帮你润色措辞；AI 只会起草你明确允许的段落，不会擅自大段重写。
- **像审稿一样改论文**：直接在论文模板排版好的 PDF 页面上标注意见，AI 逐条回应；支持任意两版并排对照，也能在写作间里直接看图和表。
- **全部留在本地**：大纲、草稿、版本和批注都保存在你自己的论文文件夹里，不上传云端，也不绑死特定平台。

## 安装

### 运行环境

| 依赖 | 说明 |
| --- | --- |
| Python 3.9+ | 在终端运行 `python3 --version` 检查。macOS 若提示安装命令行开发者工具，按提示安装即可。 |
| 支持的客户端 | macOS 版 Claude 桌面客户端（Chat）、Claude Code（含 VS Code 扩展）、Codex 或 Google Antigravity，直接使用你客户端里现有的模型。 |
| LaTeX（审阅排版用） | pdfLaTeX 或 Tectonic。如果本机装有 ChatGPT 桌面应用，Paperroom 会自动复用它自带的 Tectonic。只写大纲时不需要安装。 |
| Poppler（仅非 macOS） | 提供 `pdftoppm` 和 `pdftotext` 用于渲染审阅页图；macOS 直接使用系统自带的 PDFKit。 |

### Claude 桌面版 Chat（macOS）

1. 下载 [Paperroom.mcpb](packages/Paperroom.mcpb)。
2. 打开 Claude 桌面版，进入 **设置 → 桌面应用 → 扩展**，把文件拖进去按提示安装。
3. 新开一个对话，输入「调用 Paperroom 的 `get_usage`」。能正常返回说明，就装好了。

### Claude Code / Codex

1. 下载 [Paperroom-Plugin-0.7.3.zip](packages/Paperroom-Plugin-0.7.3.zip) 并**完整解压**（不要只拷贝单个文件）。
2. 在 macOS 上双击解压目录里的 `Install-Paperroom.command`；或在终端进入解压目录运行：

   ```bash
   python3 install.py
   ```

   安装脚本会自动检测本机的 Claude Code 和 Codex 并一起装好。只装其中一个时，加 `--client claude` 或 `--client codex`。文件会复制到 `~/.local/share/paperroom/`，装完后解压目录可以删掉。
3. 重开一个新会话。如果希望 Codex 自动拦截未经授权的正文修改，可以在 `/hooks` 里审阅并启用 Paperroom 的钩子（钩子更新时可能需要再次确认）。
4. 在论文目录里打开会话，输入「调用 Paperroom 的 `get_usage`」确认版本。

### Google Antigravity（反重力）

1. 下载并完整解压 [Paperroom-Plugin-0.7.3.zip](packages/Paperroom-Plugin-0.7.3.zip)。
2. 在 macOS 上双击 `Install-Antigravity.command`，或在终端运行：

   ```bash
   python3 install.py --client antigravity
   ```

3. 重启 Antigravity，在论文目录的对话里说「用 Paperroom 来写这篇论文」（已有项目说「打开这篇论文的 Paperroom」）。

> 说明：在 Antigravity 中同样可以使用完整的本地写作间和 MCP 工具，但直接通过编辑器或终端手动改文件时，不会触发自动写入拦截。

### 先体验一下

不确定合不合胃口？直接双击解压目录里的 `Try-Paperroom.command`，它会用一篇示例论文打开写作间，你可以先试试三级大纲和排版审阅，不会改动你的任何文件。

### 更新

插件更新不会影响你已有的大纲、草稿和审阅记录（它们都存在论文目录里）。

- **Claude 桌面版 Chat**：下载新版 `Paperroom.mcpb`，重新拖进 **扩展** 页面即可。
- **Codex（macOS）**：双击解压目录里的 `Enable-Codex-Updates.command`（或运行 `python3 install.py --client codex --auto-update`），之后会自动跟随 GitHub `main` 分支更新；更新后重开会话生效。如需关闭，运行 `python3 install.py --client codex --disable-auto-update`。
- **Claude Code**：双击一次 `Enable-Claude-Updates.command` 开启自动更新。
- **手动更新**：Claude Code、Codex 和 Antigravity 都可以直接下载新版 ZIP 重新运行安装器。

## 快速上手

首次使用，在论文目录的对话里说 **「用 Paperroom 来写这篇论文」**；之后换新对话，说 **「打开这篇论文的 Paperroom」** 并点开返回的本地链接即可（同名论文较多时指明路径就行）。Claude Code 也可以直接输 `/paperroom:open`，Codex 可以输 `$paperroom:open`。

一次完整的写作流程大概是这样：

1. **交代手头材料**：在聊天里告诉 AI 论文目录、实验数据、想说明的核心观点和已有初稿，一起把研究问题和证据理清楚。
2. **定整篇大纲**：聊得差不多了，让 AI 草拟整篇大纲；在浏览器里按需调整，点 **采用这份章节安排**。
3. **聊透某一节的结构**：选一节（比如 Method），和 AI 多轮讨论分几段、每段讲什么，然后说「把这一节的段落安排放到参考栏」。
4. **亲手写段落大纲**：对照右侧参考，在左侧用自己的话敲下小标题和每段作用，点 **保存段落大纲**。想顺一下措辞可以让 AI 润色。
5. **亲手写逐句意图**：对某一段同样先讨论、生成参考，再自己写每句话说什么，点 **保存并允许起草本段**。
6. **起草、存版本、审阅**：说「按我保存的意图起草这一段」。觉得可以留一版时，说「把这一版放进 Paperroom」，在 **排版与审阅** 里像审稿人一样标注意见，并用 **排版版本** 并排对照新旧稿。

想尝试另一种大改方案前，可以点右上角 **存档** 给整篇论文留个副本；以后切回旧稿时，Paperroom 也会自动帮你把当前版本先存一份，两边都不会丢。

每一步怎么操作、聊天里怎么和 AI 配合、图表怎么管理，请看 **[写作指导](docs/writing-guide.zh-CN.md)**。  
（AI 调用 `get_usage()` 时读取的是写给它看的操作规范：[README-workflow.md](plugins/paperroom/runtime/README-workflow.md)。）

## 分享给合作者

点写作间右上角 **存档 → 导出给合作者**，会打包一份当前论文的 ZIP（包含正文、素材和已同步的大纲/批注草稿；导出前记得先保存外部编辑器里正在改的文件）。如果希望对方也能切回以前的项目快照，勾选 **包含历史存档**。

对方完整解压后，在论文文件夹里打开 Paperroom 就能接着写。如果项目里有指向外部文件的符号链接，导出时会提示具体路径，先替换成实际文件即可。

## 安装与使用常见问题

| 遇到的问题 | 怎么处理 |
| --- | --- |
| 提示 `未找到本机 Claude Code 或 Codex CLI` | 先安装并至少打开过一次对应客户端；如果命令装在非默认路径，把它加入 `PATH` 后重试。 |
| 提示 `未发现 codex，已跳过。` | 正常提示，说明你本机只装了另一个客户端。 |
| 聊天里找不到 Paperroom 工具 | 重开一个新会话，让 AI 调用 Paperroom 的 `get_usage` 检查版本，并确认客户端里已启用插件。 |
| 写作间网页显示「暂时离线」 | 不用关网页，在任意对话里让 AI 重新打开一次写作间，几秒内会自动重连。 |
| AI 提示打不开写作间 | 检查客户端是否允许调用 Paperroom 工具。急着用时，可以直接双击 `~/.local/share/paperroom/Open-Paperroom.command`（访达按 `⌘ + ⇧ + G` 输入路径）手动选论文打开，不依赖 AI。 |

表里没覆盖到你的问题？坦白说，作者自己也是半路出家，这个插件多半是和 AI 一起磨出来的。把报错原样贴给 Claude 或 GPT，往往比找作者解决得更快。

## 许可

见 [LICENSE](LICENSE)。
