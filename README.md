# Paperroom

English · [中文](README.zh-CN.md)

Paperroom keeps the author in charge of a paper written with an AI assistant in Codex, Claude Code or the Claude desktop app. Talk through research questions, experiments and arguments in your usual chat. When it is time for the AI to write prose, you open a local workspace and write, in your own words, what each paragraph should do for the reader. The AI drafts paragraph by paragraph from those intents, and you review each section as typeset pages.

## Install

| Setup | How |
| --- | --- |
| Claude desktop Chat, macOS | Download [Paperroom.mcpb](packages/Paperroom.mcpb). In Settings → Desktop app → Extensions → Manage → Advanced settings → Install Extension, choose the file. Paperroom then appears under ＋ → Connectors next to the chat box. |
| Claude Code with automatic updates | Download and run [Enable-Claude-Updates.command](Enable-Claude-Updates.command) on macOS, or double-click the same file in the extracted plugin package. |
| Claude Code or Codex | Download and fully extract [Paperroom-Plugin-0.6.12.zip](packages/Paperroom-Plugin-0.6.12.zip). On macOS double-click `Install-Paperroom.command`, or run `python3 install.py` in the extracted folder. From a source checkout you can run the installer from the repository root. |

Paperroom needs local Python 3.9 or later and uses the model in your existing chat. For Claude Code (including its VS Code extension) or Codex, install just the client you use with `python3 install.py --client claude` or `python3 install.py --client codex` from the extracted folder. Reopen the client. In your manuscript chat, ask **“Call Paperroom’s `get_usage()` tool and tell me the installed version.”** The tool returns the version and the matching usage guide.

Existing Claude Code users only need to run [Enable-Claude-Updates.command](Enable-Claude-Updates.command) once. It points the user-level Paperroom source at this repository's `v2-author-workspace` branch, installs the version there and turns on Claude Code's automatic updates (a private repository needs local Git read access). Then reopen your Claude Code session or run `/reload-plugins`. Manage the switch under `/plugin` → **Marketplaces → paperroom-local**. For offline installs, run `Install-Paperroom.command` from each new package. To update the desktop Chat extension, install the new [Paperroom.mcpb](packages/Paperroom.mcpb).

Codex asks you to approve Paperroom's hooks once in `/hooks` (and again after an update changes them).

## Language

The workspace has Chinese and English interfaces. It follows your browser's language, and the switch in the top-right corner changes it at any time. Paperroom's messages to the AI and its tool errors follow the same choice. Write intents and review notes in any language. Switching the interface language preserves the original text.

## First session with an existing draft

1. **In your usual chat**, give the client access to the folder containing your manuscript and results. For example, ask “Use Paperroom with `/path/to/my-paper`. Read my draft and experiments. What research question does the evidence support?” Once you agree, ask it to record the question and evidence and propose the sections.
2. **In the browser workspace**, adopt or edit the section list. Open Introduction, write what each paragraph should accomplish, and choose **Save paragraph plan**. You can work on one section at a time.
3. **For one paragraph**, open its sentence plan. If you want guidance, ask in chat “Put a sentence-by-sentence reference for Introduction paragraph 1 in its reference panel.” In the workspace, type your own sentence intents and choose **Save and allow drafting**. Return to the same chat and ask “Draft Introduction paragraph 1 from my saved intents.”
4. **Review the typeset result.** Once the section's paragraphs are drafted, ask the AI to publish Introduction for review. Read the pages in the workspace, pin your observations and submit them. Ask in chat for the next revision, then open **Compare section versions** to read the two editions together.

Resume from any connected client by naming the same manuscript folder. It contains the outline in `paper.md` and the project database with saved progress and reviews. Submit edits in an open workspace before upgrading, especially when moving from 0.6.2. For help at any step, ask the AI to read the [guide included with the plugin](plugins/paperroom/runtime/README-workflow.md).

## The three outline levels

| Level | Who writes it | For reference | Next |
| --- | --- | --- | --- |
| The paper's sections and each one's role | The AI drafts it after you discuss the structure; you adopt or edit it | The research question, a summary of results and an optional AI reference for the whole paper | Plan the paragraphs of any adopted section |
| A section's paragraphs and how they connect | You | The paper outline, materials and the AI's reference for this section | Write sentence intents for any paragraph |
| What each sentence of a paragraph says | You | Your section plan, the relevant evidence and the AI’s sentence-by-sentence reference | The AI can draft this paragraph |

The section list is usually short, so the AI drafts it with `propose_paper_outline` (for an existing paper, from its `\section` headings). Read it in the workspace and press **Adopt**, or edit and save it; a section's paragraph plan opens only once adopted, and the writing log records who drafted and who adopted.

Insert optional subheadings between paragraphs while planning a section. Use **Delete paragraph** to remove a row and **Undo last deletion** to restore it before saving. On desktop, scroll the AI reference beside the editor. After you submit the plan, the AI in your chat can use your paragraph purposes and the section reference to suggest what each sentence should cover and how it follows the previous one. Type your own intents, including literal LaTeX such as `$\Delta = r - p$`.

Use chat to direct the AI at any outline level. “Generate a reference for the paper outline and put it in the panel” creates and saves it in one turn. “Polish the saved role of Method paragraph 2” updates that paragraph. “Show me two ways to express the intent for sentence 3” keeps the options in chat until you choose one to save. You can keep editing your outline in the workspace. [Writing workflow for AI assistants](plugins/paperroom/runtime/README-workflow.md)

Type your paragraph plans, intents and review notes yourself: the author fields block copy, cut, paste and drag-and-drop. The research question and materials can be pasted as usual. Intents can be plain notes, e.g. "explain this observation, say what it supports, then name the conditions the comparison does not cover". When a level is written, go back to the chat and let the AI continue.

## Prose lives in your LaTeX source

Paperroom reads the paper's main `.tex`, including files pulled in with `\input` and `\include`. Each outline section is the `\section` with the same title; its paragraphs are separated by blank lines and match the author's paragraph plan in order. Figures, tables and comments are not prose; display math belongs to its paragraph. The AI writes a paragraph into the source and then registers it; no second copy is kept by hand.

Small edits need no checkpoint: wording, sentence order, citations, equations. The Claude Code and Codex plugins check every edit before it is written: a change that adds a paragraph, or rewrites more than half of one, is refused if the author has not written that paragraph's sentence intents, and the AI is told which paragraph and where to fill in the outline. Successive small edits add up, so splitting a rewrite into steps does not get around the check. Paragraphs the author wrote by hand can still be polished. Very short additions (under about 20 English words or 40 Chinese characters) are not limited. The AI cannot edit `paper.md`, where the outline lives. Shell commands cannot be checked in advance; they are checked afterwards and the AI is asked to undo whole-paragraph writes. The desktop Chat does not edit files and is not affected.

When publishing or saving an original, Paperroom compiles the paper in a temporary folder and keeps the physical pages from the section's heading to its end, so roman front matter and `\include` page breaks are handled; nothing is written into the paper folder. With several main files, or a section title that differs from the outline, the AI can use `bind_section_source`. Projects without a main LaTeX file keep the earlier flow, where prose is registered with each draft. Existing projects need no migration: published versions and reviews stay as they are, and stored drafts become registration snapshots.

## Review and further rounds

When every paragraph of a section is drafted, ask in the chat for the section to be published. Read the typeset pages next to your outline and pin observations, keep or change, to exact places. Submitting returns the reviewed version to the AI.

Compiling from source requires Tectonic or pdfLaTeX. You can also supply a matching, already compiled PDF with the section’s page range. Page previews use Poppler’s `pdftoppm` or, on macOS, PDFKit.

For the next version the AI must answer every note: revised, kept as is, or disagrees, each with a reason; missing or duplicate answers are refused. The new version opens with those answers next to your notes and says which paragraphs changed. The first version needs at least 3 notes by default, later ones at least 1, and from the second version on you can choose **Approve, no new notes**.

## Before and after

Choose a section from the paper contents and open **Compare section versions**. The latest published edition appears beside the previous one. For example, publishing Method edition 3 makes editions 2 and 3 the comparison pair. On the first rewrite, Paperroom uses the original saved before publication. With only one layout, it shows that layout on its own. Earlier review links still open the saved editions that their observations refer to.

On desktop the two layouts scroll together. The **Before / After** switch on the review page keeps your reading position and any observation you are typing. On phones, switch between layouts in the full-screen reader and use **Text width** or **2×** to enlarge the text.

You can also import an existing PDF, or a standalone TeX file, under **Import existing draft**, with the section's pages such as `2-4`.

## View prepared figures and tables

Ask the AI in your manuscript chat to create or revise a figure or table and save the result in one of these folders. Paths start at the root of the manuscript project. The AI can create the folder when saving the first file using the chat client’s file tools. You can also place an existing export there yourself.

| Prepared item | Folder | Accepted formats |
| --- | --- | --- |
| Figure | `paperroom-assets/figures/` | PNG, JPEG, WebP, PDF |
| Table | `paperroom-assets/tables/` | PDF compiled from LaTeX |

> Update the benchmark table in LaTeX using the results we discussed. Compile it, save the successful output to `paperroom-assets/tables/Method/benchmark.pdf`, and open it in Paperroom’s figures and tables panel.

Open **Figures & tables** at the top of the workspace. Its two tabs display the prepared files, including optional subfolders such as `Method/`. Give feedback in chat and have the AI update the same filename. Click **Refresh figures and tables** to see the new export. To see how the figure or table appeared on a published page, open the section comparison.

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
