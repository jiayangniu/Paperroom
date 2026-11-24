"""Author consent for restored archive messages and exact-file disclosure previews."""
from contextlib import closing
from pathlib import Path
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import journal
import timestamps


class DisclosureTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name).resolve() / "project.sqlite3"

    def test_archive_message_is_private_and_individually_disclosable(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN")
            journal.append(db, "checkpoint_restored", {"archive_id": "a42", "commit": "Discuss with Ada"})
        private = timestamps.export_verifiable_log(self.path)
        self.assertNotIn("Discuss with Ada", json.dumps(private))
        self.assertEqual(private["events"][0]["summary"]["archive_id"], "a42")
        choices = timestamps.disclosable_items(self.path)["events"][0]["items"]
        self.assertEqual([(c["id"], c["content"]) for c in choices], [("commit", "Discuss with Ada")])
        public = timestamps.export_verifiable_log(self.path, disclose={"1": ["commit"]})
        self.assertEqual(public["events"][0]["disclosed"]["commit"]["content"], "Discuss with Ada")
        self.assertEqual(private["events"][0]["digest"], public["events"][0]["digest"])

    def test_frozen_early_version_public_message_requires_explicit_consent(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN")
            journal.append(db, "versions_cleaned", {"removed": []})
            old = {"schema": "paperroom.event.v2", "seq": 2, "kind": "checkpoint_restored",
                   "recorded_at": journal.utc_now(), "previous_digest": journal.raw_events(db)[0]["digest"],
                   "summary": {"archive_id": "old", "commit": "Historic private remark"}, "commitments": []}
            old["digest"] = journal.event_digest(old)
            db.execute("INSERT INTO v2_journal VALUES (?,?,?)", (2, old["digest"], journal.canonical_json(old)))
        with self.assertRaisesRegex(ValueError, "存档备注"):
            timestamps.export_verifiable_log(self.path)
        choices = timestamps.disclosable_items(self.path)["events"][0]["items"]
        self.assertEqual(choices[0]["content"], "Historic private remark")
        bundle = timestamps.export_verifiable_log(self.path, disclose={"2": [choices[0]["id"]]})
        self.assertEqual(bundle["events"][1]["summary"], old["summary"])
        self.assertEqual(bundle["events"][1]["digest"], old["digest"])
        self.assertEqual(journal.event_digest(bundle["events"][1]), old["digest"])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(len(journal.export_events(db, include_secrets=False, up_to_seq=1)), 1)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the author dialog test.")
    def test_preview_and_download_share_bytes_and_follow_the_authors_current_choices(self):
        subprocess.run(["node", str(ROOT / "tests/browser/disclosure-preview.mjs"),
                        str(RUNTIME / "workspace.js")], check=True, capture_output=True, text=True)
