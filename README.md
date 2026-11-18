# Paperroom

Paperroom 是本地学术写作插件。平时在原聊天里讨论数据、研究问题和论文结构。请 AI 写正文时，作者先在浏览器里复写本节逻辑和每段的句子安排。AI 按作者的意思起草后，作者看 LaTeX 编译的节选并留下本版意见。

## 选择使用方式

| 使用场景 | 入口 |
| --- | --- |
| 在 Claude 桌面版 Chat 的原对话里继续写论文 | 下载 [Paperroom.mcpb](packages/Paperroom.mcpb)，在 Claude 的 Settings → Desktop app → Extensions → Manage → Advanced settings → Install Extension 中选择该文件。安装后在聊天输入框的 ＋ → Connectors 查看 Paperroom。 |
| 在 Claude Code 或 Codex 里工作 | 下载 [Paperroom-Plugin-0.2.0.zip](packages/Paperroom-Plugin-0.2.0.zip)，按下节说明安装。也可以从克隆的仓库根目录运行安装器。 |
| 离线体验作者如何复写和审阅 | 下载仓库后，用浏览器打开 [demo/demo.html](demo/demo.html)。示例中的实验数据是虚构的。 |

## 安装 Claude Code 或 Codex 插件

在 macOS 解压完整目录，运行其中的 **Install-Paperroom.command**。也可以在解压目录的终端运行：

    python3 install.py

需要 Python 3.9+ 和本机的 Claude Code 或 Codex CLI。安装器会识别 PATH 上的客户端，以及常见的 macOS Codex 应用和 Claude Code VS Code 扩展内附的 CLI。若检测到两个客户端，将在两边安装并验证启用状态。只装一边可运行 python3 install.py --client claude 或 python3 install.py --client codex。

安装器在用户目录的 ~/.local/share/paperroom 下保存版本化的本地插件源，并调用各客户端自己的插件管理命令。它不修改任何论文或论文目录的指引。安装不需要单独的模型 API key 或 pip 软件包。受组织管理的客户端以其允许的本地插件和 MCP 权限为准。

在已打开的 Claude Code 对话中运行 /reload-plugins；如果当前界面未提供该命令，重新打开客户端并恢复原对话。在 Codex CLI 安装后启动新的会话。保持原论文目录为工作目录。这个包面向本机 Claude Code、Codex CLI 及能加载本地 Codex 插件的客户端。网页端和远程工作区需要在其执行环境中另行接入。

## 日常使用

“这组结果支持什么结论？”继续自由讨论。

“请按刚讨论的逻辑帮我写摘要。”客户端调用 Paperroom，浏览器自动打开作者输入页。若客户端请求本地工具权限，按界面提示处理；若系统未能自动打开浏览器，聊天中会返回本机链接。

在小黑屋提交后，回到原聊天说“继续”。客户端读取作者的思路，讨论下一段或逐句安排，起草后编译并打开该版的审阅页面。如果宿主没有识别写作意图，可以明确说“用 Paperroom 帮我重写这段”。插件通过客户端选择工具触发，无法拦截宿主所有自由文本输出。

换论文时使用对应项目的目录，例如这个论文的 main.tex 所在目录。如果一个聊天能访问多个项目，请在有歧义时指明论文。记录写入该项目的 .paperroom/project.sqlite3。已经安装旧 demo 的项目会自动沿用 paperroom_tool/.paperroom/project.sqlite3，任务 ID、作者输入及版本审稿意见保留。不同物理副本各有自己的数据，请在两个客户端选择同一个论文目录。

浏览器服务由本机 MCP 进程在第一次需要时启动，仅监听回环地址并自动选择可用端口。每个客户端会话可以有自己的浏览器地址，提交后共享同一个项目数据库。客户端会话结束后，旧链接可能失效；在新会话说“用 Paperroom 打开上次的摘要任务”即可。从旧 demo 切换时，两边只要指向同一数据库，原页面和插件都能继续处理已提交的内容。未提交文字暂存在原页面的浏览器存储，请先在那里提交。

## 排版与隐私

发布支持可独立编译的 .tex 节选或论文自己的构建流程生成的同版 PDF 和页码范围。生成图片时优先使用 Poppler 的 pdftoppm，macOS 可直接使用系统 PDFKit。从 .tex 编译需要 Tectonic 或 pdfLaTeX。论文和作者记录在本机保存为明文。调用模型的内容仍遵循所选 AI 客户端的服务设置。此版本不提供审稿人认证。

## 分发与开发

源代码采用 MIT 许可。压缩包包含两个客户端各自的本地插件目录清单及共享的 stdio MCP 运行时。插件提供 begin_writing、writing_status、set_paragraph_reference、publish_draft 和 open_author_room。作者提交只在浏览器表单中进行。后台程序依赖 Python 标准库。

    python3 -m unittest discover -s tests -v

卸载可使用各客户端的 Plugins 管理界面，或执行 claude plugin uninstall paperroom@paperroom-local --scope user、codex plugin remove paperroom@paperroom-local。论文项目的写作记录保存在项目中。
