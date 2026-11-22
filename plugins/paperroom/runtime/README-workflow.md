# Paperroom workflow for AI assistants

When the author asks how Paperroom works, call `get_usage()` from Claude Chat, Claude Code or Codex. It takes no arguments and works before selecting a manuscript. Authors read their own guide in `docs/writing-guide.md`.

## Choosing a project and opening its workspace

A request to discuss, write or rewrite a paper on its own does not opt a project into Paperroom. Start its workflow when the author explicitly requests Paperroom for that manuscript. Installing the plugin, opening a new chat, and asking what Paperroom does are not requests to create a workspace.

| What the author asks | Action |
| --- | --- |
| “Use Paperroom to manage this paper” / “用 Paperroom 管理这篇论文” | Call `activate_project(project=…)` once with the absolute manuscript folder. This also returns the workspace link. |
| “Open Paperroom for this paper” / “打开这篇的 Paperroom 写作间” | Call `open_writing_workspace(project=…)` for the existing workspace. If the folder is unmanaged, ask whether to enable it before creating anything. |
| Open a coauthor's copy | Use `open_writing_workspace(project=…)` with the local path of the copied project, including its Paperroom database. |

In Claude Code the author can type `/paperroom:open`. In Codex the author can type `$paperroom:open`. In Claude desktop Chat the author names the manuscript in a message. Resolve the manuscript from that window and pass its absolute `project` path on subsequent calls. If several manuscripts are possible, ask which folder to use. Each paper has its own workspace.

In Claude desktop Chat, activation or opening returns a private `workspace_session` tool argument for the selected folder. Supply it on subsequent project tool calls from this conversation. Keep it out of messages to the author, notes, files, logs and links. If the extension restarts and this argument expires, reopen the same previously selected manuscript to obtain a fresh one. Claude Code and Codex do not require this argument.

Return the exact `room_url` as a clickable link, including any path, query or fragment. The link opens on the machine running Paperroom. If an open page went offline, call `open_writing_workspace` for that same project. If a tool fails without a link, report its name and the actual error. For a client approval error, ask the author to approve the specific action in the client if available. Avoid guessing that their computer is offline or substituting shell commands after a denial.

If an earlier `update_research_assets` call reported a permission error, read the same manuscript with `workspace_status`. Continue if both saved fields match. If they differ, report what was read and the original error before proposing another write.

If `workspace_status` reports `tex_available: false`, Paperroom can't compile on this computer. `save_version` then keeps the PDF you compiled for the main `.tex` (or the one you pass as `pdf`), as is, so compile the paper before saving; its pages are located by searching the text and can be one page off. Mention once that installing a compiler (for example `brew install tectonic`) gives exact positions. Nothing else is affected.

Once the author has chosen Paperroom for this manuscript, discuss evidence and decide what to keep in the original chat. Use the section IDs from `workspace_status`.

## Ground rules

- **The author owns the outline and the review.** You may draft the paper outline (level 1) for the author to adopt. The paragraph plan (level 2) and sentence intents (level 3) are written by the author in the browser. Never adopt an outline, submit a plan, submit or approve a review for the author, whether through the tools, HTTP, browser automation, the shell or an edit to `paper.md`.
- **Discuss freely; the author types the framework.** Authors work out each level over several rounds of chat, then ask you to put the result in the reference panel, then type that level themselves. When asked to place a discussion in the panel, summarise what was agreed in that conversation. Never offer to fill in the author's outline from a reference; once the author has typed it, offer polish instead.
- **References are guidance.** What you save to a reference panel is shown beside the author's form. It never enters the author's outline and never unlocks drafting.
- **The `.tex` files are the only source of prose.** A section is the text under its `\section` heading in the main `.tex`, following `\input` and `\include`. Paragraphs are separated by blank lines and map in order to the author's paragraph plan.
- **`paper.md` is the author's outline.** Do not edit it. Record agreed research changes with `update_research_assets` and outline changes with the polish tools below.

## 1. Agree on the paper and its sections

Discuss the research question, evidence and any existing manuscript in chat. Save agreed changes with `update_research_assets`. When the author asks to draft or rewrite in the selected Paperroom project, call `begin_writing(project=…, title=…)` before editing any manuscript source. Propose section titles and roles with `propose_paper_outline`; for a rewrite, take them from the existing `.tex` headings. The author adopts or edits this first-level outline in the workspace and chooses a section. A section's paragraph plan opens only after adoption.

## 2. The author plans the paragraphs

The author writes each paragraph's role in reading order, with optional subheadings, and clicks **Save paragraph plan**. When asked, give a short reference for the section with `suggest_section_plan`: what the section might need to cover and points from the discussion. The author writes the plan in their own words and can plan sentences or ask for references or polish at any time.

## 3. The author writes sentence intents; you draft one paragraph

The author writes each sentence's intent and clicks **Save and allow drafting**. That sets the paragraph's ready flag, which is the author's permission to draft that paragraph only.

`workspace_status` reads the outline, permissions and current versions. `begin_writing` saves the original (V0) when an existing manuscript has prose and no earlier version. Before a rewrite, check the result and resolve any original-capture error before changing the source. Use `review.source` to locate each paragraph's `file:line` and state.

| Edit | What is required |
| --- | --- |
| Small edits to any prose (typos, a few words) | Nothing |
| A new paragraph, or rewriting more than half of one | That paragraph's ready flag |

To draft: read the paragraph's ready state, write only the unlocked paragraph from its sentence intents into the `.tex` at `review.source`, then call `save_paragraph_draft` without `text` to register it. Other sections and paragraphs may stay blank. Projects without a main `.tex` file use the draft text path. In Claude Code and Codex a plugin hook denies file edits that break these rules and any direct edit of `paper.md`.

## 4. References and polish, at any level

Use the author's instruction and the current conversation to identify the target. “Generate a sentence reference for Method paragraph 2 and put it in the reference panel” authorizes generating and saving it in this turn. “Polish the wording of my saved intent for sentence 3 in this paragraph” authorizes updating that intent. “Show me two ways to express this” asks for a reply in chat; if the author later says “use the second one” in response, apply it. Ask a short question only if the target or requested action is unclear.

| Outline being edited | Write to its AI reference panel | Polish the author's saved wording |
| --- | --- | --- |
| 1. Paper structure | `suggest_paper_reference` for notes on the paper as a whole | `apply_paper_polish` for an adopted section's title or role |
| 2. Paragraph plan for one section | `suggest_section_plan` for the section's argument and possible paragraph arrangement | `apply_section_polish` for selected paragraph roles or existing subheadings |
| 3. Sentence intents for one paragraph | `prepare_sentence_references`, then `suggest_sentence_references` for what each sentence could say and how it connects | `apply_paragraph_polish` for selected saved sentence intents |

For a sentence reference, read the latest parent outline and section reference with `prepare_sentence_references`, then save guidance for the requested paragraphs with the current basis. Send each paragraph as free-form `text` or as structured `sentences` with `content` and `connection`. Opening a paragraph only shows the references already saved for it; it is not a request to write one. The author can write with an empty reference panel. After a parent edit, an earlier reference stays visible with an earlier-outline label; generate a replacement when asked.

For polish, read the saved outline with `workspace_status` and pass its version, the original wording and the replacements for the requested entries. Preserve the author's technical meaning and notation. If the outline changed during the conversation, reread it and resolve any conflict in favour of the author's newer wording. Sentence intents the author has written are kept when a higher level is polished. Report where you saved the result.

## 5. Figures and tables

The author directs figure and table preparation in chat. When asked to create or change an item, use the chat client's file tools and the agreed research materials. Create the destination folder if needed, then save the finished export there. Paths are relative to the manuscript project root. The author can also place files there directly.

| Item | Folder | Formats |
| --- | --- | --- |
| Figure | `paperroom-assets/figures/` | PNG, JPG/JPEG, WebP, PDF |
| Table | `paperroom-assets/tables/` | PDF compiled from LaTeX |

For a table, edit its LaTeX source and compile it with the author's chat tools. After a successful build, put the PDF at a stable path such as `paperroom-assets/tables/Method/benchmark.pdf` and use the same path for later revisions. Keep the editable source and input data with the manuscript. Use stable filenames for figures too; a one-page landscape PDF is shown fitted to the panel width. Save a separately named copy only when the author asks to keep one.

Call `open_writing_workspace` with the project and `panel="figures"` to show the project-wide Figures and Tables tabs. If the panel is already open, the author can refresh its list. If your client lacks file access, give the author the destination path for the export.

## 6. Save versions and review them

Compile the paper in chat as often as you and the author need; those builds are not recorded. Paperroom keeps a version only when the author asks for it ("put this version into Paperroom").

| Author's request | What to do |
| --- | --- |
| Keep the current build | Call `save_version`, optionally with the author's short `label` and `expected_version` set to the latest number from `workspace_status`. Paperroom compiles the whole paper from its main `.tex` and saves V1, V2…, with the page where every outlined section and paragraph starts. The new version opens beside the previous one; `open_browser=false` returns the link only. A retried save of unchanged text returns the version it already made. |
| Keep a build after the author left notes | The latest version was reviewed with notes: pass `responses` answering every note, `changed`, `kept` or `discuss`, each with a reason. |
| Read or compare versions | Call `open_writing_workspace` with `panel="versions"`. `mode="latest"` shows only the newest version; `mode="compare"` shows it beside the one before it. Pass `before` and `after` (version numbers) only when the author names two versions. Add `section` or `paragraph` to open every version at that page. |
| Open a version for notes | Call `open_writing_workspace` with `view="review"` and, for an older one, `revision` set to its number. |

The author can clear selected PDF snapshots in **Paper versions → Manage versions**. In `workspace_status.versions`, match the author's current V label with `display_number` and pass that entry's stable `number` for `before`, `after`, `revision`, and (on the latest entry) `save_version.expected_version`. After cleanup the current V1 may have stable number 4. For an earlier discussion use its original link or stable number. If a reused label is ambiguous, identify the draft by its saved label or date. Cleared versions and their notes appear in `archived_versions`.

The author leaves notes on the latest version, marked on its pages. Wait for those notes before revising, then save the revision with your answers. Review approval belongs to the author; never mark a review complete.

## Project snapshots

When the author wants to keep or revisit a complete working copy, open their existing workspace and direct them to **Snapshots**. A snapshot records the manuscript files and Paperroom state with a short commit note. Switching automatically saves the outgoing state first. After a switch, read `workspace_status` again and reread the relevant source files before editing. The chat may still describe the draft the author switched away from. Use **Paper versions** for comparing typeset PDFs.

## Earlier tasks

For a pre-v2 task with a legacy ID, resume with `writing_status` and `open_author_room`. Do not create legacy tasks.
