"""An author's unfinished forms travel with the manuscript, without being submitted."""
from contextlib import closing
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from test_document_reader import Paper, TEXTS, chrome, serve
import paperroom
import workspace_server as web


class HandoffTests(unittest.TestCase):
    def test_old_outline_draft_recovers_after_move_and_cannot_reappear_after_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp, "original")
            old.mkdir()
            project_key = web.read_snapshot(old)["project"]
            old_key = f"paperroom-author-v2:/workspace:{project_key}:section:abc::"
            draft = {"base": 3, "fields": {"items": [{"purpose": "Private outline."}]}}
            with closing(paperroom.connect(web.database_path(old))) as db, db:
                db.execute("CREATE TABLE v2_author_autosaves (key TEXT PRIMARY KEY, etag TEXT, body TEXT)")
                db.execute("INSERT INTO v2_author_autosaves VALUES (?,?,?)", (old_key, "old", json.dumps(draft)))
            moved = old.rename(Path(tmp, "coauthor"))
            new_key = old_key.replace(project_key, web.read_snapshot(moved)["project"])
            self.assertNotEqual(old_key, new_key)
            with closing(paperroom.connect(web.database_path(moved))) as db:
                self.assertEqual(web.outline_draft(db, new_key), {"etag": "old", "draft": draft})
                etag = web.save_outline_draft(db, {"key": new_key, "etag": "old", "draft": draft})["etag"]
                with self.assertRaises(ValueError):
                    web.save_outline_draft(db, {"key": old_key, "etag": "old", "draft": None})
                web.save_outline_draft(db, {"key": new_key, "etag": etag, "draft": None})
                self.assertIsNone(web.outline_draft(db, old_key)["draft"])

    @unittest.skipUnless(shutil.which("node") and chrome(), "Needs Node.js and Chrome.")
    def test_fresh_browser_at_new_path_recovers_outline_and_unsubmitted_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp, "original")
            original.mkdir()
            paper = Paper(original)
            paper.original(2, 1, 2, TEXTS)
            paper.save(2, 1, 2, TEXTS)
            run = serve(original, "handoff.mjs", "write", paper.intro)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            moved = Path(tmp, "coauthor")
            shutil.copytree(original, moved)
            shutil.rmtree(original)
            snapshot = web.read_snapshot(moved)
            self.assertNotIn("unsent", json.dumps(snapshot))
            self.assertEqual(snapshot["versions"][-1]["notes"], [])
            run = serve(moved, "handoff.mjs", "recover", paper.intro)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(web.read_snapshot(moved)["versions"][-1]["notes"][0]["text"], "unsent review")
