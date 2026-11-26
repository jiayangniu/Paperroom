import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"))
import outline


class OutlineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dbfile = self.root / "author.sqlite3"
        self.db = sqlite3.connect(self.dbfile)
        self.addCleanup(self.db.close)

    def initial(self):
        assets = outline.update_assets(
            self.db, self.root, 0, "What changes?", "Paired results\nA second trial"
        )
        self.plan = outline.submit(
            self.db,
            self.root,
            assets["version"],
            "paper",
            [
                {"title": "Introduction", "purpose": "Motivate the two decisions"},
                {"title": "Results", "purpose": "Report experiments"},
            ],
        )
        self.intro, self.results = self.plan["sections"]
        self.plan = outline.submit(
            self.db,
            self.root,
            self.plan["version"],
            "section",
            [{"purpose": "Position the method"}, {"purpose": "Separate the two decisions"}],
            self.intro["id"],
        )
        self.p1, self.p2 = self.plan["sections"][0]["paragraphs"]

    def approve(self, para, lines):
        self.plan = outline.submit(
            self.db,
            self.root,
            self.plan["version"],
            "paragraph",
            lines,
            self.intro["id"],
            para["id"],
        )

    def test_subheadings_group_existing_paragraphs_without_reopening_intents(self):
        self.initial()
        self.approve(self.p1, [r"Define $\theta$.", r"Write $r > p$."])
        original = self.plan["sections"][0]["paragraphs"]
        p1, p2 = ({"id": p["id"], "purpose": p["purpose"]} for p in original)

        def save(items):
            self.plan = outline.submit(self.db, self.root, self.plan["version"], "section",
                                       items, self.intro["id"])
            return outline.state(self.db, self.root)["sections"][0]

        a = {"type": "heading", "title": "Adaptive growth"}
        b = {"type": "heading", "title": r"Noisy $\theta$"}
        after = save([a, p1, b, p2])
        self.assertEqual(after["paragraphs"], original)
        self.assertEqual(after["subheadings"], [{"before": 0, "title": a["title"]},
                                                 {"before": 1, "title": b["title"]}])
        md = (self.root / "paper.md").read_text()
        self.assertLess(md.index("#### Adaptive growth"), md.index("##### Paragraph 1"))
        self.assertLess(md.index(b["title"]), md.index("##### Paragraph 2"))
        # Relabel and move a heading to the end. Then remove just that heading.
        renamed = {**a, "title": "Later"}
        self.assertEqual(save([p1, p2, renamed])["subheadings"], [{"before": 2, "title": "Later"}])
        after = save([p1, p2])
        self.assertEqual(after["subheadings"], [])
        self.assertEqual(after["paragraphs"], original)
        self.assertIn("#### Paragraph 2", (self.root / "paper.md").read_text())

    def test_delete_saved_paragraphs_keeps_surviving_intents_and_manuscript(self):
        self.initial()
        self.approve(self.p1, ["This intent stays with its paragraph."])
        retained = self.plan["sections"][0]["paragraphs"][0]
        manuscript = self.root / "section.tex"
        manuscript.write_text("Existing manuscript")
        def save(items):
            self.plan = outline.submit(self.db, self.root, self.plan["version"],
                                       "section", items, self.intro["id"])
            return outline.state(self.db, self.root)["sections"][0]

        heading = {"type": "heading", "title": "Method overview"}
        after = save([heading, retained])
        self.assertEqual(after["paragraphs"], [retained])
        self.assertEqual(after["subheadings"], [{"before": 0, "title": "Method overview"}])
        with self.assertRaises(ValueError):
            outline.require_paragraph(self.db, self.root, self.intro["id"], self.p2["id"])
        cleared = save([])
        self.assertFalse(cleared["planned"])
        self.assertEqual(cleared["paragraphs"], [])
        self.assertEqual(cleared["subheadings"], [])
        self.assertEqual(manuscript.read_text(), "Existing manuscript")
        with self.assertRaises(ValueError):
            outline.require_section(self.db, self.root, self.intro["id"])
        with self.assertRaises(ValueError):
            save([])

    def test_partial_unlock_and_scoped_reconfirmation(self):
        self.initial()
        self.approve(self.p2, ["Name both choices.", "Explain the distinction."])
        second = outline.require_paragraph(self.db, self.root, self.intro["id"], self.p2["id"])
        self.assertTrue(second["ready"])
        with self.assertRaises(ValueError):
            outline.require_section(self.db, self.root, self.intro["id"])
        self.approve(self.p1, ["State the previous approach."])
        self.assertEqual(
            len(outline.require_section(self.db, self.root, self.intro["id"])["paragraphs"]), 2
        )
        self.plan = outline.submit(
            self.db,
            self.root,
            self.plan["version"],
            "section",
            [
                {"id": self.p2["id"], "purpose": self.p2["purpose"]},
                {"id": self.p1["id"], "purpose": "New positioning"},
            ],
            self.intro["id"],
        )
        p2, p1 = self.plan["sections"][0]["paragraphs"]
        self.assertEqual(p2["revision"], second["revision"])
        self.assertTrue(p2["ready"])
        self.assertFalse(p1["ready"])
        self.assertEqual(p1["sentences"], ["State the previous approach."])
        self.plan = outline.update_assets(
            self.db,
            self.root,
            self.plan["version"],
            "What changes?",
            "More results",
            affected_sections=[self.results["id"]],
        )
        self.assertTrue(self.plan["sections"][0]["paragraphs"][0]["ready"])

    def test_pure_status_cas_manual_edit_and_user_content(self):
        self.assertEqual(outline.state(None, self.root)["version"], 0)
        file = self.root / "paper.md"
        self.assertFalse(file.exists())
        user_text = "# My own notebook\r\nUnrelated article notes.\r\n"
        file.write_bytes(user_text.encode())
        self.initial()
        self.approve(self.p1, ["Our first argument", "A multi-line thought\nwith an example."])
        old = self.plan["version"]
        data = file.read_bytes()
        self.assertTrue(data.startswith(user_text.encode()))
        revised = (
            data.replace(b"Our first argument", b"A more precise argument")
            + b"\nExtra personal notes.\n"
        )
        file.write_bytes(revised)
        manual = outline.state(None, self.root)
        self.assertNotEqual(manual["version"], old)
        item = manual["sections"][0]["paragraphs"][0]
        self.assertFalse(item["ready"])
        self.assertEqual(
            item["sentences"], ["A more precise argument", "A multi-line thought\nwith an example."]
        )
        with self.assertRaises(ValueError):
            outline.submit(
                self.db,
                self.root,
                old,
                "paragraph",
                ["Would overwrite"],
                self.intro["id"],
                self.p1["id"],
            )
        self.assertEqual(file.read_bytes(), revised)
        self.plan = manual
        self.approve(self.p1, item["sentences"])
        self.assertTrue(file.read_bytes().startswith(user_text.encode()))
        self.assertTrue(file.read_bytes().endswith(b"Extra personal notes.\n"))

    def test_duplicate_wrong_parent_and_incomplete_assets_do_not_grant(self):
        with self.assertRaises(ValueError):
            outline.submit(self.db, self.root, 0, "paper", [{"title": "One", "purpose": "Reason"}])
        self.initial()
        before = (self.root / "paper.md").read_bytes()
        with self.assertRaises(ValueError):
            outline.submit(
                self.db,
                self.root,
                self.plan["version"],
                "section",
                [
                    {"id": self.p1["id"], "purpose": "Once"},
                    {"id": self.p1["id"], "purpose": "Twice"},
                ],
                self.intro["id"],
            )
        with self.assertRaises(ValueError):
            outline.submit(
                self.db,
                self.root,
                self.plan["version"],
                "paragraph",
                ["Wrong parent"],
                self.results["id"],
                self.p1["id"],
            )
        self.assertEqual((self.root / "paper.md").read_bytes(), before)

    def test_concurrent_author_sessions(self):
        def patch(note):
            with closing(sqlite3.connect(self.dbfile, timeout=5)) as db:
                try:
                    return outline.update_assets(db, self.root, 0, "Q", note)["evidence"]
                except ValueError:
                    return None

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(patch, ["first", "second"]))
        self.assertEqual(len([r for r in results if r]), 1)
        self.assertIn(outline.state(None, self.root)["evidence"], results)

    def test_partial_assets_are_editable_and_external_parent_changes_require_review(self):
        draft = outline.update_assets(self.db, self.root, 0, "", "First trial")
        self.assertEqual(draft["evidence"], "First trial")
        with self.assertRaises(ValueError):
            outline.submit(
                self.db, self.root, draft["version"], "paper", [{"title": "A", "purpose": "B"}]
            )
        complete = outline.update_assets(self.db, self.root, draft["version"], "Q", "First trial")
        paper = outline.submit(
            self.db, self.root, complete["version"], "paper", [{"title": "A", "purpose": "Why Q"}]
        )
        section = paper["sections"][0]["id"]
        plan = outline.submit(
            self.db, self.root, paper["version"], "section", [{"purpose": "Motivate"}], section
        )
        para = plan["sections"][0]["paragraphs"][0]["id"]
        approved = outline.submit(
            self.db, self.root, plan["version"], "paragraph", ["One reason"], section, para
        )
        self.assertTrue(approved["sections"][0]["paragraphs"][0]["ready"])
        path = self.root / "paper.md"
        path.write_text(path.read_text().replace("> Why Q", "> Bound Q"))
        changed = outline.state(None, self.root)
        self.assertFalse(changed["sections"][0]["planned"])
        with self.assertRaises(ValueError):
            outline.submit(
                self.db, self.root, changed["version"], "paragraph", ["New reason"], section, para
            )

    def test_conflicting_manual_syntax_and_external_symlinks_are_preserved(self):
        self.initial()
        path = self.root / "paper.md"
        broken = path.read_text().replace("## Experimental evidence", "## Other heading")
        path.write_text(broken)
        with self.assertRaises(ValueError):
            outline.update_assets(self.db, self.root, self.plan["version"], "Q", "Evidence")
        self.assertEqual(path.read_text(), broken)
        path.rename(self.root / "separate.md")
        path.symlink_to(self.root / "separate.md")
        with self.assertRaises(ValueError):
            outline.update_assets(self.db, self.root, self.plan["version"], "Q", "Evidence")
        self.assertEqual((self.root / "separate.md").read_text(), broken)

    def test_utf8_bom_and_crlf_preserve_three_level_outline(self):
        self.initial()
        self.approve(self.p1, ["First sentence.", "Second sentence."])
        path = self.root / "paper.md"
        crlf = path.read_text(encoding="utf-8").replace("\n", "\r\n")
        path.write_bytes(b"\xef\xbb\xbf" + crlf.encode("utf-8"))
        loaded = outline.state(self.db, self.root)
        intro = loaded["sections"][0]
        self.assertTrue(intro["adopted"])
        self.assertTrue(intro["planned"])
        self.assertEqual(len(intro["paragraphs"]), 2)
        self.assertTrue(intro["paragraphs"][0]["ready"])
        self.assertEqual(intro["paragraphs"][0]["sentences"], ["First sentence.", "Second sentence."])
