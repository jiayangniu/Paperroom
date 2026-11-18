from contextlib import closing
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import outline
import paperroom
import section_review as review


class SectionReviewTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = Path(folder.name)
        self.dbpath = self.project / ".paperroom/project.sqlite3"
        self.db = paperroom.connect(self.dbpath)
        self.addCleanup(self.db.close)
        outline.update_assets(self.db, self.project, 0, "Which explanation?", "Controlled experiment")
        doc = self.outline("paper", [{"title": "Introduction", "purpose": "Establish the gap"},
                                     {"title": "Results", "purpose": "Report measurements"}])
        self.section = doc["sections"][0]["id"]
        doc = self.outline("section", [{"purpose": "Prior work"}, {"purpose": "State the gap"}],
                           section=self.section)
        self.paras = [p["id"] for p in doc["sections"][0]["paragraphs"]]

    def outline(self, level, items, **kwargs):
        v = outline.state(self.db, self.project)["version"]
        return outline.submit(self.db, self.project, v, level, items, **kwargs)

    def approve(self, paragraph, intent="Describe the result in context."):
        self.outline("paragraph", [intent], section=self.section, paragraph=paragraph)

    def save(self, paragraph, text, expected=0, db=None):
        db = self.db if db is None else db
        version = outline.require_paragraph(db, self.project, self.section, paragraph)["revision"]
        return review.save_paragraph_draft(db, self.project, self.section, paragraph, version, text, expected)

    def fill(self):
        for p, text in zip(self.paras, ["Prior work examined X.", "We investigate Y."]):
            self.approve(p)
            self.save(p, text)

    def publish(self, **options):
        with patch.object(paperroom, "render_document", return_value=(b"%PDF-test", [b"rendered page"])):
            return review.publish_section(self.db, self.project, self.section, **options)

    def respond(self, notes, revision=1):
        return review.submit_review(self.db, self.project, self.section, revision, notes)

    def test_only_author_planned_paragraph_can_be_drafted(self):
        p, q = self.paras
        self.approve(p)
        self.assertEqual(review.status(None, self.project, self.section)["phase"], "outlining")
        self.assertEqual(self.save(p, "First.")["phase"], "outlining")
        with self.assertRaises(ValueError):
            review.save_paragraph_draft(self.db, self.project, self.section, q, 1, "Not unlocked.")
        with self.assertRaises(ValueError):
            self.publish()
        self.approve(q)
        self.assertEqual(self.save(q, "Second.")["phase"], "ready")
        with self.assertRaises(ValueError):
            self.save(p, "P1.\n\nP2.", expected=1)
        self.assertEqual(self.save(p, "First.")["drafts"][p]["version"], 1)
        with self.assertRaises(ValueError):
            self.save(p, "Stale client tried to overwrite first.")

    def test_revision_anchors_and_review_gate(self):
        self.fill()
        p, q = self.paras
        v1 = self.publish(minimum=2, expected_revision=0)
        self.assertEqual(v1["phase"], "review")
        self.assertEqual(review.page(self.db, self.section, 1, 1), b"rendered page")
        self.assertIsNone(review.page(self.db, self.section, 1, 0))
        with self.assertRaises(ValueError):
            self.save(q, "Premature revision.", expected=1)
        with self.assertRaises(ValueError):
            self.publish()
        note = {"kind": "keep", "paragraph": p, "quote": "examined X", "text": "Retain scope X."}
        pin = {"kind": "change", "page": 1, "pin": {"x": .2, "y": .7}, "text": "Specify what Y excludes."}
        for invalid in ([note], [note, note], [note, dict(pin, page=2)],
                        [dict(note, quote="not in this paragraph"), pin],
                        [dict(note, paragraph=self.section), pin],
                        [note, dict(pin, pin={"x": 3, "y": .8})]):
            with self.assertRaises(ValueError):
                self.respond(invalid)
        self.assertEqual(self.respond([note, pin])["phase"], "reviewed")
        self.assertEqual(self.respond([note, pin])["phase"], "reviewed")
        self.assertEqual(self.save(q, "We investigate only Y.", expected=1)["phase"], "ready")
        v2 = self.publish(minimum=1, expected_revision=1)
        self.assertEqual(v2["revisions"][1]["changed"], [q])
        self.assertEqual(v2["revisions"][0]["notes"], [note, pin])
        self.assertEqual(v2["revisions"][0]["paragraphs"][1]["text"], "We investigate Y.")
        with self.assertRaises(ValueError):
            self.respond([note, pin], revision=1)
        self.respond([note], revision=2)
        self.assertEqual(self.publish(expected_revision=2)["phase"], "reviewed")

    def test_changed_outline_cannot_bypass_review_of_its_frozen_edition(self):
        self.fill()
        self.publish(minimum=1)
        p = self.paras[1]
        self.approve(p, "Qualify before reporting.")
        current = review.status(self.db, self.project, self.section)
        self.assertEqual(current["phase"], "review")
        self.assertFalse(current["drafts"][p]["current"])
        self.assertTrue(current["drafts"][self.paras[0]]["current"])
        self.assertTrue(current["review_outline_changed"])
        self.assertEqual(current["current_revision"], 1)
        with self.assertRaisesRegex(ValueError, "等待作者"):
            self.save(p, "The support for Y is preliminary.", expected=1)
        with self.assertRaisesRegex(ValueError, "等待作者"):
            self.publish(expected_revision=1)
        note = {"kind": "change", "paragraph": p, "quote": "investigate Y", "text": "Please state the limits."}
        finished = self.respond([note])
        self.assertEqual(finished["phase"], "drafting")
        self.save(p, "The support for Y is preliminary.", expected=1)
        result = self.publish(expected_revision=1)
        self.assertEqual(result["current_revision"], 2)
        self.assertEqual(result["revisions"][0]["notes"], [note])
        self.assertEqual(result["revisions"][1]["changed"], [p])

    def test_retry_and_archived_section_can_still_be_reviewed(self):
        self.fill()
        first = self.publish(minimum=1, expected_revision=0)
        retry = self.publish(minimum=1, expected_revision=0)
        self.assertEqual(first, retry)
        self.assertEqual(len(retry["revisions"]), 1)
        state = outline.state(self.db, self.project)
        other = state["sections"][1]
        self.outline("paper", [{"id": other["id"], "title": other["title"], "purpose": other["purpose"]}])
        self.assertEqual(review.archived_sections(self.db, [other["id"]]),
                         [{"id": self.section, "title": "Introduction"}])
        self.assertEqual(review.status(self.db, self.project, self.section)["phase"], "review")
        self.assertEqual(self.respond([{"kind": "keep", "paragraph": self.paras[0], "text": "Scope is precise."}])["phase"],
                         "archived")
        self.assertTrue(review.page(self.db, self.section, 1, 1))

    def test_cjk_does_not_pass_through_latin_only_template(self):
        with patch.object(review, "_render_cjk", return_value=(b"PDF", [b"CJK rendered"])):
            source, _, pages = review._asset_preview(self.project, "引言", [{"text": "实验结果。"}], None, None, "all")
        self.assertIn(b"Songti SC", source)
        self.assertEqual(pages, [b"CJK rendered"])

    def test_publishing_race_leaves_no_partial_edition(self):
        self.fill()

        def simultaneous_edit(*args):
            with closing(paperroom.connect(self.dbpath)) as other:
                self.save(self.paras[0], "Changed during typesetting.", expected=1, db=other)
            return b"pdf", [b"outdated page"]

        with patch.object(paperroom, "render_document", side_effect=simultaneous_edit):
            with self.assertRaisesRegex(ValueError, "排版期间"):
                review.publish_section(self.db, self.project, self.section)
        self.assertEqual(review.status(self.db, self.project, self.section)["revisions"], [])
        self.assertIsNone(review.page(self.db, self.section, 1, 1))

    def test_external_source_must_contain_current_paragraphs_in_order(self):
        self.fill()
        tex = self.project / "excerpt.tex"
        for contents in ("We investigate Y.\n\nPrior work examined X.",
                         "Prior work examined X.\n% We investigate Y."):
            tex.write_text(contents)
            with self.assertRaisesRegex(ValueError, "依序"):
                self.publish(tex=tex)
        tex.write_text("Prior work\nexamined X.\n\nWe investigate Y.")
        self.assertEqual(self.publish(tex=tex)["phase"], "review")
