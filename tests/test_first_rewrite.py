"""First rewrite of a multi-file LaTeX paper through the MCP tools, with real TeX.

The .tex is the single prose source. The synthetic author's outline is written with
outline.submit, the function the browser endpoint uses; everything the AI does goes
through paperroom_mcp.invoke.
"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import outline
import paperroom
import paperroom_mcp as mcp
import versions
import workspace_server

HAS_TEX = paperroom.tex_available()
MAIN = r"""\documentclass[11pt]{article}
\begin{document}
\pagenumbering{roman}
\title{Screening}\author{A. Synthetic}\maketitle
\clearpage
\pagenumbering{arabic}
\input{sections/intro}
\include{sections/method}
\end{document}
"""
OLD = ["Each exact evaluation can dominate the cost of a search, which is why counting them matters.",
       "We compare a screening rule with an unscreened search in three paired runs."]
NEW = ["Exact evaluations dominate the cost of many searches, so a method that reaches the target "
       "with fewer of them is cheaper in practice, even when its final error is no better.",
       "We ask whether screening candidates before evaluating them reduces the number of exact "
       "evaluations needed to reach a fixed target in three paired runs."]


def intro(paragraphs):
    return "\\section{Introduction}\n" + "\n\n".join(paragraphs) + "\n"


@unittest.skipUnless(HAS_TEX and (shutil.which("pdftoppm") or sys.platform == "darwin"),
                     "Needs a TeX engine and a page renderer.")
class FirstRewriteTest(unittest.TestCase):
    def call(self, name, **args):
        with patch.object(mcp, "show_author", return_value={"room_url": "test"}):
            return json.loads(json.dumps(mcp.invoke(name, {"project": str(self.project), **args})))

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = project = Path(folder.name).resolve()
        (project / "sections").mkdir()
        (project / "main.tex").write_text(MAIN)
        (project / "sections/intro.tex").write_text(intro(OLD))
        (project / "sections/method.tex").write_text("\\section{Method}\nThree paired runs.\n")
        self.call("activate_project")
        self.call("update_research_assets", version=0, question="Q?", evidence="E.")
        with closing(paperroom.connect(workspace_server.database_path(project))) as db:
            state = outline.state(db, project)
            state = outline.submit(db, project, state["version"], "paper",
                                   [{"title": "Introduction", "purpose": "Cost"}, {"title": "Method", "purpose": "Runs"}])
            self.section = state["sections"][0]["id"]
            state = outline.submit(db, project, state["version"], "section",
                                   [{"purpose": "a"}, {"purpose": "b"}], section=self.section)
            for p in state["sections"][0]["paragraphs"]:
                state = outline.submit(db, project, state["version"], "paragraph", ["s"],
                                       section=self.section, paragraph=p["id"])
        self.paragraphs = state["sections"][0]["paragraphs"]

    def register(self, index, expected=0):
        p = self.paragraphs[index]
        return self.call("save_paragraph_draft", section=self.section, paragraph=p["id"],
                         plan_revision=p["revision"], expected_version=expected)

    def version(self, number):
        with closing(paperroom.connect(workspace_server.database_path(self.project))) as db:
            return versions.get(db, number)

    def test_original_is_frozen_once_as_v0_then_compared_with_the_rewrite(self):
        self.assertEqual(self.call("workspace_status")["versions"], [])
        began = self.call("begin_writing", title="Introduction")
        status = self.call("workspace_status", section=self.section)
        # The whole paper: roman title page, the introduction, and the \include'd method on its own page.
        self.assertEqual(began["original_saved"], {"version": 0, "pages": 3})
        self.assertNotIn("original_saved", status["review"])
        v0 = status["versions"][0]
        self.assertEqual((v0["number"], v0["kind"], v0["label"]), (0, "original", "原稿"))
        intro_place = v0["map"][self.section]
        self.assertEqual(intro_place["page"], 2)
        self.assertEqual(list(intro_place["paragraphs"]), [p["id"] for p in self.paragraphs])
        self.assertEqual([p["where"] for p in status["review"]["source"]["paragraphs"]],
                         ["sections/intro.tex:2", "sections/intro.tex:4"])
        again = self.call("workspace_status", section=self.section)
        self.assertNotIn("original_saved", again)
        self.assertEqual(len(again["versions"]), 1)
        self.assertEqual(self.version(0)["texts"][self.section], OLD)

        # Text passed alongside a different source is refused: the .tex is the source.
        with self.assertRaisesRegex(Exception, "正文以 .tex 为准"):
            self.call("save_paragraph_draft", section=self.section, paragraph=self.paragraphs[0]["id"],
                      plan_revision=1, expected_version=0, text=NEW[0])
        (self.project / "sections/intro.tex").write_text(intro(NEW))
        self.register(0)
        self.register(1)

        # A small edit after registration is in the saved version: it is the paper as it compiles.
        (self.project / "sections/intro.tex").write_text(intro([NEW[0].replace("in practice", "overall"), NEW[1]]))
        result = self.call("save_version", label="first rewrite", expected_version=0)
        self.assertEqual((result["saved_version"], result["pages"], result["label"]), (1, 3, "first rewrite"))
        self.assertEqual(result["changed"], {self.section: [0, 1]})
        texts = self.version(1)["texts"][self.section]
        self.assertIn("overall", texts[0])
        self.assertFalse(any("paperroom-" in t for t in texts))
        self.assertEqual([v["number"] for v in self.call("workspace_status")["versions"]], [0, 1])

    def test_paragraph_states_still_show_rewrites_and_extra_paragraphs(self):
        self.call("begin_writing", title="Introduction")
        (self.project / "sections/intro.tex").write_text(intro(NEW))
        self.register(0)
        self.register(1)
        rewritten = "Screening is assessed here through a separate cost model whose parameters " \
                    "come from earlier benchmarks rather than from the paired runs reported below."
        (self.project / "sections/intro.tex").write_text(intro([NEW[0], rewritten]))
        status = self.call("workspace_status", section=self.section)
        self.assertEqual([p["state"] for p in status["review"]["source"]["paragraphs"]], ["registered", "rewritten"])
        # A version is a snapshot of the build the author asked to keep; the paragraph gate is
        # enforced on edits (the hook), so save_version keeps what compiles, extra paragraph included.
        (self.project / "sections/intro.tex").write_text(intro(NEW + ["An extra paragraph."]))
        saved = self.call("save_version")
        self.assertEqual(self.version(saved["saved_version"])["texts"][self.section][2], "An extra paragraph.")
        # Only the planned paragraphs get a page in the map.
        self.assertEqual(len(saved["changed"][self.section]), 3)
        self.assertEqual(len(self.call("workspace_status")["versions"][-1]["map"][self.section]["paragraphs"]), 2)

    def test_math_refs_and_macros_compile_into_the_version(self):
        self.call("begin_writing", title="Introduction")
        rich = [NEW[0] + " The cost grows as $n^2$ when every candidate is evaluated.",
                "As Fig.~\\ref{fig:runs} shows, \\ours{} reaches the target sooner in all three paired runs."]
        main = MAIN.replace("\\begin{document}", "\\newcommand{\\ours}{ScreenRank}\n\\begin{document}")
        (self.project / "main.tex").write_text(main)
        (self.project / "sections/intro.tex").write_text(
            intro(rich) + "\n\\begin{figure}\\centering X\\caption{Runs}\\label{fig:runs}\\end{figure}\n")
        self.register(0)
        self.register(1)
        result = self.call("save_version")
        body = self.version(result["saved_version"])
        self.assertTrue(body["has_pdf"])
        self.assertIn("\\ours{}", body["texts"][self.section][1])
        self.assertEqual(set(body["map"][self.section]["paragraphs"]), {p["id"] for p in self.paragraphs})

if __name__ == "__main__":
    unittest.main()
