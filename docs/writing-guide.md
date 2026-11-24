# Paperroom Writing Guide

English · [中文](writing-guide.zh-CN.md)

This guide is for authors writing papers with Paperroom. For installation, see the [README](../README.md).

## Why Paperroom works this way

Talking a paper through with AI over several rounds is a great way to sharpen your thinking: you pitch an idea, the AI pokes holes in it, and the argument gradually clicks into place. The catch is that it's easy to get lazy halfway through and say, “just write this section for me.” It feels faster in the moment, but you end up spending more time reading, checking, and rewriting—and worse, because you skipped turning the logic into your own words, the finished draft may sound smooth without actually reflecting your thinking.

Paperroom's rule is simple: **discuss freely, but type the framework yourself.**

Brainstorm in chat for as long as you like, and drop the AI's suggestions into the reference panel whenever you want. But every layer of the structure—how a section is split into paragraphs, what each paragraph should make the reader understand, and how each sentence follows the one before—is written by you in the workspace. It doesn't need to be elegant; it just needs to come from your own head. Once the structure is yours, let the AI handle the polishing, LaTeX drafting, and compilation.

## Three levels, one rhythm

Every level follows the same loop:

```text
Discuss in chat → put conclusions in the reference panel → write out your own ideas again alongside the AI reference → save → ask AI to polish if needed
```

The framework goes from coarse to fine in three levels:

| Level | What it captures | Who writes it |
| --- | --- | --- |
| Paper outline | The sections of the paper and what each contributes to the argument | AI drafts from your discussion; you edit and confirm |
| Paragraph plan | Subsections, paragraphs, and what each paragraph should make the reader understand | You, by hand |
| Sentence intents | What each sentence in a paragraph says and how it connects to the previous one | You, by hand |

Settling one level unlocks the next. If working on a lower level reveals a flaw higher up, you can go back and revise it anytime without losing what you've already written below.

---

## Step 1: Start a project with what you have

In a chat inside your paper's folder, say **“Use Paperroom to write this paper”** and click the local workspace link. In later chats, say **“Open this paper's Paperroom”** (add the folder path if several papers share a name). You can keep multiple papers open under their own links at the same time.

Before outlining, tell the AI what you're starting with—data, main claim, notes, or an earlier draft:

> Use Paperroom to start a paper in `~/papers/my-paper`. The data is in `results/`: paired runs on three molecules at five noise levels. Roughly, I want to show that a cheap noiseless ranking can screen candidates first, cutting most noisy evaluations with almost no loss in accuracy. There's an earlier draft in `main.tex` you can look at.

The AI reads your materials, works out the **research question** and **existing evidence** with you, and saves them. You can view or edit both anytime under **Research question & materials**.

## Step 2: Settle the paper outline

Keep discussing which sections you need and what each one does. When the structure feels solid, ask the AI to draft it:

> Draft the paper outline from what we've discussed, then open the workspace.

Review it under **Paper outline** in the browser. Go back to chat if anything feels off, or edit directly on the page. When you're happy with it, click **Adopt these sections** (editing and saving counts as adopting too).

This is the only level the AI drafts directly, since section boundaries are usually obvious from discussion. Everything below this level is typed by you.

## Step 3: Talk through one section (and its figures & tables)

Pick a section to start with (say, Method) and work out its logic in chat until you can explain its parts clearly yourself—including **which figures and tables belong in this section**. It works best to settle and polish a section's figures and tables with the AI at this stage and drop them into Paperroom so you can view them while writing the paragraph plan and sentence intents (see [Preparing and viewing figures and tables](#preparing-and-viewing-figures-and-tables) below):

> Let's work on Method. What role should it play in the overall argument, and what should a reader be convinced of by the end?

> I want to explain one noiseless step first, then the cost noise introduces, then our method. Does splitting into three subsections make sense?

> For the second subsection, I'm thinking two paragraphs: where the gap between gain and cost comes from, and what information each decision needs. Is that too fast?

## Step 4: Put the discussion in the reference panel

Once the structure is clear, ask the AI to organize it into the reference panel:

> Summarize the Method paragraph plan we just discussed and put it in the reference panel.

Open Method in the workspace and **The AI's reference** will appear on the right. It's strictly for reference—it never enters your outline and never unlocks drafting.

## Step 5: Type the paragraph plan yourself

With the reference on the right, write the subheadings and each paragraph's role on the left in your own words.

- **Copy-paste is disabled on purpose.** Paste, drag-and-drop, and copy are turned off in these fields. The point isn't to transcribe the reference—it's to use the AI reference as a prompt to write out your own ideas again in your own words. Wherever typing feels awkward is usually where the logic still needs work.
- **Read straight through.** Paragraph numbers sit in the left margin so you can read an entire subsection continuously and check the flow.
- **Edit and reorder easily.** Click any paragraph to open its toolbar: **Insert before** (a paragraph or subheading), move up or down, or **Delete paragraph** (**Undo last deletion** brings it back if needed).
- **Groupings and math.** Use **Add subheading** to organize subsections (they also show up in the left navigation). You can write LaTeX math directly, such as `$\Delta = r - p$`.
- **Stay aligned with long references.** Click **Find in reference** to jump to the matching spot on the right.

Click **Save paragraph plan** when finished.

## Step 6: Ask the AI to polish what you wrote

Hand-typed outlines can be wordy or rough. Once saved, ask the AI to tighten them up:

> Polish the roles of Method paragraphs 2 and 3 without changing their meaning.

The AI updates those entries directly while preserving your technical meaning and notation. If you'd rather compare options first, ask:

> Show me two ways to phrase the role of paragraph 4.

The options stay in chat and are only written back when you say “use the second one.”

## Step 7: Write sentence intents to unlock drafting

Work one paragraph at a time. Discuss how the paragraph should unfold:

> In Method paragraph 2, I want to show the 1D curve first, then explain the difference between a gradient and an exact evaluation. Should I mention that earlier angles stay fixed first?

Then ask for a sentence-level reference:

> Generate a sentence reference for Method paragraph 2 and put it in the reference panel.

Open the paragraph in the workspace. Your paragraph role sits at the top left, and the **AI sentence reference** scrolls independently on the right. **One level up** (the section outline) and the research question/materials stay folded at the bottom; opening the section outline jumps straight to your current paragraph without touching what you've typed on the left.

Write each sentence's intent—what it says and how it follows the sentence before—then click **Save and allow drafting**. That click is your explicit permission for the AI to draft this paragraph. You can ask for polish here too:

> Polish my intent for sentence 3 of paragraph 2.

## Step 8: Have the AI draft

Once unlocked, tell the AI to write it:

> Draft Method paragraph 2 from my saved intents.

The AI writes the paragraph into its matching spot in your `.tex` file. Other paragraphs can stay blank while you go one by one.

- **Automatic original backup (V0):** When rewriting an existing paper, Paperroom saves the original manuscript as **V0** before the AI's first edit so you can always compare against it.
- **What needs permission:** Small tweaks (typos, a few words) need no unlock. Writing a new paragraph or rewriting more than half of one requires **Save and allow drafting**. In Claude Code and Codex, the plugin enforces this automatically.

## Step 9: Save versions and review them

Compile and tweak in chat as often as you like—Paperroom doesn't log intermediate builds. When a draft is worth keeping, say:

> Put this version into Paperroom, labelled “Method revised”.

The AI compiles the full paper and saves it as the next version (V1, V2, …; the label is optional). The workspace automatically tracks which sections and paragraphs changed since the previous version.

Click **Versions & review** on the left to inspect the latest build:

1. Read through the typeset pages. Click anywhere on a page to pin a note, or pick a paragraph from the side panel.
2. Mark each note as **Change** or **Keep**, explain why, and click **Save observation**.
3. When you've finished reading, click **Submit review**.

On the next saved version, the AI answers every note as **Revised**, **Kept as is**, or **Disagrees**, with a reason. When you're satisfied with a version, click **Approve, no new notes**. Only you can approve a review.

---

## Reading, comparing, and cleaning up versions

Click **Paper versions** at the top right of any outline page:

- **One version:** Opens the latest version by default. Click the version name at the top to switch, or use `←` / `→` to step through versions at the same spot.
- **Compare two:** Shows the latest version beside the previous one. Both headers are pickers so you can compare any two (e.g., V0 vs. V3); choosing the version already open on the other side swaps them. Turn on **Sync scrolling** to align both sides by section and paragraph pages—even if the new draft runs half a page longer.
- **Opens where you are:** Opening from Method's paragraph plan lands on Method's page; opening from a specific paragraph lands on that paragraph. **Versions & review** behaves the same way.
- **Visual cues and zoom:** Older versions are marked amber, newer ones green, and the newest carries a **Latest** badge. Zoom with `− percentage +`, `⌘`-scroll, or trackpad pinch; click the percentage to fit width.
- **Cleaning up intermediate drafts:** Click **Manage versions**, select drafts you don't need anymore, click **Preview cleanup**, check the note counts and updated numbering, then click **Confirm cleanup**. Remaining drafts renumber cleanly (e.g., clearing V1–V3 makes the old V4 show as V1; the original always stays V0). Your `.tex` files are untouched, notes on cleared drafts stay readable, and old links still point to the exact draft they were created for.

## Snapshots, switching clients, and coauthors

### Saving and switching snapshots

Before trying a risky rewrite, click **Snapshots**, add an optional note (e.g., “Method before rewrite”), and click **Save snapshot**. Each snapshot is a full working copy—manuscript, assets, and Paperroom data—stored alongside your project in `<paper-folder>.paperroom-archives`.

To roll back, save any edits in external editors and wait for running builds to finish. Click **Switch** next to a snapshot, optionally note what you're leaving behind, and click **Save current version and switch**. Paperroom saves your current state first so you can always switch forward again. *(Git metadata stays in your working folder; symbolic links are saved as links, so external targets are managed separately.)*

### Switching clients on the same computer

When moving between Claude, Codex, and Antigravity, open the same manuscript folder and ask: “Open this paper's Paperroom and reread the current status and source.” Multiple clients can read at the same time, but **only let one client edit a given `.tex` file at once**, and finish active edits before switching snapshots.

### Handing off to a coauthor

Click **Snapshots → Export for coauthor** to download a ZIP containing the manuscript, assets, saved PDFs, and synced drafts (save changes in external editors first). Check **Include snapshot history** if they need earlier snapshots too. Your coauthor just extracts the ZIP and opens the folder in Paperroom on their machine.

## Preparing and viewing figures and tables

It's best to decide which figures and tables a section needs while working on its **paragraph plan (level 2)**. First, iterate with the AI in chat on what each figure should show or how each table should be structured; once they look right, have the AI export them into fixed folders in your project so you can reference them directly in the workspace while outlining and drafting.

| Item | Folder | Formats |
| --- | --- | --- |
| Figure | `paperroom-assets/figures/` | PNG, JPEG, WebP, PDF |
| Table | `paperroom-assets/tables/` | PDF compiled from LaTeX |

Organizing by section subfolders (such as `Method/` or `Results/`) keeps things tidy. Just ask the AI in chat to build and save them:

> Draw the method pipeline as a one-page landscape PDF and save it to `paperroom-assets/figures/Method/fig1.pdf`.

> Turn the Related work comparison table we just finalized into LaTeX, compile it to PDF, and save it to `paperroom-assets/tables/Related work/table1.pdf`.

**How to use them in the workspace:**
1. Click **Figures & tables** at the top right or on a section page to preview them directly—single-page landscape figures fit to width, and multi-page tables support paging and zoom.
2. Keep the finished figures and tables open as you write that section's paragraph plan and sentence intents so your prose stays aligned with them.
3. To revise one, ask the AI to update the source and overwrite the same file, then click **Refresh figures and tables** to see the new version. If you want to keep an older version, explicitly ask the AI to save under a new name.

## Useful chat prompts for references and polish

| Goal | What to say in chat | Where it goes |
| --- | --- | --- |
| Feedback on paper structure | “Write a reference for the paper outline and put it in the reference panel.” | Beside the paper outline |
| Paragraph breakdown for a section | “Put the Method paragraph plan we discussed in the reference panel.” | Beside that section's paragraph plan |
| Sentence-by-sentence plan | “Generate a sentence reference for Method paragraph 2 and put it in the reference panel.” | Beside that paragraph's sentence intents |
| Tighten saved outline wording | “Polish my intent for sentence 3.” / “Polish the role of Introduction paragraph 2.” | Written directly into your outline |
| Compare phrasings first | “Show me two ways to phrase this intent.” | Stays in chat until you say “use the second one” |

References are only generated when you ask, and you can write with an empty reference panel. Editing an upper level never overwrites sentence intents you've already written; older references simply get flagged as based on an earlier outline so you can refresh them if needed.

## Where your files live

Everything related to your paper stays in its project folder:

| Path | Contents |
| --- | --- |
| `paper.md` | Your three-level outline in plain text. You can edit sentence intents after their numbers, but leave headings, numbers, and `paperroom` comments intact. The AI never edits this file directly. |
| `.paperroom/` | Workspace data: registered drafts, AI references, saved PDF versions and page images, review notes, and the writing log. |
| Your `.tex` files | The single source of truth for prose. AI-drafted paragraphs go here; Paperroom maps sections by `\section` headings. |
| `paperroom-assets/` | Figures and tables shown in the workspace. |

Only one small config lives outside the project folder: `~/.local/share/paperroom/rooms/` stores each paper's local workspace URL and access token (readable only by your user account), keeping your workspace URL stable across closed tabs, new chats, restarts, and updates.

## Handy extras

- **Writing log:** Click **Writing log** (top right) for a local-time history of outline submissions, saved versions, and reviews. Exportable, with optional third-party timestamp receipts.
- **English / Chinese UI:** Switch anytime in the top-right corner; only interface labels change, never your text.
- **Persistent workspace & auto-reconnect:** Closing chat windows or restarting your client won't break an open workspace tab. After a long idle period the server stops on its own; if the page shows **Offline for now**, ask the AI in any chat to open the workspace and the tab will reconnect within seconds. Plugin updates auto-refresh the page (waiting if you're mid-typing).
- **Open without AI:** Whenever you open or activate a paper from chat, Paperroom keeps `~/.local/share/paperroom/Open-Paperroom.command` up to date. Double-click it to pick a paper and open the workspace directly.
- **Safe concurrent sync:** The workspace syncs every few seconds. If the AI updates something while you're typing, your unsubmitted text is preserved so you can compare before saving.

## FAQ

**The AI says a paragraph can't be drafted yet.**  
Open that paragraph, make sure its sentence intents are filled in, and click **Save and allow drafting**. If you edited the section's paragraph plan afterward, save the paragraph plan again first.

**Can the AI just fill my outline in from the reference panel?**  
No—that's the core constraint. Ask for as many references as you want, but every outline entry has to be typed by you. Once it's saved, the AI can help polish it.

**What if I don't have a LaTeX compiler installed locally?**  
You can still use Paperroom. Ask the AI to compile the PDF (named after your main `.tex`) before saving a version; Paperroom will keep that PDF and locate sections/paragraphs by text search (occasionally off by a page). Installing a local compiler (such as `brew install tectonic`) lets Paperroom compile with exact page markers without touching your project's PDF.

**Review pages don't render images.**  
macOS uses built-in PDFKit. On Linux or Windows, install Poppler (`pdftoppm` and `pdftotext`).
