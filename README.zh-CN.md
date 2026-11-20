# Paperroom

[English](README.md) · 中文

用 Claude 或 Codex 写论文时，你可以在原对话里讨论研究。准备动笔时，Paperroom 会打开本地写作间。你亲手写下每一段、每一句要让读者理解什么，AI 据此起草，再由你审阅排版后的稿件。

## 安装

| 客户端 | 安装方式 |
| --- | --- |
| macOS 上的 Claude 桌面版 Chat | 下载 [Paperroom.mcpb](packages/Paperroom.mcpb)，把文件拖到「设置 → 桌面应用 → 扩展」页面。 |
| Claude Code（含 VS Code 扩展）或 Codex | 下载并完整解压 [Paperroom-Plugin-0.6.12.zip](packages/Paperroom-Plugin-0.6.12.zip)，在解压后的文件夹里运行 `python3 install.py`，再重新打开客户端。 |

需要 Python 3.9 或更高版本，使用你聊天中已有的模型。

## 用现有稿件开始第一次写作

1. **在聊天中**输入「用 Paperroom 打开 `/path/to/my-paper`，读一下我的初稿和实验结果。我们先商定研究问题和章节安排，再打开写作间。」
2. **在浏览器中**采用或修改章节，写下引言每一段的作用，点「保存段落大纲」。打开其中一段，逐句写下意图，例如「指出以前的实验漏掉了哪种情况」，再点「保存并允许起草本段」。
3. **回到聊天**，输入「按我保存的意图起草这一段。」整节起草完成后，再请 AI 发布本节供审阅。
4. **在浏览器中**审读排版页面，提交标注意见。修订后打开 **章节版本对照**，并排比较两版。

想看参考或润色时，在原对话里说「把逐句建议放到参考栏」或「润色我保存的段落大纲」。让 AI 调用 `get_usage()`，即可阅读插件附带的[完整写作流程](plugins/paperroom/runtime/README-workflow.md)，也可顺便查看已安装的版本。
