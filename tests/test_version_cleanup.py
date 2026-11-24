"""Stable links and author-confirmed cleanup of Paperroom's saved layout copies."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import journal
import versions


class VersionCleanup(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.project = Path(directory.name)
        self.path = self.project / "paperroom.sqlite"
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)

    def compiled(self, name):
        return {"pdf": b"%PDF-" + name.encode(), "images": [name.encode()],
                "main": "main.tex", "texts": {"intro": [name]}, "source_sha256": name,
                "map": {"intro": {"title": "Introduction", "page": 1, "paragraphs": {}}}}

    def save(self, name, **options):
        with patch.object(versions, "_compile", return_value=self.compiled(name)):
            return versions.save(self.db, self.project, **options)

    def test_source_change_during_render_preserves_previous_version(self):
        first = self.save("first")
        main = self.project / "main.tex"
        main.write_text("before")
        compiled = self.compiled("next")
        compiled["lines"] = versions.L.expand(self.project, main)
        main.write_text("after")
        with patch.object(versions, "_compile", return_value=compiled):
            with self.assertRaisesRegex(ValueError, "源码已改变"):
                versions.save(self.db, self.project, expected=first["number"])
        self.assertEqual(len(versions.listing(self.db)), 1)

    def snapshot(self):
        rows = versions.listing(self.db)
        return [row["number"] for row in rows], [len(row["notes"]) for row in rows]

    def test_existing_project_renumbers_only_the_visible_labels(self):
        db = self.db
        with db:
            versions.create_tables(db)
            versions._store(db, 0, "original", "original", self.compiled("original"), None)
        for number in range(1, 5):
            prior = number - 1
            note = {"kind": "change", "page": 1, "text": f"Review {prior}"}
            versions.submit_review(db, prior, [note])
            self.save(f"round {number}", responses=[{"note": 1, "status": "changed", "text": f"Answer {prior}"}])

        # The installed version did not write display numbers or explicit predecessors.
        with db:
            for number, payload in db.execute("SELECT number,body FROM v2_versions").fetchall():
                body = json.loads(payload)
                body.pop("display_number")
                body.pop("previous_number")
                db.execute("UPDATE v2_versions SET body=? WHERE number=?", (json.dumps(body), number))
        before = versions.get(db, 4)
        old_log = journal.export_events(db)
        preview = self.snapshot()
        result = versions.cleanup(db, [1, 2, 3], *preview)
        self.assertEqual([(v["number"], v["display_number"]) for v in result["versions"]], [(0, 0), (4, 1)])
        self.assertEqual([v["last_display_number"] for v in result["archived_versions"]], [1, 2, 3])
        kept = versions.get(db, 4)
        for field in ("created", "pdf_sha256", "map", "texts", "notes", "responses", "previous_number", "compared_with"):
            self.assertEqual(kept[field], before[field])
        self.assertEqual(kept["previous_number"], 3)
        self.assertEqual(versions.get(db, 3)["notes"][0]["text"], "Review 3")
        self.assertEqual(kept["responses"][0]["text"], "Answer 3")
        for n in range(1, 4):
            self.assertIsNone(versions.page(db, n, -1))
            self.assertIsNone(versions.page(db, n, 1))
        self.assertEqual(versions.page(db, 4, -1), b"%PDF-round 4")
        self.assertEqual(versions.page(db, 4, 1), b"round 4")
        self.assertEqual(versions.page(db, 0, -1), b"%PDF-original")
        self.assertEqual(journal.export_events(db)[:-1], old_log)
        self.assertEqual(journal.export_events(db)[-1]["kind"], "versions_cleaned")
        self.assertEqual(versions.cleanup(db, [1, 2, 3], *preview), result)
        self.assertEqual(len(journal.export_events(db)), len(old_log) + 1)
        with self.assertRaisesRegex(ValueError, "最新"):
            versions.submit_review(db, 1, [], approve=True)
        new = self.save("fresh round", expected=4)
        self.assertEqual((new["number"], new["display_number"], new["previous_number"]), (5, 2, 4))

    def test_no_recycled_ids_after_cleaning_latest_or_entire_list(self):
        for name in ("first", "second", "third"):
            self.save(name)
        versions.cleanup(self.db, [2, 3], *self.snapshot())
        with self.assertRaisesRegex(ValueError, "版本已更新"):
            self.save("fourth", expected=3)
        new = self.save("fourth", expected=1)
        self.assertEqual((new["number"], new["display_number"], new["compared_with"]), (4, 2, 1))
        self.assertEqual(self.save("fourth", expected=1), new)
        with self.assertRaisesRegex(ValueError, "版本已更新"):
            self.save("fourth", expected=3)
        versions.cleanup(self.db, [1, 4], *self.snapshot())
        self.assertEqual(versions.listing(self.db), [])
        with patch.object(versions, "_located_sections", side_effect=AssertionError("must not re-freeze")):
            self.assertIsNone(versions.freeze_original(self.db, self.project))
        restarted = self.save("fifth")
        self.assertEqual((restarted["number"], restarted["display_number"], restarted["previous_number"]), (5, 1, None))

    def test_confirmation_detects_new_notes_or_a_new_version_and_rejects_v0(self):
        self.save("first")
        preview = self.snapshot()
        versions.submit_review(self.db, 1, [{"page": 1, "kind": "keep", "text": "An important review"}])
        with self.assertRaisesRegex(ValueError, "重新预览"):
            versions.cleanup(self.db, [1], *preview)
        preview = self.snapshot()
        self.save("second", responses=[{"note": 1, "status": "kept", "text": "Kept"}])
        with self.assertRaisesRegex(ValueError, "重新预览"):
            versions.cleanup(self.db, [1], *preview)
        with self.assertRaisesRegex(ValueError, "V0"):
            versions.cleanup(self.db, [0, 1], *self.snapshot())
        self.assertEqual(versions.page(self.db, 1, -1), b"%PDF-first")

    def test_racing_save_checks_the_retained_version_after_rendering(self):
        self.save("first")
        self.save("second")

        def render(*_):
            with closing(sqlite3.connect(self.path)) as other:
                versions.cleanup(other, [1], *self.snapshot())
            return self.compiled("third")

        with patch.object(versions, "_compile", side_effect=render), self.assertRaisesRegex(ValueError, "请重新读取"):
            versions.save(self.db, self.project, expected=2)
        self.assertEqual(self.snapshot()[0], [2])
        self.assertEqual(self.save("third", expected=2)["display_number"], 2)

    def test_failed_cleanup_rolls_back_metadata_and_blobs(self):
        for name in ("first", "second"):
            self.save(name)
        previous = versions.version_lists(self.db)
        with patch.object(journal, "append", side_effect=sqlite3.OperationalError("disk full")):
            with self.assertRaises(sqlite3.OperationalError):
                versions.cleanup(self.db, [1], *self.snapshot())
        self.assertEqual(versions.version_lists(self.db), previous)
        self.assertEqual(versions.page(self.db, 1, -1), b"%PDF-first")
        self.assertEqual(versions.page(self.db, 1, 1), b"first")
