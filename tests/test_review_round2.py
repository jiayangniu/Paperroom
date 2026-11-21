"""Regressions for the issues found in the 0.6.1 review.

Synthetic papers in temporary folders only. PDF checks read the text of the final
PDF the author receives; the synthetic author's outline is written with
outline.submit, the function the browser endpoint uses.
"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review_fixes import HAS_TEX, Paper, fake_build, gate, seen  # noqa: E402

import assets  # noqa: E402
import latex_source as L  # noqa: E402
import paperroom  # noqa: E402

PREAMBLE = "\\documentclass{article}\n\\newif\\ifdraft\n%s\\begin{document}\n\\section{Introduction}\n"


@unittest.skipUnless(HAS_TEX, "Needs a TeX engine and a page renderer.")
class ConditionalsFollowTheTypesetText(unittest.TestCase):
    """P1. What is recorded as shown is exactly what the compile typeset."""

    def save(self, body, switch="", count=2):
        """Save the paper as a version; return it, the paragraphs it recorded and its PDF text."""
        paper = Paper(self, {"main.tex": PREAMBLE % switch + body + "\n\\end{document}\n"},
                      ["Introduction"], {"Introduction": count})
        paper.call("workspace_status")
        paper.intents("Introduction", *range(count))
        paper.register("Introduction", *range(count))
        number = paper.call("save_version")["saved_version"]
        return paper, paper.version(number)["texts"][paper.ids["Introduction"]], paper.version_text(number)

    def test_inline_iffalse(self):
        body = ("Opening words \\iffalse SECRETWORDS that never print \\fi closing words.\n\n"
                "\\iffalse A WHOLEHIDDEN paragraph on one line. \\fi\n\nVisible last.")
        paper, texts, pdf = self.save(body)
        self.assertEqual(texts, ["Opening words closing words.", "Visible last."])
        self.assertNotIn("SECRETWORDS", pdf)
        self.assertNotIn("WHOLEHIDDEN", pdf)
        self.assertIn("closing words", pdf)

    DRAFT = "\\ifdraft\nNEWBRANCH wording for the draft.\n\\else\nOLDBRANCH wording for the paper.\n\\fi\n\nSecond paragraph."
    SWITCHES = (("", "OLDBRANCH", "NEWBRANCH"), ("\\drafttrue\n", "NEWBRANCH", "OLDBRANCH"))

    def test_draft_switch_prints_only_one_branch(self):
        for switch, shown, hidden in self.SWITCHES:
            with self.subTest(draft=bool(switch)):
                _, texts, pdf = self.save(self.DRAFT, switch)
                self.assertIn(shown, texts[0])
                self.assertIn(shown, pdf)
                self.assertNotIn(hidden, pdf)

    def test_draft_switch_records_only_the_branch_that_printed(self):
        for switch, shown, hidden in self.SWITCHES:
            _, texts, _ = self.save(self.DRAFT, switch)
            self.assertNotIn(hidden, texts[0])

    def test_inline_branches_and_argument_conditionals(self):
        body = ("Shared start \\ifdraft DRAFTWORD\\else PAPERWORD\\fi{} shared end.\n\n"
                "\\ifnum1>0 NUMSHOWN\\else NUMHIDDEN\\fi{} and \\ifthenelse{1>0}{x}{y} tail.")
        paper = Paper(self, {"main.tex": PREAMBLE % "\\usepackage{ifthen}\n" + body + "\n\\end{document}\n"},
                      ["Introduction"], {"Introduction": 2})
        paper.intents("Introduction", 0, 1)
        paper.register("Introduction", 0, 1)
        number = paper.call("save_version")["saved_version"]
        pdf = paper.version_text(number)
        for shown, hidden in (("PAPERWORD", "DRAFTWORD"), ("NUMSHOWN", "NUMHIDDEN")):
            self.assertIn(shown, pdf)
            self.assertNotIn(hidden, pdf)
        self.assertIn("x tail", pdf)
        recorded = paper.version(number)["texts"][paper.ids["Introduction"]]
        self.assertEqual(len(recorded), 2)
        self.assertIn("PAPERWORD", recorded[0])
        self.assertNotIn("DRAFTWORD", recorded[0])

    def test_a_paragraph_only_in_a_switched_off_branch_is_not_recorded(self):
        body = "Visible one.\n\n\\ifdraft\nOnly in drafts.\n\\fi\n\nVisible two."
        _, texts, pdf = self.save(body, count=3)
        self.assertNotIn("Only in drafts", pdf)
        self.assertNotIn("Only in drafts.", texts)


class IncludeOnlyFromAPreambleFile(unittest.TestCase):
    """P1. \\includeonly read from a file the preamble inputs."""

    FILES = {"main.tex": "\\documentclass{article}\n\\input{settings}\n\\begin{document}\n"
                         "\\include{sections/intro}\n\\include{sections/method}\n\\end{document}\n",
             "settings.tex": "\\usepackage{amsmath}\n\\includeonly{sections/method}\n",
             "sections/intro.tex": "\\section{Introduction}\nIntro text that must not appear.\n",
             "sections/method.tex": "\\section{Method}\nMethod text that is compiled.\n"}

    def test_excluded_section_is_refused(self):
        paper = Paper(self, self.FILES, ["Introduction", "Method"], {"Introduction": 1, "Method": 1})
        status = paper.call("workspace_status", section=paper.ids["Introduction"])
        self.assertEqual(status["review"]["documents"], [])
        self.assertIn("\\includeonly", status["review"]["source"]["error"])
        paper.intents("Introduction", 0)
        with self.assertRaisesRegex(ValueError, "includeonly"):
            paper.register("Introduction", 0)
        method = L.section(paper.root, "Method")
        self.assertEqual([p["text"] for p in method.paragraphs], ["Method text that is compiled."])

    @unittest.skipUnless(HAS_TEX, "Needs a TeX engine and a page renderer.")
    def test_the_included_section_is_the_only_one_saved(self):
        paper = Paper(self, self.FILES, ["Introduction", "Method"], {"Introduction": 1, "Method": 1})
        paper.intents("Method", 0)
        paper.register("Method", 0)
        number = paper.call("save_version")["saved_version"]
        self.assertEqual(list(paper.version(number)["map"]), [paper.ids["Method"]])
        text = paper.version_text(number)
        self.assertIn("Method text that is compiled", text)
        self.assertNotIn("Intro text that must not appear", text)


FIGURE = ("\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n\\section{Results}\n"
          "\\begin{figure}\\includegraphics%s{figs/plot.png}\\caption{Plot.}\\label{fig:plot}\\end{figure}\n"
          "\\end{document}\n")


class ConfirmWhatTheAuthorSaw(unittest.TestCase):
    """P1. A confirmation is bound to the build and float the author looked at."""

    def test_blue_on_screen_red_on_disk(self):
        paper = Paper(self, {"main.tex": FIGURE % "", "figs/plot.png": b"BLUE" * 32}, ["Results"], {})
        with patch.object(paperroom, "render_marked", fake_build), paper.db() as db:
            card = seen(assets.build(db, paper.root, "ai"), "fig:plot")
            (paper.root / "figs/plot.png").write_bytes(b"REDD" * 32)
            # The author presses confirm on the blue page still on screen.
            state = assets.confirm(db, paper.root, "fig:plot", True, **card)
            self.assertTrue(state["confirmed"]["fig:plot"]["changed"])
            state = assets.build(db, paper.root, "ai")
            self.assertTrue(state["confirmed"]["fig:plot"]["changed"])
            # A card from the old build no longer matches the latest build's float.
            with self.assertRaisesRegex(ValueError, "编译版本已变化"):
                assets.confirm(db, paper.root, "fig:plot", True, build=state["build"]["build"], digest=card["digest"])
            with self.assertRaisesRegex(ValueError, "刷新"):
                assets.confirm(db, paper.root, "fig:plot", True)
            state = assets.confirm(db, paper.root, "fig:plot", True, **seen(state, "fig:plot"))
            self.assertFalse(state["confirmed"]["fig:plot"]["changed"])

    def test_same_size_same_mtime_and_starred_includegraphics(self):
        paper = Paper(self, {"main.tex": FIGURE % "*[width=2cm]", "figs/plot.png": b"BLUE" * 32}, ["Results"], {})
        figure = assets.index(paper.root)["figures"][0]
        self.assertEqual(figure["graphics"], ["figs/plot.png"])
        image = paper.root / "figs/plot.png"
        stat = image.stat()
        image.write_bytes(b"REDD" * 32)
        os.utime(image, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual((image.stat().st_size, image.stat().st_mtime_ns), (stat.st_size, stat.st_mtime_ns))
        self.assertNotEqual(assets.index(paper.root)["figures"][0]["digest"], figure["digest"])


SHARED_MAIN = "\\documentclass{%s}\n\\begin{document}\n\\input{%s}\n\\end{document}\n"
OLD_1 = "Each exact evaluation can dominate the cost of a search, which is why we count them in every run."
OLD_2 = "We compare a screening rule with an unscreened search in three paired runs on one benchmark suite."
NEW_2 = ("Screening is assessed here through a separate cost model whose parameters come from earlier "
         "benchmarks rather than from the paired runs reported in the remainder of this paper.")


class GateByBoundMainAndSharedSource(unittest.TestCase):
    """P1. Intents apply to the bound main file; a shared source is judged once."""

    def edit(self, paper, path, old, new):
        state = paper.root / ".gate"
        gate({"hook_event_name": "PostToolUse", "tool_name": "mcp__paperroom__open_writing_workspace",
              "tool_input": {"project": str(paper.root)}, "tool_response": paper.opened}, paper.root, state)
        result = gate({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                       "tool_input": {"file_path": str(paper.root / path), "old_string": old, "new_string": new}},
                      paper.root, state)
        return result and result["hookSpecificOutput"]["permissionDecisionReason"]

    def test_separate_introductions(self):
        intro = "\\section{Introduction}\n%s\n\n%s\n" % (OLD_1, OLD_2)
        files = {"conference.tex": SHARED_MAIN % ("article", "conf/intro"),
                 "journal.tex": SHARED_MAIN % ("report", "jour/intro"),
                 "conf/intro.tex": intro, "jour/intro.tex": intro}
        paper = Paper(self, files, ["Introduction"], {"Introduction": 2})
        paper.call("bind_section_source", section=paper.ids["Introduction"], tex="conference.tex")
        paper.intents("Introduction", 1)
        self.assertIsNone(self.edit(paper, "conf/intro.tex", OLD_2, NEW_2))
        reason = self.edit(paper, "jour/intro.tex", OLD_2, NEW_2)
        self.assertIn("jour/intro.tex:4", reason)
        self.assertIn("conference.tex", reason)

    def test_shared_source_bound_by_label_under_another_name(self):
        intro = "\\section{Introduction}\\label{sec:intro}\n%s\n\n%s\n" % (OLD_1, OLD_2)
        files = {"conference.tex": SHARED_MAIN % ("article", "sections/intro"),
                 "journal.tex": SHARED_MAIN % ("report", "sections/intro"), "sections/intro.tex": intro}
        paper = Paper(self, files, ["Motivation"], {"Motivation": 2})
        paper.call("bind_section_source", section=paper.ids["Motivation"], tex="conference.tex", label="sec:intro")
        reason = self.edit(paper, "sections/intro.tex", OLD_2, NEW_2)
        self.assertEqual(reason.count("sections/intro.tex:4"), 1, reason)
        self.assertIn("「Motivation」第 2 段的逐句意图", reason)
        paper.intents("Motivation", 1)
        self.assertIsNone(self.edit(paper, "sections/intro.tex", OLD_2, NEW_2))


ABSTRACT = ("\\documentclass{article}\n\\begin{document}\n\\begin{abstract} %s\\end{abstract}\n"
            "\\section{Introduction}\nIntro.\n\\end{document}\n")


class AbstractOnTheBeginLine(unittest.TestCase):
    """Abstract prose written on the \\begin{abstract} line is the abstract."""

    def test_one_line_and_two_line_abstracts(self):
        for body, text in (("Screening halves exact evaluations. ", "Screening halves exact evaluations."),
                           ("Screening halves\nexact evaluations. ", "Screening halves\nexact evaluations.")):
            with self.subTest(body=body):
                paper = Paper(self, {"main.tex": ABSTRACT % body}, ["Abstract"], {"Abstract": 1})
                found = L.section(paper.root, "Abstract").paragraphs
                self.assertEqual([p["text"] for p in found], [text])

    @unittest.skipUnless(HAS_TEX, "Needs a TeX engine and a page renderer.")
    def test_the_original_is_frozen(self):
        paper = Paper(self, {"main.tex": ABSTRACT % "Screening halves exact evaluations. "}, ["Abstract"], {"Abstract": 1})
        self.assertNotIn("original_saved", paper.call("workspace_status", section=paper.ids["Abstract"]))
        status = paper.call("begin_writing", title="Abstract")
        self.assertEqual(status["original_saved"], {"version": 0, "pages": 1})
        self.assertEqual(list(status["versions"][0]["map"]), [paper.ids["Abstract"]])
        self.assertEqual(paper.version(0)["texts"][paper.ids["Abstract"]], ["Screening halves exact evaluations."])
        self.assertIn("Screening halves exact evaluations", paper.version_text(0))


if __name__ == "__main__":
    unittest.main()
