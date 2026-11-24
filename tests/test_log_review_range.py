"""Submission exports include the selected version's review without changing its seal."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"))
import journal
import timestamps


class SubmissionLogRange(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name).resolve() / "project.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)

    def action(self, kind, payload, revision=None):
        with self.db:
            self.db.execute("BEGIN")
            return journal.append(self.db, kind, payload, revision=revision)

    def test_version_includes_its_review_and_stops_before_next_draft(self):
        saved = self.action("version_saved", {"number": 1, "pdf_sha256": "a" * 64}, revision=1)
        self.action("section_hint", {"text": "Intervening reference."})
        reviewed = self.action("version_reviewed", {
            "number": 1, "notes": [{"kind": "change", "text": "Qualify this claim."}],
            "approved": False,
        }, revision=1)
        self.action("paper_hint", {"text": "Later drafting."})
        self.action("version_saved", {"number": 2, "pdf_sha256": "b" * 64}, revision=2)
        approved = self.action("version_reviewed", {"number": 2, "notes": [], "approved": True},
                               revision=2)
        self.action("paper_hint", {"text": "Work after final approval."})

        options = timestamps.disclosable_items(self.path, target_version=1)
        self.assertEqual([e["seq"] for e in options["events"]], [2, reviewed["seq"]])
        log = timestamps.export_verifiable_log(self.path, target_version=1,
                                               disclose={reviewed["seq"]: ["note_1"]})
        self.assertEqual(log["target_version"]["event_seq"], saved["seq"])
        self.assertEqual([e["seq"] for e in log["events"]], [1, 2, 3])
        last = log["events"][-1]
        self.assertEqual(last["previous_digest"], log["events"][-2]["digest"])
        self.assertEqual(last["disclosed"]["note_1"]["content"]["text"], "Qualify this claim.")
        self.assertIsNone(last["receipt"])
        self.assertNotIn("Later drafting.", json.dumps(log))

        latest = timestamps.export_verifiable_log(self.path, target_version=2)
        self.assertEqual(latest["events"][-1]["digest"], approved["digest"])
        self.assertTrue(latest["events"][-1]["summary"]["approved"])
        full = timestamps.export_verifiable_log(self.path)
        self.assertEqual(full["target_version"]["number"], 2)
        self.assertEqual(len(full["events"]), 7)

    def test_unreviewed_version_keeps_save_as_endpoint(self):
        self.action("version_saved", {"number": 1, "pdf_sha256": "a" * 64}, revision=1)
        self.action("paper_hint", {"text": "Work in progress."})
        log = timestamps.export_verifiable_log(self.path, target_version=1)
        self.assertEqual(len(log["events"]), 1)
        self.assertEqual(timestamps.disclosable_items(self.path, target_version=1)["events"], [])

    def test_legacy_v0_origin_and_review_survive_selective_disclosure(self):
        with self.db:
            self.db.execute("CREATE TABLE v2_journal (seq INTEGER PRIMARY KEY, digest TEXT, event TEXT)")
            previous = None
            for seq, (kind, payload) in enumerate((
                    ("version_saved", {"number": 0, "kind": "original", "pdf_sha256": "a" * 64}),
                    ("version_reviewed", {"number": 0, "notes": [], "approved": True}),
            ), start=1):
                event = dict(schema="paperroom.event.v1", seq=seq, kind=kind, revision=0,
                             recorded_at=journal.utc_now(), previous_digest=previous,
                             salt="a" * 64, payload=payload)
                event["digest"] = previous = journal.event_digest(event)
                self.db.execute("INSERT INTO v2_journal VALUES (?, ?, ?)", (seq, previous, json.dumps(event)))
        self.action("version_saved", {"number": 1, "pdf_sha256": "b" * 64}, revision=1)
        options = timestamps.disclosable_items(self.path, target_version=0)
        self.assertEqual([e["seq"] for e in options["events"]], [1, 2])
        for disclose in ({}, {1: ["__v1_payload__"], 2: ["__v1_payload__"]}):
            with self.subTest(disclose=disclose):
                log = timestamps.export_verifiable_log(self.path, target_version=0, disclose=disclose)
                self.assertTrue(log["origin"]["started_with_existing_manuscript"])
                self.assertEqual(log["target_version"]["event_seq"], 1)
                self.assertEqual([e["kind"] for e in log["events"]], ["version_saved", "version_reviewed"])
