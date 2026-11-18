# Paperroom

一个供 Codex 和 Claude Code 共用的本地论文写作 demo。作者可以自由改研究问题、补实验和调整章节顺序。要求 AI 起草或改写正文时，作者在浏览器里写出自己的思路，再看 LaTeX 排版节选并审阅。MIT 许可。

## 先体验，约三分钟

双击 **demo.html**。示例采用虚构的三组实验。你可以边看讨论参考边写整节逻辑、逐段写每句的作用，最后看真实 LaTeX 编译出的图片并提交审稿想法。离线模式的讨论材料和成稿预先给定，输入保存在本浏览器。真实项目中由你正在用的 AI 根据你的输入起草。

## 与真实的 AI 一起写

需要本机 Python 3.9+，以及已安装并能正常对话的 Codex CLI 或 Claude Code。两边共用一套 Python 标准库程序，工具本身无需模型 API key。切换客户端时在同一个论文目录启动，使用同一个任务 ID。

**试用解压目录。** 在 paperroom 目录打开两个终端。第一个运行：

    python3 paperroom.py serve

浏览器自动打开。手动访问 http://127.0.0.1:8765/ 也可以。第二个终端在同一目录运行 'codex' 或 'claude'。打开一个新会话后，依次试这两句话：

> 请读 examples/evidence.csv。这是虚构数据。先讨论它能支撑什么 research question、还缺什么证据、要分哪些 section。把我确定的内容记到 project.md。

> 现在请帮我写 Introduction，用两段。我们先定整节逻辑，再按 Paperroom 流程动笔。

**接入已有论文。** 在解压目录运行：

    python3 install.py "/绝对路径/我的论文项目"

安装器将运行代码复制到目标的 paperroom_tool/，保留原有 AGENTS.md 和 CLAUDE.md 并追加项目指引。它也会放入一份可自由编辑的 paperroom-notes.md。从目标论文根目录执行以下命令，并在第二个终端的同一目录开启新的 AI 会话：

    python3 paperroom_tool/paperroom.py serve

讨论时照常使用聊天。AI 建立写作任务后，打开浏览器里的该任务。每次提交后在聊天中说“继续”。换客户端时可以说“读取 Paperroom 状态，继续 Introduction”，它能读到已经提交的作者逻辑和各版本意见。两边的私有对话历史仍由各自的客户端管理。如果不在默认端口，可运行 'serve --port 8780' 并使用终端打印的地址。

## 写作和审稿

- 整节写作依次经过整节复写、每段的句子安排、AI 起草、当前版本图片审阅。进小黑屋可以查看参考。作者可以明确修改原先讨论的结论。
- 只需改已有的一段时，用单段任务直接复写句子安排。普通提问、补资产、改 research question 和调换章节可以随时进行。
- 在浏览器提交前，本次输入随键入暂存于当前浏览器。提交后保存在项目的 .paperroom/project.sqlite3（接入已有项目时位于 paperroom_tool/ 下）。SQLite 事务拒绝旧页面重复提交，两个客户端可读取同一状态。
- 默认每版至少三条各不相同的审阅意见，建任务时通过 '--min-notes' 调整。计数检查只衡量是否提交了规定数量的不同文本。
- 日志可供自己回顾，当前 demo 以明文存储。拥有本地文件权限的人可以编辑文件，项目指引也可被绕过。审稿人可验证的过程证明与加密披露属于后续功能。

## 排版

提供可独立编译的当前 .tex 文件。支持 pdfLaTeX 或 Tectonic；以 Tectonic 首次编译可能需要下载字体/宏包。将 PAPERROOM_TEX_OFFLINE 设为 1 可以仅使用本地 Tectonic 缓存。也能传入在 Overleaf 或项目构建流程中预先编译好的同版 PDF。现有论文含 BibTeX、自定义模板或子文件时，推荐用原构建流程生成 PDF，再选择对应页。预编译 PDF 由提交者确认与源文件相符。

macOS 使用系统 PDFKit 生成图片，其他系统需要 Poppler 的 pdftoppm。'--pages 2-3' 截取 PDF 页；若要精确截到章节底部，用原模板单独排版该节。examples/intro.tex、intro.pdf 和 intro.png 提供了同一份节选的源文件、成品和审阅图。只试 demo.html 无需安装排版工具。

## 手动检查或调试

以下命令在解压目录执行。把 TASK_ID 和 VERSION 替换为 status 的实际值。真实使用中由 AI 执行这些命令，作者只使用浏览器和原来的 AI 对话。

    python3 paperroom.py status
    python3 paperroom.py start Introduction --paragraphs 2 --ref examples/outline.md --min-notes 3
    python3 paperroom.py status TASK_ID
    python3 paperroom.py plan TASK_ID --at VERSION --ref 当前段落的讨论.md
    python3 paperroom.py publish TASK_ID --at VERSION --tex 当前节选.tex
    python3 paperroom.py publish TASK_ID --at VERSION --tex 当前稿.tex --pdf 当前稿.pdf --pages 1-2

每段计划只在作者提交上一阶段后开放。图片审阅只在产生当前稿的排版图后开放。审稿结束后可用新版本号再次发布，前一版的意见继续保留。

运行测试：

    python3 -m unittest discover -s tests -v

官方项目指引文档：[OpenAI Codex](https://developers.openai.com/codex/guides/agents-md/) · [Claude Code](https://code.claude.com/docs/en/memory)
