from contextlib import closing
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import outline
import paperroom
import section_review as review
import versions


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
        with patch.object(paperroom, "render_document", return_value=(b"%PDF-test", [b"rendered page"])), \
                patch.object(review.excerpt.pdf_text, "read_pages", return_value=["Prior work examined X. We investigate Y."]):
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
        answers = [{"note": 1, "status": "kept", "text": "Scope X stays."},
                   {"note": 2, "status": "changed", "text": "Now says only Y."}]
        v2 = self.publish(minimum=1, expected_revision=1, responses=answers)
        self.assertEqual(v2["revisions"][1]["responses"], answers)
        self.assertEqual(v2["revisions"][1]["changed"], [q])
        self.assertEqual(v2["revisions"][0]["notes"], [note, pin])
        self.assertEqual(v2["revisions"][0]["paragraphs"][1]["text"], "We investigate Y.")
        with self.assertRaises(ValueError):
            self.respond([note, pin], revision=1)
        self.respond([note], revision=2)
        # Answering without changing the text still gives the author a version to read.
        again = [{"note": 1, "status": "kept", "text": "Unchanged."}]
        answered = self.publish(expected_revision=2, responses=again)
        self.assertEqual((answered["phase"], answered["current_revision"]), ("review", 3))
        self.assertEqual(answered["revisions"][2]["responses"], again)
        self.assertEqual(answered["revisions"][2]["changed"], [])

    def test_each_note_is_answered_and_later_versions_can_pass(self):
        self.fill()
        self.assertEqual(self.publish()["revisions"][0]["minimum"], 3)
        p, q = self.paras
        notes = [{"kind": "change", "paragraph": q, "text": "Narrow the claim."},
                 {"kind": "keep", "paragraph": p, "text": "Good framing."},
                 {"kind": "change", "paragraph": p, "text": "Cite the survey."}]
        with self.assertRaisesRegex(ValueError, "逐条写下"):
            review.submit_review(self.db, self.project, self.section, 1, [], approve=True)
        self.respond(notes)
        self.save(q, "We investigate only Y.", expected=1)
        with self.assertRaisesRegex(ValueError, "逐条回应"):
            self.publish(expected_revision=1)
        partial = [{"note": 1, "status": "changed", "text": "Narrowed."}, {"note": 3, "status": "discuss", "text": "No survey exists."}]
        with self.assertRaisesRegex(ValueError, "第 2 条"):
            self.publish(expected_revision=1, responses=partial)
        with self.assertRaisesRegex(ValueError, "不止一次"):
            self.publish(expected_revision=1, responses=partial + [partial[0]])
        answers = partial + [{"note": 2, "status": "kept", "text": "Kept."}]
        v2 = self.publish(expected_revision=1, responses=answers)
        self.assertEqual([a["note"] for a in v2["revisions"][1]["responses"]], [1, 2, 3])
        self.assertEqual(v2["revisions"][1]["minimum"], 1)
        # A retry while version 2 awaits review is recognized, not rejected.
        self.assertEqual(self.publish(expected_revision=1, responses=answers)["current_revision"], 2)
        passed = review.submit_review(self.db, self.project, self.section, 2, [], approve=True)
        self.assertTrue(passed["revisions"][1]["approved"])
        self.assertEqual(passed["phase"], "reviewed")
        # Nothing to answer after an approval without notes.
        with self.assertRaisesRegex(ValueError, "无需逐条回应"):
            self.publish(expected_revision=2, responses=answers)

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
        result = self.publish(expected_revision=1, responses=[{"note": 1, "status": "changed", "text": "Limits stated."}])
        self.assertEqual(result["current_revision"], 2)
        self.assertEqual(result["revisions"][0]["notes"], [note])
        self.assertEqual(result["revisions"][1]["changed"], [p])

    def test_comparison_freezes_the_reference_before_rendering(self):
        self.fill()
        def freeze(name):
            with patch.object(paperroom, "render_document", return_value=(b"%PDF-frozen", [name.encode()])):
                return review.import_reference(self.db, self.project, self.section,
                                               upload=b"%PDF-ref", title=name)["reference_id"]

        original = freeze("Original")
        render = review._asset_preview

        def overlapping_import(*args):
            self.assertEqual(freeze("Imported during publish"), "ref-2")
            return render(*args)

        with patch.object(review, "_asset_preview", side_effect=overlapping_import):
            result = self.publish(minimum=1)
        by_id = {d["id"]: d for d in result["documents"]}
        self.assertEqual(by_id["rev-1"]["before_id"], original)
        self.assertEqual(result["revisions"][0]["before_id"], original)
        with self.assertRaisesRegex(ValueError, "无需逐条回应"):
            self.publish(minimum=1, responses=[{"note": 1, "status": "kept", "text": "No review yet."}])
        self.respond([{"kind": "keep", "paragraph": self.paras[0], "quote": "examined X", "text": "Clear."}])
        result = self.publish(responses=[{"note": 1, "status": "kept", "text": "Kept."}])
        self.assertEqual(result["revisions"][-1]["before_id"], "rev-1")

    def save_version(self, text, **options):
        """Save a whole-paper version from a stand-in build whose only content is `text`."""
        place = {self.section: {"title": "Introduction", "page": 1, "paragraphs": {p: 1 for p in self.paras}}}
        build = lambda db, project, pdf=None: dict(pdf=b"%PDF-" + text.encode(), images=[text.encode()], main="main.tex",
                                         map=place, texts={self.section: [text]}, source_sha256=text, found=[], lines=[])
        with patch.object(versions, "_compile", build):
            return versions.save(self.db, self.project, **options)

    def test_chat_comparison_link_stays_on_its_pair_as_versions_advance(self):
        import paperroom_mcp as mcp

        def open_versions(**args):
            with patch.object(mcp, "show_author", return_value={"room_url": "local"}) as opened:
                mcp.invoke("open_writing_workspace", {"project": str(self.project), "panel": "versions", **args})
            return opened.call_args.kwargs["query"]

        with self.assertRaisesRegex(ValueError, "还没有保存的排版版本"):
            open_versions()
        links = []
        for number in range(1, 4):
            if number > 1:
                versions.submit_review(self.db, number - 1, [{"kind": "keep", "page": 1, "section": self.section,
                                                              "paragraph": self.paras[0], "text": f"Retain round {number}."}])
            answers = [{"note": 1, "status": "kept", "text": f"Kept for round {number}."}] if number > 1 else None
            self.assertEqual(self.save_version(f"Round {number}.", responses=answers)["number"], number)
            if number > 1:
                links.append(open_versions(before=number - 1, after=number, mode="compare"))
        self.assertEqual([(link["before"], link["after"], link["mode"]) for link in links],
                         [(1, 2, "compare"), (2, 3, "compare")])
        # A link to a named pair keeps naming it after newer versions exist.
        self.assertEqual(open_versions(before=1, after=2, mode="compare"), links[0])
        # Without numbers the page compares the latest version with the one before it.
        latest = open_versions(section=self.section)
        self.assertEqual((latest["before"], latest["after"], latest["view"], latest["section"]),
                         (None, None, "section", self.section))
        for bad in ({"before": 1}, {"before": 2, "after": 2}, {"before": 1, "after": 9},
                    {"mode": "latest", "before": 1, "after": 2}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "版本"):
                open_versions(**bad)
        with self.assertRaisesRegex(ValueError, "排版版本面板"):
            mcp.invoke("open_writing_workspace", {"project": str(self.project), "before": 1, "after": 2})

    def test_legacy_comparison_interprets_offsets_and_excludes_later_references(self):
        self.fill()
        for name in ("Baseline", "Imported afterwards"):
            with patch.object(paperroom, "render_document", return_value=(b"%PDF-frozen", [name.encode()])):
                review.import_reference(self.db, self.project, self.section, upload=b"%PDF-ref", title=name)
        edition = self.publish(minimum=1)["revisions"][0]
        del edition["before_id"]
        edition["created"] = "2025-01-01T12:00:00Z"
        with self.db:
            self.db.execute("UPDATE v2_editions SET body=?", (json.dumps(edition),))
            self.db.executemany("UPDATE v2_references SET created=? WHERE revision=?",
                                [("2025-01-01T13:30:00+02:00", 1), ("2025-01-01T10:30:00-02:00", 2)])
        docs = review.status(self.db, self.project, self.section)["documents"]
        self.assertEqual([d["id"] for d in docs], ["ref-1", "rev-1", "ref-2"])
        self.assertEqual(docs[1]["before_id"], "ref-1")

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

    def test_multi_file_paper_publishes_from_its_main_tex(self):
        # A first rewrite edits sections/intro.tex and renders the whole paper's main.tex.
        self.fill()
        (self.project / "sections").mkdir()
        (self.project / "sections/intro.tex").write_text(
            "\\section{Introduction}\nPrior work examined X.\n\nWe investigate Y.\n")
        (self.project / "sections/old.tex").write_text("Stale text.\n")
        main = self.project / "main.tex"
        main.write_text("\\documentclass{article}\n\\begin{document}\n\\input{sections/intro}\n"
                        "% \\input{sections/old}\n\\end{document}\n")
        result = self.publish(tex=main, pages="1")
        self.assertEqual(result["phase"], "review")
        frozen = self.db.execute("SELECT content FROM v2_pages WHERE revision=1 AND page=0").fetchone()[0]
        self.assertIn(b"We investigate Y.", frozen)
        self.assertNotIn(b"Stale text.", frozen)
        # Editing the included file changes the request, so an edit during rendering is caught.
        before = review._publish_request(self.project, main, None, "1", 3)
        (self.project / "sections/intro.tex").write_text("\\section{Introduction}\nChanged.\n")
        self.assertNotEqual(before, review._publish_request(self.project, main, None, "1", 3))

    def test_existing_chapter_without_saved_layout_is_flagged_before_edits(self):
        (self.project / "sections").mkdir()
        (self.project / "sections/intro.tex").write_text("\\section{ Introduction }\nOld text.\n")
        (self.project / "notes.tex").write_text("% \\section{Introduction}\n\\section{Results}\n")
        hint = review.original_hint(self.project, "Introduction", [])
        self.assertEqual(hint["files"], ["sections/intro.tex"])
        self.assertIsNone(review.original_hint(self.project, "Introduction", [{"id": "ref-1"}]))
        self.assertIsNone(review.original_hint(self.project, "Discussion", []))
