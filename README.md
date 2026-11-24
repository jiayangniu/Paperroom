# Paperroom

English · [中文](README.zh-CN.md)

**Think through your paper with AI—without letting it do the thinking for you.**

In your usual Claude, Codex, or Antigravity chat, say “Use Paperroom to write this paper” and open the local workspace link. You write what each paragraph and sentence should accomplish, the AI drafts the LaTeX prose from your plan, and you review the typeset pages like a referee.

## Why Paperroom

Writing a paper with AI has an easy trap. You start out brainstorming, get tired halfway through, and ask the AI to “just write this section.” Seconds later you get a smooth-looking draft—only to spend more time reading, fact-checking, and rewriting it. Worse, because you skipped organizing the argument yourself, you end up with polished prose whose logic you can barely defend.

Paperroom is built around one simple rule: **discuss freely, but type the framework yourself.**

- **Leave brainstorming to the AI.** Talk through ideas for as many rounds as you want, and drop the AI's suggestions into a side-by-side reference panel whenever they're useful.
- **Own every level of the structure.** How many paragraphs a section needs, what each paragraph proves, and how each sentence connects to the last—you type all of it in the workspace. Copy-paste is disabled on purpose. Rough phrasing is fine; the point is that the logic passes through your own head first.
- **Hand the drafting and busywork to the AI.** Once your outline is written, the AI can polish your wording and draft only the paragraphs you explicitly unlock.
- **Review on real typeset pages.** Pin notes directly onto PDF pages rendered with your paper's template, and have the AI answer each note in the next revision. Compare any two versions side by side, and preview figures and tables in the same workspace.
- **Everything stays local.** Outlines, drafts, versions, and review notes live inside your paper's project folder—no cloud lock-in.

## Install

### Requirements

| Requirement | Notes |
| --- | --- |
| Python 3.9+ | Check with `python3 --version` in Terminal. On macOS, accept the prompt if it asks to install Command Line Developer Tools. |
| A supported chat client | Claude Desktop (Chat) on macOS, Claude Code (including the VS Code extension), Codex, or Google Antigravity. Uses whatever model you already have in chat. |
| LaTeX (for typeset review) | pdfLaTeX or Tectonic. If the ChatGPT desktop app is installed, Paperroom automatically reuses its bundled Tectonic. Not required just for outlining. |
| Poppler (non-macOS only) | Provides `pdftoppm` and `pdftotext` for review page images. macOS uses its built-in PDFKit. |

### Claude Desktop Chat (macOS)

1. Download [Paperroom.mcpb](packages/Paperroom.mcpb).
2. Open Claude Desktop, go to **Settings → Desktop app → Extensions**, drag the file onto the page, and confirm.
3. Start a new chat and type “Call Paperroom's `get_usage`.” If it returns the usage guide, you're set.

### Claude Code / Codex

1. Download [Paperroom-Plugin-0.7.3.zip](packages/Paperroom-Plugin-0.7.3.zip) and **extract the entire archive** (don't copy individual files out).
2. On macOS, double-click `Install-Paperroom.command` in the extracted folder. Or run from Terminal inside that folder:

   ```bash
   python3 install.py
   ```

   The installer detects both Claude Code and Codex and installs Paperroom for each. Pass `--client claude` or `--client codex` to install for just one. Files are copied to `~/.local/share/paperroom/`, so you can delete the extracted folder afterward.
3. Start a new session. In Codex, open `/hooks` to review and enable Paperroom's edit hooks if you want unauthorized prose edits blocked automatically (you may be asked to re-approve after hook updates).
4. Open a session in your paper's folder and type “Call Paperroom's `get_usage`” to verify the installed version.

### Google Antigravity

1. Download and extract [Paperroom-Plugin-0.7.3.zip](packages/Paperroom-Plugin-0.7.3.zip).
2. On macOS, double-click `Install-Antigravity.command`, or run:

   ```bash
   python3 install.py --client antigravity
   ```

3. Restart Antigravity. In a chat inside your paper's folder, say “Use Paperroom to write this paper” (or “Open this paper's Paperroom” for an existing project).

> Note: Antigravity gets the full local workspace and MCP tools, though direct file edits made through the editor or terminal aren't automatically intercepted by Paperroom's writing gate.

### Try it first

Want to see how it feels before touching your own paper? Double-click `Try-Paperroom.command` in the extracted folder to open a sample paper in the workspace and try the three-level outline and version review safely.

### Updating

Updating the plugin never touches your outlines, drafts, or review history—they stay inside your paper's folder.

- **Claude Desktop Chat**: Download the new `Paperroom.mcpb` and drag it onto the **Extensions** page again.
- **Codex (macOS)**: Double-click `Enable-Codex-Updates.command` in the extracted folder (or run `python3 install.py --client codex --auto-update`) to follow releases from GitHub's `main` branch. Start a new Codex session after an update. To disable, run `python3 install.py --client codex --disable-auto-update`.
- **Claude Code**: Double-click `Enable-Claude-Updates.command` once to enable automatic updates.
- **Manual update**: For Claude Code, Codex, or Antigravity, download the new release ZIP and re-run the installer.

## Quick start

The first time in a paper folder, say **“Use Paperroom to write this paper.”** In future chats, say **“Open this paper's Paperroom”** and click the returned local link (include the folder path if you have multiple papers with the same name). You can also use `/paperroom:open` in Claude Code or `$paperroom:open` in Codex.

A typical workflow looks like this:

1. **Share what you have.** Tell the AI where your project, data, notes, or rough draft live, and work out your research question and evidence together.
2. **Settle the paper outline.** Ask the AI to draft the top-level outline, adjust it in the browser, and click **Adopt these sections**.
3. **Talk through one section.** Pick a section (e.g., Method), discuss its subsections and paragraphs in chat, and say “Put this section's paragraph plan in the reference panel.”
4. **Type the paragraph plan yourself.** With the reference on the right, write the subheadings and each paragraph's role in your own words, then click **Save paragraph plan**. Ask the AI to polish the wording if needed.
5. **Type sentence intents the same way.** Discuss how a paragraph unfolds, ask for a sentence reference, write each sentence's intent yourself, and click **Save and allow drafting**.
6. **Draft, save versions, and review.** Say “Draft this paragraph from my saved intents.” When a build is worth keeping, say “Put this version into Paperroom,” leave notes under **Versions & review**, and compare drafts side by side in **Paper versions**.

Before trying a major rewrite, click **Snapshots** in the top-right corner to save a full copy of the project. Whenever you switch back to an older snapshot, Paperroom saves your current state first so neither draft is lost.

For the full walkthrough, example prompts, and figure/table management, see the **[writing guide](docs/writing-guide.md)**.  
*(When the AI calls `get_usage()`, it reads the AI-facing instructions in [README-workflow.md](plugins/paperroom/runtime/README-workflow.md).)*

## Sharing with a coauthor

Click **Snapshots → Export for coauthor** to download a ZIP of your current project (including the manuscript, assets, and synced outline/review drafts—save any open files in external editors first). Check **Include snapshot history** if your coauthor also needs older project snapshots.

They just extract the full ZIP and open the folder in Paperroom. If your project contains symbolic links to files outside the folder, the exporter will point them out so you can replace them with actual files first.

## Troubleshooting

| Issue | What to do |
| --- | --- |
| `未找到本机 Claude Code 或 Codex CLI` (no CLI found) | Install the client and open it at least once. If `claude` or `codex` is in a custom location, add it to your `PATH` and try again. |
| `未发现 codex，已跳过。` (codex not found, skipped) | Normal if you only have one of the two clients installed. |
| Paperroom tools don't show up in chat | Start a new session, ask the AI to call Paperroom's `get_usage` to verify the version, and check that the plugin is enabled in your client. |
| Workspace page shows **Offline for now** | Don't close the tab—ask the AI in any chat to open the workspace, and the page will reconnect automatically in a few seconds. |
| The AI says it can't open the workspace | Make sure your client allows Paperroom tool calls. In the meantime, double-click `~/.local/share/paperroom/Open-Paperroom.command` (in Finder, press `⌘ + ⇧ + G` and paste the path) to pick your paper and open it without the AI. |

Hit something not listed here? To be honest, the author is a beginner who built most of this plugin by chatting with AI. Pasting the error directly into Claude or GPT will probably get you an answer faster than asking the author.

## License

See [LICENSE](LICENSE).
