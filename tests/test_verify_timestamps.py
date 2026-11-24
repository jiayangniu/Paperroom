import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_timestamps as verifier
import journal
import timestamps


class OfflineVerificationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        dbpath = self.root / "events.sqlite3"
        db = sqlite3.connect(dbpath)
        with db:
            db.execute("BEGIN")
            for kind in ("paper_outline", "section_outline", "paragraph_outline"):
                journal.append(db, kind, {"question": "未发表的研究数据", "title": "Intro", "sentences": ["未发表的研究数据"]})
        db.close()
        self.bundle = timestamps.history(dbpath, export=True)

    def cli(self, bundle):
        export = self.root / "paperroom-timestamps.json"
        export.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts/verify_timestamps.py"), str(export)],
                              cwd=self.root, text=True, capture_output=True, timeout=15)

    def test_valid_local_export_and_empty_legacy_export(self):
        for bundle, count in [(self.bundle, 3), ({"events": [], "format": "paperroom-timestamps-v1"}, 0)]:
            with self.subTest(count=count):
                result = self.cli(bundle)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"回执覆盖 0 条，仅有本机记录 {count} 条", result.stdout)
                self.assertNotIn("研究数据", result.stdout)

    def test_altered_content_removed_event_and_reordering_fail(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["events"][0]["disclosed"]["question"]["content"] = "替换过的数据"
        result = self.cli(bundle)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("摘要不符", result.stderr)
        self.assertNotIn("替换过的数据", result.stderr)
        for events in (self.bundle["events"][1:], list(reversed(self.bundle["events"]))):
            with self.assertRaisesRegex(ValueError, "顺序"):
                verifier.verify_bundle(dict(self.bundle, events=events))

    def test_receipt_signed_time_coverage_and_verifier_trust(self):
        event = self.bundle["events"][1]
        signed_at = "2026-11-18T03:10:09Z"
        event["receipt"] = dict(authority="tsa.invalid", verified_at=signed_at,
                                query_der_b64="cQ==", reply_der_b64="cg==")
        ca = self.root / "reviewer-trust.pem"
        with patch.object(verifier.tsa, "verify_receipt", return_value=signed_at) as verify:
            self.assertEqual(verifier.verify_bundle(self.bundle, ca), (3, [(2, signed_at)]))
            verify.assert_called_once_with(event["digest"], b"q", b"r", ca_file=ca)
            event["receipt"]["verified_at"] = "2000-01-01T00:00:00Z"
            with self.assertRaisesRegex(ValueError, "签名时间不符"):
                verifier.verify_bundle(self.bundle, ca)
            event["receipt"]["ca_file"] = "sender-chosen-ca.pem"
            with self.assertRaisesRegex(ValueError, "回执格式无效"):
                verifier.verify_bundle(self.bundle, ca)
        del event["receipt"]["ca_file"]
        result = self.cli(self.bundle)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("回执验证失败", result.stderr)
