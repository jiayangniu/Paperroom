# Paperroom

Paperroom 帮助论文作者在 Codex、Claude Code 或 Claude 桌面版的原对话里主导写作。你可以随时讨论研究问题、补充实验、调整论证。准备让 AI 写正文时，打开本地写作间，亲手写下这一段要怎样带着读者理解研究。AI 根据你的句意逐段起草，整节完成后由你对照排版审稿。

## 安装

| 场景 | 安装方式 |
| --- | --- |
| Claude 桌面版 Chat，macOS | 下载 [Paperroom.mcpb](packages/Paperroom.mcpb)。在 Settings → Desktop app → Extensions → Manage → Advanced settings → Install Extension 中选择文件。安装后在聊天输入框旁的 ＋ → Connectors 查看 Paperroom。 |
| Claude Code，自动更新 | 下载 [Enable-Claude-Updates.command](Enable-Claude-Updates.command) 后在 macOS 运行。也可以在解压的插件包里双击同名文件。 |
| Claude Code 或 Codex | 下载并完整解压 [Paperroom-Plugin-0.3.0.zip](packages/Paperroom-Plugin-0.3.0.zip)。在 macOS 双击 `Install-Paperroom.command`，或在解压目录运行 `python3 install.py`。使用源码时也可以直接从仓库根目录运行安装器。 |

使用本地 Python 3.9 或以上版本。终端安装器会查找已经安装的客户端。只安装一边可运行 `python3 install.py --client claude` 或 `python3 install.py --client codex`。安装后重新载入插件或重新打开客户端。插件使用现有对话中的 AI，无需单独的模型 API key。

**已装旧版的 Claude Code 用户**也只需运行一次 [Enable-Claude-Updates.command](Enable-Claude-Updates.command)。它把用户级的 Paperroom 更新源切换到本项目的 GitHub 分支 `v2-author-workspace`，安装该分支上的新版，并开启 Claude Code 自带的自动更新。私有仓库需要本机 Git 已有读取权限。成功后可重新打开本地 Claude Code 会话，或在本地 Claude Code 交互终端输入 `/reload-plugins`。桌面版的聊天气泡使用单独的 Paperroom 桌面扩展，可在该对话的 ＋ → Connectors 中查看。以后作者在该分支发布新版本时，Claude Code 会在启动会话后后台检查。可在 `/plugin` 的 **Marketplaces → paperroom-local** 中管理这个开关。

使用离线安装方式时，每次升级可运行新包内的 `Install-Paperroom.command`。在 Claude 桌面版 Chat 里重新选择新版 MCPB 文件。已有单节任务仍可通过 `writing_status` 查看或用原来的任务 ID 继续。第二版的三级大纲在同一论文项目中独立开始记录。

## 从论文资料开始

在原聊天里指明你的论文目录，尤其是在客户端能访问多份稿件时。初稿、PDF、表格和图片可以放在这个目录，继续借助客户端原有的文件工具与 AI 讨论。切换客户端后选用同一个目录即可取回写作进度。

> 先读论文初稿和实验结果，和我讨论研究问题与证据。把已经确定的 research question 和实验摘要记到 Paperroom。

> 用 Paperroom 帮我写 Introduction，我们先讨论本节第一段的作用。

项目的 `paper.md` 汇集研究问题、实验证据和三级大纲。可保留大片空白，先展开今天要写的部分。

| 作者填写 | 可以参考 | 下一步 |
| --- | --- | --- |
| 整篇有哪些节、每一节的作用 | 项目的研究问题和当前实验结果概述 | 任选一节规划段落 |
| 这一节有哪些段、各段怎样衔接 | 已定的论文大纲和研究材料 | 任选一段安排句意 |
| 这一段的每句话要说什么 | 所属节的段落计划和相关证据 | AI 可以起草这一段 |

句意用自己熟悉的语言写即可。可以把论证写到“先解释这个观察，再说明它支撑什么，最后指出比较没有覆盖的条件”。写完这一层就回到原聊天让 AI 继续。其余的段落和章节可以稍后再规划。

## 审阅成稿

整节各段准备好后，从原聊天请求编译并打开该版的论文节选。作者在浏览器里对照大纲阅读版面，将修改意见或保留理由落在具体位置。提交足够的意见后，把已审阅的版本交回 AI。再次发布会产生新版本，可对照标出的变化和旧版反馈复查。

渲染可以使用独立编译的 LaTeX 节选，也可以使用按论文原模板生成的匹配 PDF 和页码范围。编译 `.tex` 需要 Tectonic 或 pdfLaTeX。生成页图优先使用 Poppler 的 `pdftoppm`，macOS 还可以使用系统 PDFKit。

作者表单及版本记录保存在本机。模型可读取的材料遵循所用客户端的权限和服务设置。Paperroom 的阶段约束适用于它处理的起草和发布请求，宿主聊天仍有直接输出文本的能力。当前记录适合作者复查和交接；审稿人认证属于后续设计。

## 本地体验和开发

在 macOS 解压插件包或下载完整仓库后，可以双击 [Try-Paperroom.command](Try-Paperroom.command)，打开一份可直接批注的虚构论文。每次启动都会创建独立样例，关闭服务后清理本次样例。真实论文请在解压目录或仓库根目录运行以下命令，并传入已有的论文目录。

```sh
python3 plugins/paperroom/runtime/workspace_server.py /absolute/path/to/paper
```

完整的 AI 草拟流程需要在已连接插件的客户端中进行。第一版的 [离线演示](demo/demo.html) 也保留在仓库中，可用浏览器直接打开。

从仓库运行测试，并重新生成两种安装包：

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_packages.py
```

向自动更新用户发布运行时改动时，需要同步递增 Claude Code、Codex 插件清单和 MCP 服务的版本号，再将新版本推送到 `v2-author-workspace`。[Claude Code 插件发布说明](https://code.claude.com/docs/en/plugins/host-marketplace#keep-users-up-to-date)

源码使用 MIT 许可。终端客户端可通过各自的插件管理界面卸载 Paperroom，论文目录内的写作记录由作者保管。
