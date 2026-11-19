# Paperroom

English · [中文](README.zh-CN.md)

Paperroom keeps the author in charge of a paper written with an AI assistant in Codex, Claude Code or the Claude desktop app. Talk through research questions, experiments and arguments in your usual chat. When it is time for the AI to write prose, you open a local workspace and write, in your own words, what each paragraph should do for the reader. The AI drafts paragraph by paragraph from those intents, and you review each section as typeset pages.

## Install

| Setup | How |
| --- | --- |
| Claude desktop Chat, macOS | Download [Paperroom.mcpb](packages/Paperroom.mcpb). In Settings → Desktop app → Extensions → Manage → Advanced settings → Install Extension, choose the file. Paperroom then appears under ＋ → Connectors next to the chat box. |
| Claude Code with automatic updates | Download and run [Enable-Claude-Updates.command](Enable-Claude-Updates.command) on macOS, or double-click the same file in the extracted plugin package. |
| Claude Code or Codex | Download and fully extract [Paperroom-Plugin-0.6.2.zip](packages/Paperroom-Plugin-0.6.2.zip). On macOS double-click `Install-Paperroom.command`, or run `python3 install.py` in the extracted folder. From a source checkout you can run the installer from the repository root. |

Paperroom needs a local Python 3.9 or later. The installer finds the clients you have; install for one only with `python3 install.py --client claude` or `python3 install.py --client codex`. Reload plugins or restart the client afterwards. Paperroom uses the AI in your existing chat; no separate model API key is needed.

Existing Claude Code users only need to run [Enable-Claude-Updates.command](Enable-Claude-Updates.command) once. It points the user-level Paperroom source at this repository's `v2-author-workspace` branch, installs the version there and turns on Claude Code's automatic updates (a private repository needs local Git read access). Then reopen your Claude Code session or run `/reload-plugins`. Manage the switch under `/plugin` → **Marketplaces → paperroom-local**. For offline installs, run `Install-Paperroom.command` from each new package. To update the desktop Chat extension, install the new [Paperroom.mcpb](packages/Paperroom.mcpb).

Codex asks you to approve Paperroom's hooks once in `/hooks` (and again after an update changes them).

## Language

The workspace has Chinese and English interfaces. It follows your browser's language, and the switch in the top-right corner changes it at any time. Paperroom's messages to the AI and its tool errors follow the same choice. Write intents and review notes in any language; Paperroom never changes the author's own words.

## Start from your materials

Name your paper's folder in the chat, especially when the client can see several manuscripts. Keep drafts, PDFs, tables and figures there and keep discussing them with the AI as usual. Switching clients, use the same folder to pick up where you left off.

> Read my draft and results, and discuss the research question and evidence with me. Record the agreed research question and a summary of the experiments in Paperroom.

> Use Paperroom to write the Introduction. Let's first discuss what its first paragraph should do.

The project's `paper.md` gathers the research question, the evidence and a three-level outline. Large parts can stay empty; expand only what you write today.

| Level | Who writes it | For reference | Next |
| --- | --- | --- | --- |
| The paper's sections and each one's role | The AI drafts it after you discuss the structure; you adopt or edit it | The research question and a summary of results | Plan the paragraphs of any adopted section |
| A section's paragraphs and how they connect | You | The paper outline, materials and the AI's reference for this section | Write sentence intents for any paragraph |
| What each sentence of a paragraph says | You | The section plan and the relevant evidence | The AI can draft this paragraph |

The section list is usually short, so the AI drafts it with `propose_paper_outline` (for an existing paper, from its `\section` headings). Read it in the workspace and press **Adopt**, or edit and save it; a section's paragraph plan opens only once adopted, and the writing log records who drafted and who adopted. The AI may leave a short reference beside a section's paragraph plan (`suggest_section_plan`); the plan itself is yours.

Type your paragraph plans, intents and review notes yourself: the author fields block copy, cut, paste and drag-and-drop. The research question and materials can be pasted as usual. Intents can be plain notes, e.g. "explain this observation, say what it supports, then name the conditions the comparison does not cover". When a level is written, go back to the chat and let the AI continue.

## Prose lives in your LaTeX source

Paperroom reads the paper's main `.tex`, including files pulled in with `\input` and `\include`. Each outline section is the `\section` with the same title; its paragraphs are separated by blank lines and match the author's paragraph plan in order. Figures, tables and comments are not prose; display math belongs to its paragraph. The AI writes a paragraph into the source and then registers it; no second copy is kept by hand.

Small edits need no checkpoint: wording, sentence order, citations, equations. The Claude Code and Codex plugins check every edit before it is written: a change that adds a paragraph, or rewrites more than half of one, is refused if the author has not written that paragraph's sentence intents, and the AI is told which paragraph and where to fill in the outline. Successive small edits add up, so splitting a rewrite into steps does not get around the check. Paragraphs the author wrote by hand can still be polished. Very short additions (under about 20 English words or 40 Chinese characters) are not limited. The AI cannot edit `paper.md`, where the outline lives. Shell commands cannot be checked in advance; they are checked afterwards and the AI is asked to undo whole-paragraph writes. The desktop Chat does not edit files and is not affected.

When publishing or saving an original, Paperroom compiles the paper in a temporary folder and keeps the physical pages from the section's heading to its end, so roman front matter and `\include` page breaks are handled; nothing is written into the paper folder. With several main files, or a section title that differs from the outline, the AI can use `bind_section_source`. Projects without a main LaTeX file keep the earlier flow, where prose is registered with each draft. Existing projects need no migration: published versions and reviews stay as they are, and stored drafts become registration snapshots.

## Review and further rounds

When every paragraph of a section is drafted, ask in the chat for the section to be published. Read the typeset pages next to your outline and pin observations, keep or change, to exact places. Submitting returns the reviewed version to the AI.

For the next version the AI must answer every note: revised, kept as is, or disagrees, each with a reason; missing or duplicate answers are refused. The new version opens with those answers next to your notes and says which paragraphs changed. The first version needs at least 3 notes by default, later ones at least 1, and from the second version on you can choose **Approve, no new notes**.

## Before and after

When an existing section is rewritten, Paperroom saves the original pages of that section the first time the AI reads its status, before any edit. **Layouts & comparison** shows before and after side by side on desktop, scrolling together; later rounds compare with the previous version. A section with only one layout shows just that one. On the review page, the **Before / After** switch flips the manuscript in place at the same reading position while your half-written observation stays put. On phones the comparison fills the screen with the same switch, and **Text width** or **2×** makes the text readable.

You can also import an existing PDF, or a standalone TeX file, under **Import existing draft**, with the section's pages such as `2-4`.

## Figures & data

Figures and tables are usually settled before the prose. Their LaTeX is not prose, so the AI writes it directly and then calls `publish_floats`, which compiles the whole paper and records the page each figure and table actually lands on. **Figures & data** in the top-right corner shows:

- the latest build, who started it, and whether the source changed since; you can press **Recompile** too;
- **Instructions for the AI**: choose a figure or table (or a new one) and write what should change. The AI sees open instructions the next time you send a chat message, recompiles and answers each one. Open instructions can be withdrawn;
- every figure and table on its real page, with number, `\label`, caption, section and source location. **Confirm** marks one as settled and shows if it changes later; it never blocks drafting;
- images not yet used in the paper, and CSV/TSV data.

Numbers come from the paper's last `.aux` when present, otherwise from their order. Compilation uses Tectonic or pdfLaTeX (including the Tectonic bundled with the ChatGPT desktop app); page images use Poppler's `pdftoppm` or PDFKit on macOS.

Your forms and versions stay on this computer. What the model can read follows your client's permissions and service settings. Paperroom's checkpoints apply to the drafting and publishing it handles; the host chat can still output text directly.

## Writing log and offline verification

**Writing log** in the top-right corner lists, in order, the local time of each outline submission, published section version and submitted review. By default records stay in the paper project; no cloud account or blockchain is involved.

To let reviewers verify when content existed, enter an RFC 3161 authority's HTTPS address in the desktop extension's timestamp setting, or set `PAPERROOM_TSA_URL` for terminal clients and restart. Choose a record and press **Request a third-party timestamp**: only a salted SHA-256 digest is sent, and the verified receipt is kept. This needs OpenSSL with `openssl ts`; for a private CA set `PAPERROOM_TSA_CA_FILE`.

**Download verification bundle** exports JSON. **Check the file before sharing**: it contains outlines, intents, recorded drafts and review notes. Reviewers can verify it offline:

```sh
python3 scripts/verify_timestamps.py paperroom-timestamps.json
# with a CA the reviewer trusts
python3 scripts/verify_timestamps.py paperroom-timestamps.json --ca-file trusted-ca.pem
```

Each valid receipt shows that the event and the records before it existed by the signed UTC time, which may be later than the local time. An export only covers the records it contains; it cannot show whether later events were left out, who typed, or how much thought went in.

## Try it and develop

On macOS, double-click [Try-Paperroom.command](Try-Paperroom.command) in the extracted package or repository to open a sample paper you can annotate; each run uses a fresh copy. For a real paper:

```sh
python3 plugins/paperroom/runtime/workspace_server.py /absolute/path/to/paper
```

The full AI drafting flow runs in a client with the plugin connected. The first version's [offline demo](demo/demo.html) is still in the repository.

Run the tests and rebuild both packages:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_i18n.py
python3 scripts/build_packages.py
```

When releasing runtime changes to auto-updating users, raise the version in the Claude Code and Codex plugin manifests and the MCP server together, then push to `v2-author-workspace`. See [keeping Claude Code users up to date](https://code.claude.com/docs/en/plugins/host-marketplace#keep-users-up-to-date).

MIT licensed. Uninstall Paperroom from each client's plugin manager; the writing records in your paper folder remain yours.
