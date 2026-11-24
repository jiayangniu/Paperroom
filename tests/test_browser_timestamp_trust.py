"""Check the offline browser's supported timestamp certificate profile and coverage claims."""
import base64
import json
import os
import re
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_verifiable_log as log_fixture
import test_tsa


@unittest.skipUnless(shutil.which("openssl") and shutil.which("node"), "needs OpenSSL and Node WebCrypto")
class BrowserTimestampTrust(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class LocalAuthority(test_tsa.TimestampAuthorityTest):
            pass

        cls.authority = LocalAuthority
        LocalAuthority.setUpClass()
        cls.addClassCleanup(LocalAuthority.doClassCleanups)
        root = LocalAuthority.root
        run = LocalAuthority.run_tool
        run("req", "-config", "config", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", "intermediate.key", "-out", "intermediate.req", "-subj", "/CN=Timestamp CA")
        run("x509", "-req", "-in", "intermediate.req", "-CA", "ca.pem", "-CAkey", "ca.key",
            "-set_serial", "3", "-days", "2", "-out", "intermediate.pem", "-extfile", "config",
            "-extensions", "caext")
        run("x509", "-req", "-in", "signer.req", "-CA", "intermediate.pem", "-CAkey", "intermediate.key",
            "-set_serial", "4", "-days", "2", "-out", "intermediate-signer.pem", "-extfile", "config",
            "-extensions", "signext")
        cls.ca = (root / "ca.pem").read_text()

    def test_browser_enforces_timestamp_authorization_and_path_constraints(self):
        # Exercise parsed, legitimately issued certificates in the actual path validator.
        # Adjust one policy field at a time; no receipt is constructed for these cases.
        code = log_fixture.RUNTIME.joinpath("verify.html").read_text()
        script = re.search(r"<script>([\s\S]*?)</script>", code)[1]
        script = script.replace('if (typeof document === "undefined") return;',
                                'globalThis.checkPath = verifyCertChain; globalThis.oid = decodeOid; return;', 1)
        certs = [self.authority.root.joinpath(name).read_text()
                 for name in ("intermediate-signer.pem", "intermediate.pem", "ca.pem")]
        harness = """
const input = JSON.parse(require("node:fs").readFileSync(0,"utf8"));
globalThis.crypto = require("node:crypto").webcrypto;
require("node:vm").runInThisContext(input.script);
(async () => {
  const [leaf, intermediate, root] = input.certs.map(pem => PaperroomVerifier.parsePemCerts(pem)[0]);
  const run = async (l,i,r) => (await checkPath(l,[i],[r],new Date())).status;
  const results = [await run(leaf, intermediate, root)];
  for (const props of [{eku:null}, {ekuCritical:false}, {eku:[...leaf.eku,"2.5.29.37.0"]},
                       {unsupportedConstraint:true}, {keyUsage:0x04}]) {
    results.push(await run({...leaf,...props}, intermediate, root));
  }
  for (const props of [{isCA:false}, {keyUsage:0x80}, {unsupportedConstraint:true}]) {
    results.push(await run(leaf, {...intermediate,...props}, root));
  }
  results.push(await run(leaf, intermediate, {...root,pathLimit:0}));
  for (const data of [[0x2a,0x80,0x01], [0x2a,0x81]]) {
    try { oid(Uint8Array.from(data)); results.push("accepted"); }
    catch { results.push("invalid"); }
  }
  process.stdout.write(JSON.stringify(results));
})().catch(e=>{ console.error(e); process.exit(1); });
"""
        result = subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True,
                                input=json.dumps({"script": script, "certs": certs}), timeout=15)
        self.assertEqual(json.loads(result.stdout), ["verified"] + ["invalid"] * 11)

    def test_one_valid_receipt_does_not_cover_an_opaque_or_broken_prefix(self):
        old = dict(schema="paperroom.event.v1", seq=1, kind="paper_outline", previous_digest=None,
                   salt="a" * 64, payload={"question": "synthetic"}, recorded_at="2026-01-01T00:00:00.000000Z")
        old["digest"] = log_fixture.journal.event_digest(old)
        old["receipt"] = None
        new = dict(schema="paperroom.event.v2", seq=2, kind="version_saved", previous_digest=old["digest"],
                   summary={"number": 1}, commitments=[], recorded_at="2026-01-02T00:00:00.000000Z")
        new["digest"] = log_fixture.journal.event_digest(new)
        authority = self.authority

        def sign_local(_endpoint, query):
            (authority.root / "coverage.tsq").write_bytes(query)
            return authority.run_tool("ts", "-reply", "-config", "config", "-queryfile", "coverage.tsq")

        with patch.dict(os.environ, {"PAPERROOM_TSA_CA_FILE": str(authority.ca)}), \
                patch.object(log_fixture.tsa, "_post", side_effect=sign_local):
            receipt = log_fixture.tsa.stamp(new["digest"], url="https://test.invalid/")
        new["receipt"] = {
            "authority": "metadata-only.invalid", "verified_at": receipt["verified_at"],
            "query_der_b64": base64.b64encode(receipt["query_der"]).decode(),
            "reply_der_b64": base64.b64encode(receipt["reply_der"]).decode(),
        }

        def check(first, ca):
            return log_fixture.run_browser_verifier({"format": "paperroom-log-v2", "events": [first, new]}, ca_pem=ca)

        valid = check(old, self.ca)
        self.assertEqual((valid["tsaStatus"], valid["coveredSeq"]), ("verified", 2))
        self.assertEqual(valid["latestReceipt"]["receiptCheck"]["authority"], "Local Timestamp Authority")
        self.assertEqual(check(old, None)["coveredSeq"], 0)
        hidden = {key: value for key, value in old.items() if key not in ("payload", "salt")}
        for first in (dict(hidden, redacted_v1=True), dict(old, payload={"question": "mismatched"})):
            with self.subTest(redacted=bool(first.get("redacted_v1"))):
                result = check(first, self.ca)
                self.assertEqual((result["tsaStatus"], result["coveredSeq"]), ("unverified_prefix", 0))
                self.assertEqual(result["events"][1]["receiptCheck"]["status"], "verified")
