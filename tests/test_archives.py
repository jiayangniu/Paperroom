"""Copy, recovery and version identity for whole-project archives."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"))
import archives


def request():
    return uuid.uuid4().hex


class ArchivesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name).resolve() / "Shared Paper"
        self.project.mkdir()
        self.tex = self.project / "main.tex"
        self.tex.write_text("original")
        self.db = self.project / "paperroom_tool/.paperroom/project.sqlite3"
        self.db.parent.mkdir(parents=True)

    def save(self, commit=""):
        return archives.create(self.project, commit, request_id=request(), expected_generation=archives.generation(self.project))

    def switch(self, target, **kw):
        return archives.switch(self.project, target, request_id=kw.get("key", request()),
                               expected_generation=kw.get("expected", archives.generation(self.project)))

    def test_independent_wal_backup_switch_and_switch_back(self):
        with sqlite3.connect(self.db) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE notes(text)")
            db.execute("INSERT INTO notes VALUES ('first')")
            db.commit()
            first = self.save("Three sections")["created"]
            db.execute("INSERT INTO notes VALUES ('second')")
            db.commit()
        db.close()
        self.tex.write_text("reworked")
        (self.project / "results.csv").write_text("new results")
        (self.project / ".git").mkdir()
        head = self.project / ".git/HEAD"
        head.write_text("current branch")
        inode = self.project.stat().st_ino
        key = request()
        result = self.switch(first, key=key)
        self.assertEqual(self.tex.read_text(), "original")
        self.assertFalse((self.project / "results.csv").exists())
        self.assertEqual(self.project.stat().st_ino, inode)
        self.assertEqual(head.read_text(), "current branch")
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT * FROM notes").fetchall(), [("first",)])
        db.close()
        self.assertEqual(self.switch(first, key=key, expected="")["backup"], result["backup"])
        with self.assertRaises(ValueError):
            self.switch(first, expected="")
        self.switch(result["backup"])
        self.assertEqual(self.tex.read_text(), "reworked")
        self.assertEqual((self.project / "results.csv").read_text(), "new results")
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM notes").fetchone()[0], 2)
        db.close()

    def test_failed_backup_or_install_keeps_current_version_and_generation(self):
        first = self.save()["created"]
        self.tex.write_text("keep this")
        with patch.object(archives, "_capture", side_effect=OSError("disk full")), self.assertRaises(archives.SafetyCopyFailed):
            self.switch(first)
        self.assertEqual(len(archives.listing(self.project)["archives"]), 1)
        replace = os.replace
        def fail(src, dest):
            if Path(src).parent.name == "new" and Path(dest) == self.tex:
                raise OSError("rename refused")
            return replace(src, dest)
        with patch.object(os, "replace", side_effect=fail), self.assertRaises(OSError):
            self.switch(first)
        self.assertEqual(self.tex.read_text(), "keep this")
        self.assertEqual(archives.generation(self.project), "")
        self.assertEqual(len(archives.listing(self.project)["archives"]), 2)

    def test_external_edit_after_safety_copy_stops_switch(self):
        old = self.save()["created"]
        self.tex.write_text("new")
        capture = archives._capture
        def external_edit(*args):
            result = capture(*args)
            self.tex.write_text("editor changed it during switch")
            return result
        with patch.object(archives, "_capture", side_effect=external_edit), self.assertRaisesRegex(ValueError, "changed"):
            self.switch(old)
        self.assertEqual(self.tex.read_text(), "editor changed it during switch")
        self.assertEqual(archives.generation(self.project), "")

    def test_resource_links_and_nested_git_survive(self):
        external = self.project.parent / "outside"
        external.mkdir()
        (external / "untouched").write_text("only outside")
        link = self.project / "figures"
        link.symlink_to(external, target_is_directory=True)
        old = self.save()["created"]
        link.unlink()
        (self.project / "only-new/.git").mkdir(parents=True)
        git = self.project / "only-new/.git/config"
        git.write_text("current nested metadata")
        (git.parent.parent / "new.tex").write_text("untracked")
        self.switch(old)
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), str(external))
        self.assertEqual(git.read_text(), "current nested metadata")
        self.assertFalse((git.parent.parent / "new.tex").exists())
        self.assertEqual((external / "untouched").read_text(), "only outside")

    def test_recovery_before_next_read_after_process_exit_mid_switch(self):
        # Simulate a process exit after moving the live file to staging, before
        # installing its replacement. Close-and-reopen follows the same durable record.
        old = self.save()["created"]
        self.tex.write_text("keep newer")
        replace = os.replace
        recover = archives._recover
        def interrupt(src, dest):
            if Path(src).parent.name == "new" and Path(dest) == self.tex:
                raise KeyboardInterrupt()
            return replace(src, dest)
        def skip_crash_cleanup(project):
            if "pending" not in archives._state(project):
                recover(project)
        with patch.object(os, "replace", side_effect=interrupt), patch.object(archives, "_recover", side_effect=skip_crash_cleanup):
            with self.assertRaises(KeyboardInterrupt):
                self.switch(old)
        with archives.workspace_lock(self.project):
            self.assertEqual(self.tex.read_text(), "keep newer")
            self.assertFalse("pending" in archives._state(self.project))

    def test_no_parent_writes_for_listing_and_deduplicated_manual_click(self):
        self.assertEqual(archives.listing(self.project), {"archives": [], "generation": ""})
        self.assertEqual(set(self.project.parent.iterdir()), {self.project})
        key = str(uuid.uuid4())
        a = archives.create(self.project, "first", request_id=key, expected_generation="")
        self.assertEqual(a, archives.create(self.project, "first", request_id=key, expected_generation=""))
        with self.assertRaises(ValueError):
            archives.create(self.project, "different", request_id=key, expected_generation="")
        with self.assertRaises(ValueError):
            self.switch("../outside")
