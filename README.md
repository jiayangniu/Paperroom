# Paperroom

English · [中文](README.zh-CN.md)

Discuss your paper with Claude or Codex in your usual chat. When you’re ready to draft, Paperroom opens a local workspace where you write what each paragraph and sentence should do. The AI drafts from your plan, and you review the typeset pages.

## Install

| Client | How |
| --- | --- |
| Claude Desktop Chat on macOS | Download [Paperroom.mcpb](packages/Paperroom.mcpb) and drag the file onto Settings → Desktop app → Extensions. |
| Claude Code (including VS Code) or Codex | Download and fully extract [Paperroom-Plugin-0.6.12.zip](packages/Paperroom-Plugin-0.6.12.zip), run `python3 install.py` in the extracted folder, then reopen your client. |

Paperroom requires Python 3.9+ and uses the model in your chat.

## A first session with your manuscript

1. **In chat**, ask “Use Paperroom with `/path/to/my-paper`. Read my draft and results. Let’s agree on the research question and sections, then open the writing workspace.”
2. **In the browser**, adopt or edit the sections and write what each Introduction paragraph should do. Click **Save paragraph plan**. Open one paragraph, type each sentence’s job (e.g. “Say which case the earlier experiments missed”), then click **Save and allow drafting**.
3. **In chat**, ask “Draft that paragraph from my saved intents.” Once the whole section is drafted, ask chat to publish it for review.
4. **In the browser**, review the typeset pages and submit pinned notes. After revision, open **Compare section versions** to read both side by side.

In chat, you can also ask the AI to put sentence suggestions in the reference panel or polish a saved paragraph plan. Ask it to call `get_usage()` for the installed version and the [full writing workflow](plugins/paperroom/runtime/README-workflow.md).
