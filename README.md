# Paperroom

English · [中文](README.zh-CN.md)

Discuss your paper with Claude or Codex in your usual chat. When you’re ready to draft, Paperroom opens a local workspace where you write what each paragraph and sentence should do. The AI drafts from your plan, and you review the typeset pages.

Talking a paper through with an AI over many rounds makes the thinking clearer, but it's tempting to let the AI generate long passages and then spend hours reworking them. Paperroom's rule: **discuss freely, but type the framework yourself.**

- **Leave discussion and suggestions to the AI.** Talk for as many rounds as you like. The AI's suggestions can go into a reference panel beside your writing at any time.
- **Write the framework yourself.** How many paragraphs a section has, what each should say, what each sentence does: you type all of it in the workspace. It doesn't have to be precise, but it has to be yours. Text from the reference can't be pasted in.
- **Then let the AI help.** The AI can polish what you wrote, and it drafts only paragraphs you have allowed.
- **Review on typeset pages.** Each section is typeset in your paper's template. You pin notes on the pages and the AI answers each one. You can read old and new versions side by side and view figures and tables in the workspace.
- **Everything stays local.** Outlines, drafts and review history are saved in your paper's project folder.

## Install

### Requirements

| You need | Notes |
| --- | --- |
| Python 3.9 or later | Check with `python3 --version` in Terminal. If macOS offers to install the command line developer tools, accept. |
| A chat client | Claude Desktop (Chat) on macOS, Claude Code (including the VS Code extension) or Codex. Paperroom uses the model in your chat. |
| LaTeX, for typeset review | pdfLaTeX or Tectonic. If the ChatGPT desktop app is installed, Paperroom uses its bundled Tectonic. Not needed for outlining. |
| Poppler, outside macOS only | Provides `pdftoppm` and `pdftotext` for review page images. macOS uses its built-in PDFKit. |

### Claude Desktop Chat (macOS)

1. Download [Paperroom.mcpb](packages/Paperroom.mcpb).
2. In Claude Desktop, open Settings → Desktop app → Extensions, drag the file onto the page and confirm.
3. Start a new chat and type “Call Paperroom's get_usage.” If the usage guide comes back, Paperroom is installed.

### Claude Code or Codex

1. Download [Paperroom-Plugin-0.6.15.zip](packages/Paperroom-Plugin-0.6.15.zip) and **extract the whole archive**. Don't copy out individual files.
2. On macOS, double-click `Install-Paperroom.command` in the extracted folder. Or open Terminal in that folder and run:

   ```bash
   python3 install.py
   ```

   The installer finds Claude Code and Codex on your computer and installs Paperroom for both. Add `--client claude` or `--client codex` to install for just one. The plugin is copied to `~/.local/share/paperroom/`, so you can delete the extracted folder afterwards.
3. Quit and reopen your client. The first time you use it, Codex asks you to approve Paperroom's writing checks once in `/hooks`.
4. Open a session in your paper's folder and type “Call Paperroom's get_usage” to confirm the installed version.

### Try it first

`Try-Paperroom.command` in the extracted folder opens the workspace with a fictional sample paper. You can try the three-level outline and version review without touching any of your files.

### Update

- **Claude Desktop Chat**: download the new `Paperroom.mcpb` and drag it onto the Extensions page again.
- **Claude Code or Codex**: download and extract the new archive, run `install.py` again, then reopen your client. Claude Code users can instead double-click `Enable-Claude-Updates.command` once to receive updates automatically.

Your outlines, drafts and review history live in your paper's project, so updating the plugin leaves them untouched.

### If installation fails

| Message | What to do |
| --- | --- |
| `未找到本机 Claude Code 或 Codex CLI` (no Claude Code or Codex CLI found) | Install the client and open it once. If `claude` or `codex` lives in an unusual place, add it to your PATH and try again. |
| `未发现 codex，已跳过。` (codex not found, skipped) | Expected when only one of the two clients is installed. |
| Paperroom's tools don't appear in chat | Quit and reopen the client completely. In Codex, also approve the hooks once in `/hooks`. |
| The workspace page says **Offline for now** | Ask the AI in any chat to open the workspace. The open page reconnects by itself; no need to close it. |

Not in the table? Honestly, the author is a beginner who built most of this plugin by chatting with AI. Paste the error into Claude or GPT; they'll probably sort it out faster than the author would.

## Your first session

1. **Start with what you have.** In chat, type “Use Paperroom to start a paper in `~/papers/my-paper`. The data is in `results/`, roughly I want to show …, and there's an earlier draft in `main.tex`.” The AI works out the research question and evidence with you.
2. **Discuss and settle the paper outline.** When the discussion feels about right, ask the AI to draft the paper outline. Edit it in the browser and click **Adopt these sections**.
3. **Pick a section and discuss its structure over several rounds.** For example, what Method does, how many subsections it needs and what each paragraph should say. Then say “Put this section's paragraph plan in the reference panel.”
4. **Write the paragraph plan by hand beside the reference.** In the browser, type the subheadings and each paragraph's role in your own words, then click **Save paragraph plan**. Ask the AI to “polish the role of paragraph 2” if you like.
5. **Sentence intents work the same way.** Discuss how a paragraph unfolds, ask for a sentence reference, type each sentence's intent yourself, then click **Save and allow drafting**.
6. **Draft, review, compare.** Say “Draft this paragraph from my saved intents.” When a build is worth keeping, say “Put this version into Paperroom” and pin notes under **Versions & review**; **Paper versions** shows the latest only or two versions side by side.

See the **[writing guide](docs/writing-guide.md)** for every step in detail, what to say in chat and how to view figures and tables.

When the AI calls `get_usage()` in chat, it reads the [instructions shipped with the plugin](plugins/paperroom/runtime/README-workflow.md). That document is written for the AI.

## License

See [LICENSE](LICENSE).
