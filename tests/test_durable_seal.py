"""An automatic timestamp request survives interruption at the version commit boundary."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import timestamps
import versions


class DurableVersionSeal(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name).resolve()
        self.path = self.project / "project.sqlite3"
        self.settings(True)
        mock_compile = patch.object(versions, "_compile", return_value={
            "pdf": b"%PDF-example", "images": [b"page"], "main": "main.tex",
            "map": {}, "texts": {}, "source_sha256": "source", "found": [], "lines": [],
        })
        self.compile = mock_compile.start()
        self.addCleanup(mock_compile.stop)
        self.receipt = {"authority": "local.example", "verified_at": "2026-11-24T00:00:00Z",
                        "query_der": b"query", "reply_der": b"reply"}
        mock_stamp = patch.object(timestamps.tsa, "stamp", return_value=self.receipt)
        self.stamp = mock_stamp.start()
        self.addCleanup(mock_stamp.stop)

    def settings(self, enabled):
        timestamps.update_settings(self.path, {"auto_seal": enabled, "tsa_url": "https://local.example/tsa"})

    def save(self):
        with closing(sqlite3.connect(self.path)) as db:
            return versions.save(db, self.project)

    def test_interrupt_reopen_and_retry_same_version_once(self):
        def interrupt(digest, **kwargs):
            history = timestamps.history(self.path)
            event, = history["events"]
            self.assertEqual(event["digest"], digest)
            self.assertEqual(history["pending_count"], 1)
            self.assertEqual(len(history["versions"]), 1)
            raise SystemExit

        self.stamp.side_effect = interrupt
        with self.assertRaises(SystemExit):
            self.save()
        self.stamp.side_effect = None
        saved = self.save()
        self.assertEqual(saved["seal"]["status"], "sealed")
        self.assertEqual(self.save(), saved)
        self.assertEqual(self.stamp.call_count, 2)
        self.assertEqual(timestamps.history(self.path)["pending_count"], 0)
        self.assertEqual(timestamps.seal_pending(self.path)["sealed_now"], 0)
        self.assertEqual(len(timestamps.history(self.path)["events"]), 1)

    def test_outer_rollback_never_sends_or_leaves_a_pending_job(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("BEGIN IMMEDIATE")
            saved = versions.save(db, self.project)
            self.assertEqual(saved["seal"]["status"], "pending")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM v2_timestamp_pending").fetchone()[0], 1)
            self.assertEqual(timestamps.history(self.path)["events"], [])
            db.rollback()
        self.stamp.assert_not_called()
        history = timestamps.history(self.path)
        self.assertEqual((history["versions"], history["pending_count"]), ([], 0))

    def test_freezing_original_schedules_the_same_durable_job(self):
        self.stamp.side_effect = SystemExit
        with closing(sqlite3.connect(self.path)) as db:
            with patch.object(versions, "_located_sections", return_value=("main.tex", [], [({}, 0, 1)])), \
                    patch.object(versions.L, "paragraphs", return_value=[{"text": "original"}]), \
                    self.assertRaises(SystemExit):
                versions.freeze_original(db, self.project)
        history = timestamps.history(self.path)
        self.assertEqual(history["versions"][0]["number"], 0)
        self.assertEqual(history["pending_count"], 1)
        self.stamp.side_effect = None
        self.assertEqual(timestamps.seal_pending(self.path)["sealed_now"], 1)

    def test_no_retroactive_stamp_or_job_for_a_version_without_pdf(self):
        self.settings(False)
        self.assertNotIn("seal", self.save())
        self.settings(True)
        self.assertNotIn("seal", self.save())
        self.compile.return_value.update(pdf=None, source_sha256="version without PDF")
        self.assertNotIn("seal", self.save())
        self.stamp.assert_not_called()
        self.assertEqual(timestamps.history(self.path)["pending_count"], 0)

    def test_older_unqueued_save_can_still_request_a_receipt_explicitly(self):
        self.settings(False)
        self.save()
        self.settings(True)
        event, = timestamps.history(self.path)["events"]
        self.assertIsNone(event["pending_seal"])
        self.assertEqual(timestamps.seal_pending(self.path)["sealed_now"], 0)
        request = {"seq": event["seq"], "digest": event["digest"]}
        with_receipt = timestamps.request_receipt(self.path, request)
        self.assertEqual(with_receipt["events"][0]["receipt"]["authority"], "local.example")
        self.assertEqual(self.save()["seal"]["status"], "sealed")
        self.stamp.assert_called_once()

    def test_failed_worker_cannot_requeue_an_already_sealed_digest(self):
        def finish_elsewhere_then_fail(digest, **kwargs):
            event, = timestamps.history(self.path)["events"]
            timestamps._store_receipt(self.path, event["seq"], digest, self.receipt)
            raise OSError("connection closed")

        self.stamp.side_effect = finish_elsewhere_then_fail
        self.assertEqual(self.save()["seal"]["status"], "sealed")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM v2_timestamp_pending").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM timestamp_receipts").fetchone()[0], 1)
