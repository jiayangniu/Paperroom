"""The PDF verdict must come from the submitted version's recorded digest."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from test_verifiable_log import ROOT, cli_verifier, journal, run_browser_verifier, timestamps


@unittest.skipUnless(shutil.which("node"), "Needs Node.js for the browser verifier.")
class BoundPdfTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / "project.sqlite3"
        self.pdf = self.root / "manuscript.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 submission")
        self.old_pdf = b"%PDF-1.4 earlier"
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN")
            for number, content in enumerate((self.old_pdf, self.pdf.read_bytes()), 1):
                journal.append(db, "version_saved", {"number": number, "pdf_sha256": sha256(content).hexdigest()},
                               revision=number)
            journal.append(db, "version_reviewed", {"number": 2, "approved": True}, revision=2)
        self.bundle = timestamps.export_verifiable_log(self.path)

    def test_envelope_must_identify_final_saved_event(self):
        for field, other in (("pdf_sha256", sha256(self.old_pdf).hexdigest()), ("number", 1), ("event_seq", 3)):
            with self.subTest(field=field):
                bundle = dict(self.bundle, target_version={**self.bundle["target_version"], field: other})
                with self.assertRaisesRegex(ValueError, "投稿版本"):
                    cli_verifier.verify_bundle(bundle)
                result = run_browser_verifier(bundle, self.pdf.read_bytes())
                self.assertFalse(result["ok"])
                self.assertEqual(result["pdfCheck"]["status"], "invalid_target")

    def test_reader_can_select_earlier_version_without_changing_submission(self):
        result = run_browser_verifier(self.bundle, self.old_pdf, selected_seq=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["pdfCheck"]["status"], "match_local")
        self.assertEqual(result["targetVer"]["event_seq"], 1)
        self.assertEqual(self.bundle["target_version"]["event_seq"], 2)
        self.assertEqual(run_browser_verifier(self.bundle, self.old_pdf)["pdfCheck"]["status"], "mismatch")
        export = self.root / "log.json"
        export.write_text(json.dumps(self.bundle))
        output = subprocess.check_output([sys.executable, str(ROOT / "scripts/verify_timestamps.py"), str(export),
                                          "--pdf", str(self.pdf)], text=True)
        self.assertIn("不在受信时间戳覆盖范围内", output)

    def test_legacy_save_can_bind_only_if_disclosed(self):
        path = self.root / "legacy.sqlite3"
        fingerprint = sha256(self.pdf.read_bytes()).hexdigest()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE v2_journal (seq INTEGER PRIMARY KEY, digest TEXT UNIQUE, event TEXT)")
            ev = dict(schema="paperroom.event.v1", seq=1, kind="version_saved", previous_digest=None,
                      payload=dict(number=1, pdf_sha256=fingerprint), recorded_at=journal.utc_now(),
                      revision=1, salt="0" * 64)
            ev["digest"] = journal.event_digest(ev)
            db.execute("INSERT INTO v2_journal VALUES (1,?,?)", (ev["digest"], json.dumps(ev)))
        bundle = timestamps.export_verifiable_log(path, disclose={})
        self.assertTrue(run_browser_verifier(bundle)["ok"])
        self.assertEqual(run_browser_verifier(bundle, self.pdf.read_bytes())["pdfCheck"]["status"], "redacted_target")
        with self.assertRaisesRegex(ValueError, "未披露原文"):
            cli_verifier.verify_bundle(bundle, pdf_file=self.pdf)
        full = timestamps.history(path, export=True)
        self.assertEqual(cli_verifier.verify_bundle(full, pdf_file=self.pdf), (1, []))
        self.assertEqual(run_browser_verifier(full, self.pdf.read_bytes())["pdfCheck"]["status"], "match_local")
