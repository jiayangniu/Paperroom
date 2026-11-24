"""The standalone reader must hash the same JSON numbers as the Python journal."""
import copy
from contextlib import closing
import json
import shutil
import sqlite3
import unittest

from test_verifiable_log import cli_verifier, journal, run_browser_verifier, versions


@unittest.skipUnless(shutil.which("node"), "needs Node.js for the standalone WebCrypto verifier")
class NumericCommitments(unittest.TestCase):
    def verify_both(self, bundle):
        cli_verifier.verify_bundle(bundle)
        result = run_browser_verifier(bundle)
        self.assertTrue(result["chainValid"], result["errors"])

    def test_disclosing_a_real_pin_on_the_page_edge(self):
        notes = versions._validate_notes({"pages": 1}, [
            {"kind": "change", "page": 1, "text": "Clarify the left axis.", "pin": {"x": 0, "y": 1}},
            {"kind": "keep", "page": 1, "text": "Keep the inset.", "pin": {"x": 1e-7, "y": 0.5}},
        ], False)
        with closing(sqlite3.connect(":memory:")) as db, db:
            db.execute("BEGIN")
            journal.append(db, "version_reviewed", {"number": 1, "notes": notes, "approved": False})
            events = journal.export_events(db, include_secrets=False, disclose={1: ["note_1", "note_2"]})
        bundle = {"format": "paperroom-log-v2", "events": [dict(e, receipt=None) for e in events]}
        self.verify_both(bundle)

        changed = copy.deepcopy(bundle)
        changed["events"][0]["disclosed"]["note_1"]["content"]["pin"]["x"] = 0.02
        self.assertFalse(run_browser_verifier(changed)["chainValid"])
        with self.assertRaises(ValueError):
            cli_verifier.verify_bundle(changed)

    def test_full_legacy_record_preserves_python_types_and_numeric_precision(self):
        event = {
            "schema": "paperroom.event.v1", "seq": 1, "kind": "version_reviewed",
            "recorded_at": "2026-01-01T00:00:00.000000Z", "previous_digest": None, "salt": "55" * 32,
            "payload": {
                "values": [0, 0.0, -0.0, 1.0, 0.0001, 1e-5, 1e-7, 1e15, 1e16, 1e100, 5e-324,
                           (1 << 53) + 1, 10**35 + 31],
                "labels": ['"x": 1e-05', "保留 0.0"],
            },
        }
        event["digest"] = journal.event_digest(event)
        bundle = {"format": "paperroom-timestamps-v1", "events": [dict(event, receipt=None)]}
        self.verify_both(bundle)
        # Reformatting a float with exponent notation does not change its value or type.
        wire = json.dumps(bundle).replace("1e-05,", "0.0000100,")
        self.assertTrue(run_browser_verifier(wire)["chainValid"])

        # Integers and floats were different records when hashed by Python.
        bundle["events"][0]["payload"]["values"][1] = 0
        self.assertFalse(run_browser_verifier(bundle)["chainValid"])

    def test_duplicate_keys_are_rejected_when_reading_the_original_file(self):
        with self.assertRaisesRegex(AssertionError, "Duplicate JSON key"):
            run_browser_verifier('{"format":"paperroom-log-v2","events":[],"events":[]}')
