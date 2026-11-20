# Paperroom writing workflow for AI assistants

Call `get_usage()` from Claude Chat, Claude Code or Codex to read this guide for the installed plugin. It takes no arguments and works before selecting a manuscript. Discuss evidence, compare suggestions and decide what to keep in the author's chat. The workspace holds the author's outline, AI references, drafts and review history. When working on a manuscript, use the author's project folder and section IDs from `workspace_status`.

## Outline references and polish in chat

Use the author's instruction and the current conversation to identify the target. “Generate a sentence reference for Method paragraph 2 and put it in the reference panel” authorizes generating and saving it in this turn. “Polish the wording of my saved intent for sentence 3 in this paragraph” authorizes updating that intent. “Show me two ways to express this” asks for a reply in chat. If the author later says “use the second one” in response to a choice about that intent, apply it. Ask a short question only if the target or requested action is unclear.

| Outline being edited | Write to its AI reference panel | Polish the author's saved wording |
| --- | --- | --- |
| 1. Paper structure | `suggest_paper_reference` for notes on the paper as a whole | `apply_paper_polish` for an adopted section's title or role |
| 2. Paragraph plan for one section | `suggest_section_plan` for the section's argument and possible paragraph arrangement | `apply_section_polish` for selected paragraph roles or existing subheadings |
| 3. Sentence intents for one paragraph | `prepare_sentence_references`, then `suggest_sentence_references` for what each sentence could say and how it connects | `apply_paragraph_polish` for selected saved sentence intents |

Read the saved outline with `workspace_status`. For polish, use its version, the original wording and the replacements for the requested entries. Preserve the author's technical meaning and notation. If the outline changed during the conversation, reread it and resolve any conflict with the author's newer wording. Report where you saved the result. A changed paragraph role is available as context in the sentence workspace. Write a separate sentence reference only when the author asks for it.

## 1. Agree on the paper and its sections

Discuss the research question, evidence and any existing manuscript in chat. Save agreed changes with `update_research_assets`. When the author asks to draft or rewrite, use `begin_writing` or `open_writing_workspace`. Propose section titles and roles with `propose_paper_outline`, using the existing headings for a rewrite. The author adopts or edits this first-level outline in the workspace and chooses a section.

## 2. Plan the paragraphs

The author writes each paragraph's role in reading order, with optional subheadings. **Save paragraph plan** records this wording. The author can start planning sentences or ask for references or polish in chat at any time.

## 3. Plan the sentences and draft one paragraph

For a sentence reference, read the latest parent outline and section reference with `prepare_sentence_references`. Use the current basis to save guidance for the requested paragraphs. Send each paragraph as free-form `text` or as structured `sentences` with `content` and `connection`. Opening a paragraph simply shows the references available for it. The author can write with an empty reference panel. An earlier saved reference can remain visible with an earlier-outline label after a parent edit. Generate a replacement when requested.

The author writes the third-level sentence intents. Read the paragraph's ready state before drafting. Generate manuscript prose only for a paragraph whose intents authorize drafting. For an existing section, check that its original layout is saved before editing. Follow the source location in `review.source` and register the paragraph with `save_paragraph_draft`. Projects without a main TeX file use the draft text path. Use the plugin tools to save author-directed outline changes.

## View figures and tables

The author directs figure and table preparation in chat. When asked to generate or change an item, use the chat client's file tools and the agreed research materials. Create the destination folder if needed, then save the finished export there. Paths are relative to the manuscript project root. An author can also place files there directly.

| Item | Folder | Formats |
| --- | --- | --- |
| Figure | `paperroom-assets/figures/` | PNG, JPG/JPEG, WebP, PDF |
| Table | `paperroom-assets/tables/` | PDF compiled from LaTeX |

For a table, edit its LaTeX source and compile it with the author’s chat tools. After a successful build, put the resulting PDF at a stable path such as `paperroom-assets/tables/Method/benchmark.pdf`. Use the same path on the next successful revision. Keep the editable source and input data with the manuscript. Use a stable filename for figures as well. Call `open_writing_workspace` with the project and `panel="figures"` to show the project-wide Figures and Tables tabs. If the panel is already open, the author can refresh its list. Save a separately named copy only when the author asks to keep one. If your client lacks file access, give the author the destination path for the export.

## 4. Review the typeset section

| Author's request | Tool and version selection |
| --- | --- |
| Compare a section’s latest edits | Call `open_writing_workspace` with the project, section ID and `panel="comparison"`. Omit `before` and `after` for ordinary review. Paperroom opens the latest published edition alongside its predecessor. For the first edition it uses the original saved before publication, when available. A single available layout opens on its own. |
| Publish a revised section | Call `publish_section`, answering each observation on the prior reviewed edition. The returned review link opens the edition just published. The default opens it for the author. Use `open_browser=false` for link-only delivery. |

An existing review link stays attached to its published edition and observations. If the author specifically asks about a historical edition, use that saved link or read its ID from `workspace_status` and pass the requested `revision`. The author can inspect the typeset pages, compare versions and submit observations in the workspace. Review approval belongs to the author. For a resumed pre-v2 task, use `writing_status` and `open_author_room`.
