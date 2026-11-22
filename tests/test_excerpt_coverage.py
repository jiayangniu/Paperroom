"""A frozen review excerpt must include the text the author is asked to approve."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import outline
import paperroom
import section_review


HAS_TEX = paperroom.tex_available()
HAS_RENDERER = sys.platform == "darwin" or all(shutil.which(name) for name in
                                               ("pdftoppm", "pdfinfo", "pdfseparate", "pdfunite", "pdftotext"))


@unittest.skipUnless(HAS_TEX and HAS_RENDERER, "Needs a TeX engine and a PDF renderer.")
class ExcerptCoverageTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = Path(folder.name).resolve()
        self.db = paperroom.connect(self.project / ".paperroom/project.sqlite3")
        self.addCleanup(self.db.close)

    def prepare_drafts(self, paragraphs):
        plan = outline.update_assets(self.db, self.project, 0, "Which method saves evaluations?", "Three paired runs.")
        plan = outline.submit(self.db, self.project, plan["version"], "paper",
                              [{"title": "Introduction", "purpose": "Explain the experiment"}])
        self.section = plan["sections"][0]["id"]
        plan = outline.submit(self.db, self.project, plan["version"], "section",
                              [{"purpose": "Explain observation %d" % i} for i in range(1, len(paragraphs) + 1)],
                              section=self.section)
        for item, text in zip(plan["sections"][0]["paragraphs"], paragraphs):
            p = item["id"]
            plan = outline.submit(self.db, self.project, plan["version"], "paragraph",
                                  ["State the synthetic observation"], section=self.section, paragraph=p)
            revision = outline.require_paragraph(self.db, self.project, self.section, p)["revision"]
            section_review.save_paragraph_draft(self.db, self.project, self.section, p, revision, text)

    def write_main(self, body, preamble=""):
        (self.project / "main.tex").write_text(
            "\\documentclass[11pt]{article}\n" + preamble + "\n\\pagestyle{empty}\n\\begin{document}\n" +
            body + "\n\\end{document}\n", encoding="utf-8")

    def publish(self, pages):
        return section_review.publish_section(self.db, self.project, self.section, tex="main.tex", pages=pages,
                                              expected_revision=0)

    def assert_rejected_without_revision(self, pages):
        with self.assertRaises(ValueError):
            self.publish(pages)
        self.assertEqual(section_review.status(self.db, self.project, self.section)["revisions"], [])
        self.assertIsNone(section_review.page(self.db, self.section, 1, 1))

    def test_rejects_omitted_paragraph_then_publishes_complete_excerpt(self):
        first = "The paired runs reached the target within the original budget."
        second = "The comparison uses a common stopping rule across all trials."
        self.prepare_drafts([first, second])
        self.write_main(first + "\n\\newpage\n" + second)
        self.assert_rejected_without_revision("1")
        result = self.publish("1-2")
        self.assertEqual(result["phase"], "review")
        self.assertEqual(result["revisions"][0]["pages"], 2)

    def test_rejects_truncated_single_paragraph_even_when_its_beginning_is_visible(self):
        # The text is one ordinary paragraph. A short page forces a natural break inside it.
        paragraph = (
            "We first count every evaluation needed to reach the common target in each paired run. "
            "The initial measurements show similar values for the control and treatment groups. "
            "Next we compare the total cost accumulated by the same procedure across all samples. "
            "Under the shared stopping rule the treatment uses fewer evaluations than the control. "
            "Independent replication remains necessary before extending this observation to new data. "
            "The conclusion therefore concerns the selected runs and their stated budget alone."
        )
        self.prepare_drafts([paragraph])
        self.write_main(paragraph, r"\setlength{\textwidth}{3in}\setlength{\textheight}{62pt}")
        self.assert_rejected_without_revision("1")
        complete = self.publish("all")
        self.assertGreater(complete["revisions"][0]["pages"], 1)

    def test_rejects_source_present_but_excluded_from_compiled_paper(self):
        intro = "We summarize the independent evidence for the original research question."
        self.prepare_drafts([intro])
        (self.project / "intro.tex").write_text(intro)
        (self.project / "method.tex").write_text("Only the protocol for the method appears here.")
        self.write_main(r"\include{intro}\include{method}", r"\includeonly{method}")
        self.assert_rejected_without_revision("1")
