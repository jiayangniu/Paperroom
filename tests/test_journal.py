import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"))
import journal
import outline
import paperroom
import section_review


class JournalTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = Path(folder.name)
        self.dbpath = self.project / "records.sqlite3"
        self.db = paperroom.connect(self.dbpath)
        self.addCleanup(self.db.close)
        self.file = self.project / "paper.md"
        self.sections = [dict(title="引言", purpose="为什么值得研究")]
        outline.update_assets(self.db, self.project, 0, "论文问题", "测量结果")

    def test_commit_chain_and_idempotent_submissions(self):
        db, project = self.db, self.project
        doc = outline.submit(db, project, 1, "paper", self.sections)
        section = doc["sections"][0]["id"]
        doc = outline.submit(db, project, 2, "section", [dict(purpose="解释差异")], section)
        para = doc["sections"][0]["paragraphs"][0]["id"]
        doc = outline.submit(db, project, 3, "paragraph", ["第一句", "第二句"], section, para)
        with self.assertRaises(ValueError):
            outline.submit(db, project, 3, "paragraph", ["第一句", "第二句"], section, para)
        plan_revision = doc["sections"][0]["paragraphs"][0]["revision"]
        section_review.save_paragraph_draft(db, project, section, para, plan_revision, "组合结果。")
        with patch.object(paperroom, "render_document", return_value=(b"pdf", [b"png"])):
            with patch.object(journal, "append", side_effect=RuntimeError), self.assertRaises(RuntimeError):
                section_review.publish_section(db, project, section, minimum=1)
            self.assertEqual(section_review.status(db, project, section)["revisions"], [])
            for _ in range(2):
                edition = section_review.publish_section(db, project, section, minimum=1)["revisions"][-1]
        notes = [dict(kind="keep", paragraph=para, text="这句概括了实验。")]
        with patch.object(journal, "append", side_effect=RuntimeError), self.assertRaises(RuntimeError):
            section_review.submit_review(db, project, section, 1, notes)
        self.assertEqual(section_review.status(db, project, section)["phase"], "review")
        for _ in range(2):
            reviewed = section_review.submit_review(db, project, section, 1, notes)["revisions"][-1]

        events = journal.export_events(db)
        self.assertEqual([e["kind"] for e in events], ["paper_outline", "section_outline",
                         "paragraph_outline", "section_published", "section_reviewed"])
        self.assertEqual(len(set(e["salt"] for e in events)), len(events))
        previous = None
        for seq, event in enumerate(events, 1):
            self.assertEqual(event["seq"], seq)
            self.assertEqual(event["previous_digest"], previous)
            self.assertRegex(event["recorded_at"], r"\.\d{6}Z$")
            self.assertRegex(event["salt"], "^[a-f0-9]{64}$")
            canonical = json.dumps({k:v for k,v in event.items() if k != "digest"}, sort_keys=True,
                                   ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), event["digest"])
            self.assertNotEqual(journal.event_digest(dict(event, recorded_at="changed")), event["digest"])
            previous = event["digest"]
        self.assertEqual(events[0]["payload"]["question"], "论文问题")
        self.assertEqual(events[2]["payload"]["sentences"], ["第一句", "第二句"])
        self.assertEqual(events[3]["payload"]["pdf_sha256"], hashlib.sha256(b"pdf").hexdigest())
        self.assertEqual(events[3]["recorded_at"], edition["created"])
        self.assertEqual(events[-1]["recorded_at"], reviewed["reviewed"])
        self.assertEqual(events[-1]["payload"]["notes"], notes)
        self.assertTrue(all(not {"payload", "salt"}.intersection(e) for e in journal.events(db)))

    def test_old_markdown_is_not_backfilled_and_failed_submit_is_atomic(self):
        old = self.file.read_bytes()
        with closing(sqlite3.connect(self.dbpath.as_uri() + "?mode=ro", uri=True)) as reader:
            self.assertEqual(outline.state(reader, self.project)["version"], 1)
            self.assertEqual(journal.events(reader), [])
        with patch.object(journal, "append", side_effect=RuntimeError), self.assertRaises(RuntimeError):
            outline.submit(self.db, self.project, 1, "paper", self.sections)
        self.assertEqual(self.file.read_bytes(), old)
        self.assertEqual(outline.state(self.db, self.project)["version"], 1)
        self.assertEqual(journal.events(self.db), [])

    def test_interrupted_file_projection_keeps_committed_action_and_replays_once(self):
        with patch.object(outline.os, "replace", side_effect=OSError("interrupted")), self.assertRaises(OSError):
            outline.submit(self.db, self.project, 1, "paper", self.sections)
        with closing(sqlite3.connect(self.dbpath.as_uri() + "?mode=ro", uri=True)) as reader:
            self.assertEqual(outline.state(reader, self.project)["version"], 2)
            self.assertEqual(len(journal.events(reader)), 1)
        self.assertNotIn("值得", self.file.read_text())
        # Retry a request whose response was lost. The next mutation materializes
        # the committed version, even when the caller's compare-and-swap is stale.
        with self.assertRaises(ValueError):
            outline.submit(self.db, self.project, 1, "paper", self.sections)
        self.assertIn("值得", self.file.read_text())
        outline.update_assets(self.db, self.project, 2, "新问题", "测量结果")
        self.assertEqual(len(journal.events(self.db)), 1)
        self.assertEqual(outline.state(None, self.project)["version"], 3)

    def test_external_edit_after_interruption_is_preserved(self):
        with patch.object(outline.os, "replace", side_effect=OSError), self.assertRaises(OSError):
            outline.submit(self.db, self.project, 1, "paper", self.sections)
        self.file.write_text(self.file.read_text().replace("论文问题", "新问题"))
        state = outline.state(self.db, self.project)
        self.assertEqual(state["question"], "新问题")
        doc = outline.submit(self.db, self.project, state["version"], "paper", self.sections)
        self.assertEqual(doc["question"], "新问题")
        self.assertEqual([e["payload"]["question"] for e in journal.export_events(self.db)],
                         ["论文问题", "新问题"])
