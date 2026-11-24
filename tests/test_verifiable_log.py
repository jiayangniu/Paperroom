"""End-to-end acceptance tests for the verifiable writing log feature."""
import copy
import hashlib
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import archives
import journal
import outline
import paperroom
import section_review
import timestamps
import tsa
import versions
import verify_timestamps as cli_verifier
import workspace_server
from test_tsa import TimestampAuthorityTest


def run_browser_verifier(bundle, pdf_bytes=None, ca_pem=None, selected_seq=None):
    """Run the exact inline verification engine from verify.html in Node.js (real WebCrypto)."""
    html = (RUNTIME / "verify.html").read_text(encoding="utf-8")
    match = re.search(r"<script>([\s\S]*?)</script>", html)
    assert match, "verify.html missing inline script"
    script = match.group(1)
    harness = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const webcrypto = require("node:crypto").webcrypto;
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const ctx = {
  crypto: webcrypto,
  TextEncoder, TextDecoder, Uint8Array, ArrayBuffer, DataView,
  atob: s => Buffer.from(s, "base64").toString("binary"),
  btoa: s => Buffer.from(s, "binary").toString("base64"),
  Date, Math, Number, String, Array, Object, Set, Map, JSON, Error, RegExp, console,
};
ctx.globalThis = ctx;
vm.runInNewContext(input.script, ctx);
(async () => {
  const pdf = input.pdf_b64 ? Uint8Array.from(Buffer.from(input.pdf_b64, "base64")).buffer : null;
  const cas = input.ca_pem ? [input.ca_pem] : [];
  const bundle = ctx.PaperroomVerifier.parseLogJson(input.bundle_json);
  const res = await ctx.PaperroomVerifier.verifyBundle(bundle, pdf, cas, input.selected_seq);
  process.stdout.write(JSON.stringify(res));
})().catch(err => { console.error(err); process.exit(1); });
"""
    import base64
    payload = {
        "script": script,
        "bundle_json": bundle if isinstance(bundle, str) else json.dumps(bundle, ensure_ascii=False, allow_nan=False),
        "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii") if pdf_bytes is not None else None,
        "ca_pem": ca_pem,
        "selected_seq": selected_seq,
    }
    proc = subprocess.run(["node", "-e", harness], input=json.dumps(payload),
                          text=True, capture_output=True, timeout=30)
    if proc.returncode != 0:
        raise AssertionError(f"Browser verifier failed: {proc.stderr}")
    return json.loads(proc.stdout)


@unittest.skipUnless(shutil.which("openssl") and shutil.which("node"), "Needs openssl and node.")
class VerifiableWritingLogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TimestampAuthorityTest.setUpClass()
        cls.tsa_ca = TimestampAuthorityTest.ca
        cls.tsa_ca_pem = cls.tsa_ca.read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        TimestampAuthorityTest.doClassCleanups()

    def local_signer(self, endpoint, query):
        (TimestampAuthorityTest.root / "query.tsq").write_bytes(query)
        return TimestampAuthorityTest.run_tool("ts", "-reply", "-config", "config", "-queryfile", "query.tsq")

    def _make_synthetic_project(self):
        folder = tempfile.TemporaryDirectory(prefix="paperroom-vlog-")
        self.addCleanup(folder.cleanup)
        project = Path(folder.name).resolve() / "synth-paper"
        project.mkdir()
        (project / "main.tex").write_text(
            "\\documentclass{article}\n\\begin{document}\n"
            "\\section{Method}\nInitial paragraph text.\n\\end{document}\n",
            encoding="utf-8",
        )
        return project

    def test_full_acceptance_auto_seal_selective_disclosure_and_tamper_detection(self):
        project = self._make_synthetic_project()
        db_path = workspace_server.database_path(project)
        pdf_v1 = b"%PDF-1.4 synthetic-v1-bytes-0001"
        pdf_v2 = b"%PDF-1.4 synthetic-v2-bytes-0002"
        page_png = (ROOT / "demo/examples/intro.png").read_bytes()

        with closing(paperroom.connect(db_path)) as db:
            state = outline.update_assets(db, project, 0, "Research Q?", "Measured data.")
            state = outline.submit(db, project, state["version"], "paper", [
                {"title": "Method", "purpose": "Explain the approach."},
            ])
            sec = state["sections"][0]["id"]
            state = outline.submit(db, project, state["version"], "section", [
                {"purpose": "Define the core step."},
            ], section=sec)
            pid = state["sections"][0]["paragraphs"][0]["id"]
            state = outline.submit(db, project, state["version"], "paragraph", [
                "Introduce the noiseless ranking.",
                "Contrast with noisy evaluation.",
            ], section=sec, paragraph=pid)
            section_review.save_paragraph_draft(db, project, sec, pid, 1)

            # Turn on project-level auto-sealing pointing to our isolated test TSA.
            timestamps.update_settings(db_path, {"auto_seal": True, "tsa_url": "https://test.invalid/ts"})

            # Save V1 while online -> auto-sealed immediately.
            fake_compile_v1 = {
                "pdf": pdf_v1, "images": [page_png], "map": {sec: {"title": "Method", "page": 1, "paragraphs": {pid: 1}}},
                "texts": {sec: ["Draft v1"]}, "built": "paperroom", "main": "main.tex",
                "source_sha256": hashlib.sha256(b"src1").hexdigest(), "sources": {}, "lines": [], "found": [],
            }
            with patch.object(versions, "_compile", return_value=fake_compile_v1), \
                    patch.dict(os.environ, {"PAPERROOM_TSA_CA_FILE": str(self.tsa_ca)}), \
                    patch.object(tsa, "_post", side_effect=self.local_signer):
                v1 = versions.save(db, project, label="First draft")
            self.assertEqual(v1["seal"]["status"], "sealed")

            # Author reviews V1 with two notes: one to disclose, one to keep private.
            versions.submit_review(db, 1, [
                {"kind": "change", "page": 1, "section": sec, "paragraph": pid,
                 "text": "这句话把模拟器上的结果推广到了真实设备，请收窄结论。"},
                {"kind": "keep", "page": 1, "section": sec, "paragraph": pid,
                 "text": "PRIVATE_NOTE_DO_NOT_LEAK_9988"},
            ])

            # Save V2 while offline -> saves smoothly and records pending seal.
            fake_compile_v2 = {
                "pdf": pdf_v2, "images": [page_png], "map": {sec: {"title": "Method", "page": 1, "paragraphs": {pid: 1}}},
                "texts": {sec: ["Draft v2 narrowed"]}, "built": "paperroom", "main": "main.tex",
                "source_sha256": hashlib.sha256(b"src2").hexdigest(), "sources": {}, "lines": [], "found": [],
            }
            with patch.object(versions, "_compile", return_value=fake_compile_v2), \
                    patch.object(tsa, "_post", side_effect=OSError("offline")):
                v2 = versions.save(db, project, expected=1, label="Submission", responses=[
                    {"note": 1, "status": "changed", "text": "已将结论限定在 6–8 比特精确模拟范围内。"},
                    {"note": 2, "status": "kept", "text": "PRIVATE_RESPONSE_DO_NOT_LEAK_7766"},
                ])
            self.assertEqual(v2["seal"]["status"], "pending")
            hist = timestamps.history(db_path)
            self.assertEqual(hist["pending_count"], 1)

            # Back online -> seal pending succeeds.
            with patch.dict(os.environ, {"PAPERROOM_TSA_CA_FILE": str(self.tsa_ca)}), \
                    patch.object(tsa, "_post", side_effect=self.local_signer):
                sealed = timestamps.seal_pending(db_path)
            self.assertEqual(sealed["sealed_now"], 1)
            self.assertEqual(sealed["remaining_pending"], 0)

            # Cleanup V1 locally; V2 becomes display V1, yet V1's historical seal & PDF hash remain intact.
            versions.cleanup(db, [1], [1, 2], [2, 0])

        # Inspect disclosable items and select ONLY note_1 and response_1.
        disc = timestamps.disclosable_items(db_path, target_version=2)
        review_ev = next(e for e in disc["events"] if e["kind"] == "version_reviewed")
        v2_ev = next(e for e in disc["events"] if e["kind"] == "version_saved" and e["revision"] == 2)
        disclose_map = {str(review_ev["seq"]): ["note_1"], str(v2_ev["seq"]): ["response_1"]}

        bundle = timestamps.export_verifiable_log(db_path, project_name="synth-paper",
                                                  target_version=2, disclose=disclose_map)
        raw_json = json.dumps(bundle, ensure_ascii=False)

        # Acceptance #4: Privacy — undisclosed text must NOT appear anywhere in exported JSON.
        self.assertIn("这句话把模拟器上的结果推广到了真实设备", raw_json)
        self.assertIn("已将结论限定在 6–8 比特精确模拟范围内", raw_json)
        self.assertNotIn("PRIVATE_NOTE_DO_NOT_LEAK_9988", raw_json)
        self.assertNotIn("PRIVATE_RESPONSE_DO_NOT_LEAK_7766", raw_json)
        self.assertNotIn("Introduce the noiseless ranking.", raw_json)

        # Acceptance #1: Normal pass (CLI + Browser verifier with real RFC 3161 + PDF match).
        pdf_file = project / "submitted.pdf"
        pdf_file.write_bytes(pdf_v2)
        count, receipts = cli_verifier.verify_bundle(bundle, ca_file=self.tsa_ca, pdf_file=pdf_file)
        self.assertEqual(count, len(bundle["events"]))
        self.assertEqual(len(receipts), 2)

        browser_ok = run_browser_verifier(bundle, pdf_bytes=pdf_v2, ca_pem=self.tsa_ca_pem)
        self.assertTrue(browser_ok["ok"], browser_ok["errors"])
        self.assertTrue(browser_ok["chainValid"])
        self.assertEqual(browser_ok["tsaStatus"], "verified")
        self.assertEqual(browser_ok["coveredSeq"], v2_ev["seq"])
        self.assertEqual(browser_ok["pdfCheck"]["status"], "match")

        # Without custom CA, browser verifier distinguishes "untrusted_ca" from "invalid".
        browser_untrusted = run_browser_verifier(bundle, pdf_bytes=pdf_v2, ca_pem=None)
        self.assertEqual(browser_untrusted["tsaStatus"], "untrusted_ca")
        self.assertTrue(browser_untrusted["chainValid"])
        self.assertEqual(browser_untrusted["pdfCheck"]["status"], "match_local")

        # V2's receipt also binds the original V1 save even without V1's own receipt.
        later_receipt = copy.deepcopy(bundle)
        v1_event = next(e for e in later_receipt["events"] if e["kind"] == "version_saved" and e["revision"] == 1)
        v1_event["receipt"] = None
        earlier = run_browser_verifier(later_receipt, pdf_v1, self.tsa_ca_pem, selected_seq=v1_event["seq"])
        self.assertEqual(earlier["pdfCheck"]["status"], "match")
        self.assertTrue(earlier["pdfCheck"]["target"]["sealed"])

        # Acceptance #3: Log only (no PDF) -> readable & valid, pdfCheck unchecked.
        browser_log_only = run_browser_verifier(bundle, pdf_bytes=None, ca_pem=self.tsa_ca_pem)
        self.assertTrue(browser_log_only["ok"])
        self.assertEqual(browser_log_only["pdfCheck"]["status"], "unchecked")

        # Acceptance #2a: Substituted PDF -> fails PDF check specifically.
        browser_wrong_pdf = run_browser_verifier(bundle, pdf_bytes=b"%PDF-1.4 tampered-pdf", ca_pem=self.tsa_ca_pem)
        self.assertFalse(browser_wrong_pdf["ok"])
        self.assertTrue(browser_wrong_pdf["chainValid"])
        self.assertEqual(browser_wrong_pdf["tsaStatus"], "verified")
        self.assertEqual(browser_wrong_pdf["pdfCheck"]["status"], "mismatch")

        # Acceptance #2b: Tampered disclosed note -> fails chainValid specifically.
        tampered_note = copy.deepcopy(bundle)
        rev_item = next(e for e in tampered_note["events"] if e["seq"] == review_ev["seq"])
        rev_item["disclosed"]["note_1"]["content"]["text"] = "被事后改写过的批注"
        browser_bad_note = run_browser_verifier(tampered_note, pdf_bytes=pdf_v2, ca_pem=self.tsa_ca_pem)
        self.assertFalse(browser_bad_note["ok"])
        self.assertFalse(browser_bad_note["chainValid"])
        with self.assertRaisesRegex(ValueError, "公开原文与摘要不符"):
            cli_verifier.verify_bundle(tampered_note, ca_file=self.tsa_ca)

        # Acceptance #2c: Deleted middle sealed event -> fails chainValid.
        deleted_ev = copy.deepcopy(bundle)
        del deleted_ev["events"][2]
        browser_deleted = run_browser_verifier(deleted_ev, pdf_bytes=pdf_v2, ca_pem=self.tsa_ca_pem)
        self.assertFalse(browser_deleted["ok"])
        self.assertFalse(browser_deleted["chainValid"])
        with self.assertRaisesRegex(ValueError, "顺序"):
            cli_verifier.verify_bundle(deleted_ev, ca_file=self.tsa_ca)

        # Acceptance: V1 (cleaned locally) can still be verified against original PDF bytes.
        v1_bundle = timestamps.export_verifiable_log(db_path, project_name="synth-paper", target_version=1)
        browser_v1 = run_browser_verifier(v1_bundle, pdf_bytes=pdf_v1, ca_pem=self.tsa_ca_pem)
        self.assertTrue(browser_v1["ok"], browser_v1["errors"])
        self.assertEqual(browser_v1["pdfCheck"]["status"], "match")

    def test_archive_restore_logs_checkpoint_event_and_http_routes_work(self):
        project = self._make_synthetic_project()
        db_path = workspace_server.database_path(project)
        with closing(paperroom.connect(db_path)) as db:
            state = outline.update_assets(db, project, 0, "Q", "E")
            outline.submit(db, project, state["version"], "paper", [{"title": "Intro", "purpose": "Set context"}])
        snap = archives.create(project, "Before rewrite", request_id=secrets.token_hex(16), expected_generation="")
        archives.switch(project, snap["created"], "Leaving", request_id=secrets.token_hex(16), expected_generation="")
        hist = timestamps.history(db_path)
        self.assertEqual(hist["events"][-1]["kind"], "checkpoint_restored")
        self.assertNotIn("commit", hist["events"][-1]["summary"])
        self.assertEqual(timestamps.disclosable_items(db_path)["events"][-1]["items"][0]["content"],
                         "Before rewrite")

        token = secrets.token_urlsafe(16)
        handler = workspace_server.handler_for(db_path, token, project)
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                # /verify serves standalone HTML
                with urllib.request.urlopen(base + "/verify", timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertIn("PaperroomVerifier", resp.read().decode("utf-8"))
                # POST /api/timestamps/settings
                gen = archives.generation(project)
                req = urllib.request.Request(
                    base + "/api/timestamps/settings",
                    data=json.dumps({"auto_seal": True, "tsa_url": "https://timestamp.digicert.com"}).encode(),
                    headers={"Content-Type": "application/json", "Origin": base,
                             "X-Paperroom-Token": token, "X-Paperroom-Generation": gen},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    updated = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(updated["auto_seal"])
                self.assertEqual(updated["authority"], "timestamp.digicert.com")
                # POST /api/timestamps/export-log (preview)
                req2 = urllib.request.Request(
                    base + "/api/timestamps/export-log",
                    data=json.dumps({"target_version": None, "disclose": {}, "preview": True}).encode(),
                    headers={"Content-Type": "application/json", "Origin": base,
                             "X-Paperroom-Token": token, "X-Paperroom-Generation": gen},
                    method="POST",
                )
                with urllib.request.urlopen(req2, timeout=5) as resp:
                    preview = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(preview["format"], "paperroom-log-v2")
                self.assertEqual(preview["events"][-1]["kind"], "checkpoint_restored")
            finally:
                server.shutdown()

    def test_legacy_v1_events_remain_compatible(self):
        project = self._make_synthetic_project()
        db_path = workspace_server.database_path(project)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute("CREATE TABLE v2_journal (seq INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, event TEXT NOT NULL)")
            v1_ev = {
                "schema": "paperroom.event.v1",
                "seq": 1,
                "kind": "paper_outline",
                "recorded_at": "2026-11-18T00:00:00.000000Z",
                "previous_digest": None,
                "salt": "a" * 64,
                "payload": {"question": "Legacy Q", "sections": [{"id": "s1", "title": "Intro", "purpose": "P"}]},
            }
            v1_ev["digest"] = journal.event_digest(v1_ev)
            db.execute("INSERT INTO v2_journal VALUES (?,?,?)", (1, v1_ev["digest"], journal.canonical_json(v1_ev)))
            # Append a v2 event right after the legacy v1 event (mixed chain!).
            journal.append(db, "versions_cleaned", {"removed": [1], "order_before": [1, 2]})

        # Redacted v1 export -> explicitly marked redacted_v1 and verified without leaking Legacy Q.
        redacted_bundle = timestamps.export_verifiable_log(db_path, project_name="legacy", disclose={})
        self.assertNotIn("Legacy Q", json.dumps(redacted_bundle))
        self.assertTrue(redacted_bundle["events"][0]["redacted_v1"])
        res_redacted = run_browser_verifier(redacted_bundle)
        self.assertTrue(res_redacted["chainValid"])
        self.assertTrue(res_redacted["hasRedactedV1"])

        # Disclosed v1 export -> full digest verified.
        full_bundle = timestamps.export_verifiable_log(db_path, project_name="legacy", disclose={"1": ["__v1_payload__"]})
        res_full = run_browser_verifier(full_bundle)
        self.assertTrue(res_full["chainValid"])
        self.assertFalse(res_full["hasRedactedV1"])
        cli_verifier.verify_bundle(full_bundle)


if __name__ == "__main__":
    unittest.main()
