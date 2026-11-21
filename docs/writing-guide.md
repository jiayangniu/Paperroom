# Paperroom writing guide

English · [中文](writing-guide.zh-CN.md)

This guide is for authors who write with Paperroom. For installation, see the [README](../README.md).

## What Paperroom is for

Talking a paper through with an AI over many rounds is often how the thinking gets clear: you put forward an idea, the AI offers suggestions and counterexamples, and after a few rounds the structure and argument take shape. The trouble is that people get lazy. Halfway through a discussion it is tempting to have the AI generate a long passage. It looks like a shortcut, but you then spend longer reading, checking and reworking it, and the thinking in it may not be yours.

Paperroom's answer is simple: **discuss freely, but type the framework yourself.** Talk with the AI for as many rounds as you like, and ask it to put its suggestions in the reference panel whenever you want. But every level of the paper's framework (how many paragraphs a section has, what each should make the reader understand, what each sentence says) is written by you in the workspace. It doesn't have to be precise, but it has to be your own output. Once it is written, the AI can polish the wording and then draft the prose from your intents.

## Every level follows the same rhythm

```
Discuss in chat → ask the AI to put the conclusions in the reference panel → type this level yourself beside it → save → ask the AI to polish
```

The framework has three levels, written from coarse to fine:

| Level | What it says | Who writes it |
| --- | --- | --- |
| Paper outline | The sections of the paper and the role each plays in the argument | The AI drafts it from your discussion; you edit and confirm |
| Paragraph plan | The subsections and paragraphs of one section, and what readers should understand after each paragraph | You, by hand |
| Sentence intents | What each sentence of one paragraph says, and how it follows from the previous one | You, by hand |

Each level opens once the one above it is settled. If writing a lower level shows that a higher one is wrong, go back and change it at any time.

## Step 1: Start the project with what you already have

Before writing, tell the AI what you have: your experimental data and results, roughly what the paper should show, and any existing draft or notes.

> Use Paperroom to start a paper in `~/papers/my-paper`. The data is in `results/`: paired runs on three molecules at five noise levels. Roughly, I want to show that a cheap noiseless ranking can screen candidates first, removing most noisy evaluations with almost no loss in accuracy. There's an earlier draft in `main.tex` you can use.

The AI reads these materials, works out the **research question** and **existing evidence** with you, and records them. You can view and edit them later under **Research question & materials** in the workspace.

## Step 2: Discuss and settle the paper outline

Keep discussing in chat which sections the paper needs and what each one does. When it feels about right, ask the AI to draft it:

> Draft the paper outline from what we've discussed, then open the workspace.

Read it under **Paper outline** in the browser. If you're not happy, go back to chat, or edit it on the page. When it's settled, click **Adopt these sections**. Editing and saving counts as adopting too.

The paper outline is the only level the AI drafts directly, because the sections are usually clear from the discussion. From the next level on, you write by hand.

## Step 3: Pick a section and discuss its structure over several rounds

Pick a section to start with, say Method, and talk it through in chat:

> Let's write Method. What role should it play in the paper's argument? What should readers believe after reading it?

> I'd like to explain one append without noise first, then the cost noise adds, then introduce the method. Do three subsections make sense?

> For the second subsection I'm thinking two paragraphs: where the difference between r and p comes from, and what information each decision needs. Is that enough, or does it jump too fast?

Keep going until you can say for yourself how many subsections the section has and what each paragraph should say.

## Step 4: Ask the AI to put the result in the reference panel

> Summarise the Method paragraph plan we just discussed and put it in the reference panel.

Open Method in the workspace. **The AI's reference** appears on the right, listing each paragraph's role by subsection. The reference is for comparison only. It never enters your outline and never gives the AI permission to draft.

## Step 5: Write the paragraph plan by hand

With the reference on the right, write the subheadings and each paragraph's role on the left, in your own words.

- **It doesn't have to be precise, but it has to be yours.** Paste, drag-and-drop and copy are turned off in these fields, so you can't carry text over from the reference. Typing it is how you check that you really understand the section's structure.
- **Read straight through.** Paragraph numbers sit in the left margin, so you can read all the paragraphs under one subheading in a row and check the logic between them.
- **Click a paragraph to edit it.** That paragraph shows its frame and a small toolbar: **Insert before** (a paragraph or subheading), move up or down, and **Delete paragraph**. **Undo last deletion** restores one removed by mistake.
- **Group paragraphs.** **Add subheading** splits the section into subsections. Subheadings also appear in the contents on the left.
- **Type formulas directly**, for example `$\Delta = r - p$`.
- When the reference is long, **Find in reference** jumps to the part that matches the paragraph you're on.

Click **Save paragraph plan** when you're done.

## Step 6: Ask the AI to polish what you wrote

Your hand-typed version may be wordy or imprecise. That's where the AI helps:

> Polish the roles of Method paragraphs 2 and 3 without changing their meaning.

The AI rewrites those saved entries directly and keeps your technical meaning and notation. To see a few wordings first, ask:

> Show me two ways to phrase the role of paragraph 4.

The result stays in chat and is written back only after you say "use the second one".

## Step 7: Sentence intents follow the same rhythm

Go one paragraph at a time. First discuss in chat how it should unfold:

> In Method paragraph 2 I want to give the one-dimensional curve first, then the difference between a gradient and an exact evaluation. Should I first say that the earlier angles are fixed?

Then ask for a sentence reference:

> Generate a sentence reference for Method paragraph 2 and put it in the reference panel.

Open the paragraph in the workspace. The role you wrote is at the top on the left. The full **AI sentence reference** is on the right and scrolls on its own. The section outline (**One level up**) and the research question and materials are folded at the foot of the column; opening the section outline takes you straight to the paragraph you're writing. Opening or closing them leaves your typed text on the left untouched.

With the reference beside you, type each sentence's intent: what it says and how it follows from the one before. Then click **Save and allow drafting**. That is your permission: the AI drafts only paragraphs you have allowed. Polish works here too:

> Polish my intent for sentence 3 of paragraph 2.

## Step 8: Have the AI draft

> Draft Method paragraph 2 from my saved intents.

The AI writes the paragraph at its place in your `.tex` file. Other paragraphs can stay empty; go one at a time.

- When you rewrite an existing section, Paperroom saves the original typeset pages before the AI's first edit, so you can compare them later.
- Small edits, such as fixing a typo or changing a few words, need no permission. Writing a new paragraph, or rewriting more than half of one, needs that paragraph to have been saved with **Save and allow drafting**. In Claude Code and Codex, the plugin blocks edits that don't meet this rule.

## Step 9: Review the typeset section

When the whole section is drafted:

> Publish Method for my review.

The workspace opens **Section review** with pages typeset in your paper's template.

1. Read the version through. Click a page to place a mark there, or pick a paragraph directly.
2. For each observation choose **Change** or **Keep**, give your reason, and click **Save observation**.
3. Once you have the required number of notes, click **Submit review**.

The AI revises, publishes a new version and answers each note from the previous one: **Revised**, **Kept as is** or **Disagrees**, with a reason. You review the new version in turn. When a version is good enough, click **Approve, no new notes**; you don't need a minimum number of notes. Only you decide when the review is complete.

## Comparing the old and new versions

On a section or review page, click **Compare section versions**. It opens the two most recently published versions; for the first rewrite, it compares against the saved original.

- **Compare** shows Before and After side by side. With **Sync scrolling** on, both sides move together.
- **Single** shows one version at a time. Switch with the Before / After buttons at the top or the ← / → keys; you stay at the same spot.
- Before is amber and After is green throughout: page edges, labels and page counters. The newest version also carries a **Latest** badge, so you can tell at a glance which one you're reading.
- **Full page**, **Text width** and **2×** change the page size.

Earlier review links and notes always point to the version published at the time.

## Viewing figures and tables

Ask the AI in chat to create or change figures and tables as well. Finished files go into fixed folders in your project:

| Item | Folder | Formats |
| --- | --- | --- |
| Figure | `paperroom-assets/figures/` | PNG, JPEG, WebP, PDF |
| Table | `paperroom-assets/tables/` | PDF compiled from LaTeX |

> Draw the SG-ADAPT pipeline as a one-page landscape PDF and save it as `paperroom-assets/figures/Method/fig1.pdf`.

Subfolders per section are fine. Click **Figures & tables** at the top right or on a section page. A one-page landscape figure fills the width and the preview fits the figure's height; multi-page tables can be paged and zoomed. After the AI updates the same file, click **Refresh figures and tables** to see the new version. To keep an extra copy, ask the AI explicitly to save one under another name.

## References and polish at a glance

| You want | Say in chat | Result appears |
| --- | --- | --- |
| Advice on the paper's structure | "Write a reference for the paper outline and put it in the reference panel." | Beside the paper outline |
| How a section might be split into paragraphs | "Put the Method paragraph plan we discussed in the reference panel." | Beside that section's paragraph plan |
| How each sentence of a paragraph might go | "Generate a sentence reference for Method paragraph 2 and put it in the reference panel." | Beside that paragraph's sentence intents |
| Better wording for something you saved | "Polish my intent for sentence 3." "Polish the role of Introduction paragraph 2." | Written back into your outline |
| A few wordings to compare first | "Show me two ways to phrase this intent." | In chat; written back only after you say "use the second one" |

References are generated only when you ask, and you can write with an empty reference panel. Editing a higher level never overwrites sentence intents you have already written. An older reference is labelled as based on an earlier outline; ask the AI for a new one when you need it.

## Where your files are

Everything stays in your paper's project folder.

| Location | Contents |
| --- | --- |
| `paper.md` | Your three-level outline, readable as plain text. You may edit the sentence intents after their numbers; keep the headings, numbers and paperroom comments as they are. The AI does not edit this file directly. |
| `.paperroom/` | Workspace data: registered drafts, AI references, review notes, typeset versions and the writing log. |
| Your paper's `.tex` files | The only source of the prose. The AI writes drafted paragraphs here, and Paperroom finds each section by its `\section` heading. |
| `paperroom-assets/` | Figures and tables shown in the workspace. |

One thing lives outside the paper's folder: `~/.local/share/paperroom/rooms/` records each paper's local workspace address and access token, readable only by your account. It keeps the page address the same across closed windows, new chats, client restarts and plugin updates.

## Other features

- **Writing log**: **Writing log** at the top right lists, in local time, when you submitted outlines, when sections were published and when reviews were submitted. You can export it. With a third-party timestamp service configured, you can also request a receipt for an entry.
- **English and Chinese interface**: switch at the top right. Interface text changes; what you and the AI wrote stays as written.
- **Switching windows, restarts and updates**: the workspace runs in the background at a fixed address. Closing the chat window, starting a new chat or restarting your client leaves an open page working. If the page shows **Offline for now**, ask the AI in any chat to open the workspace and the page reconnects within seconds; there's no need to close it. After a plugin update the page refreshes itself to the new version, or, if you're typing, asks you to refresh once you've saved. After a long idle period the workspace stops on its own; ask the AI to open it again.
- **Changes from both sides at once**: the workspace syncs every few seconds. If the AI updates something while you're typing, your unsubmitted text is kept so you can compare and rewrite what still applies.

## Common questions

**The AI says a paragraph can't be drafted yet.**
Open the paragraph, check that its sentence intents are written, and click **Save and allow drafting**. If you changed the section's paragraph plan afterwards, save the paragraph plan again.

**Can the AI just fill my outline in from the reference?**
No, and that's deliberate. You can ask for as many references as you like, but every entry in your outline has to be typed by you. Once it is, the AI can polish it.

**Publishing says LaTeX was not found.**
Typesetting a review needs pdfLaTeX or Tectonic. If the ChatGPT desktop app is installed, Paperroom uses its bundled Tectonic. You can also ask the AI to publish a PDF you compiled yourself.

**Review pages don't show page images.**
macOS uses its built-in PDFKit. Other systems need Poppler (`pdftoppm`, `pdftotext`).
