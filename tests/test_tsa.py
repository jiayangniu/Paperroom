"""Exercise real RFC 3161 signing and trust checks with an isolated test authority."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"))
import tsa


@unittest.skipUnless(shutil.which("openssl"), "needs openssl ts")
class TimestampAuthorityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="local test tsa ")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.ca = cls.root / "ca.pem"
        (cls.root / "config").write_text("""
[req]
distinguished_name = dn
[dn]
[caext]
basicConstraints = critical,CA:true
keyUsage = critical,keyCertSign,cRLSign
[signext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,timeStamping
[tsa]
default_tsa = tsa_config
[tsa_config]
serial = serial.txt
crypto_device = builtin
signer_cert = signer.pem
signer_key = signer.key
certs = ca.pem
signer_digest = sha256
default_policy = 1.2.3.4.5
digests = sha256
ordering = no
tsa_name = yes
ess_cert_id_chain = no
""", encoding="ascii")
        (cls.root / "serial.txt").write_text("01\n", encoding="ascii")
        cls.run_tool("req", "-config", "config", "-new", "-x509", "-newkey", "rsa:2048", "-nodes",
                     "-days", "2", "-keyout", "ca.key", "-out", "ca.pem", "-subj", "/CN=Local CA",
                     "-extensions", "caext")
        cls.run_tool("req", "-config", "config", "-new", "-newkey", "rsa:2048", "-nodes",
                     "-keyout", "signer.key", "-out", "signer.req", "-subj", "/CN=Local Timestamp Authority")
        cls.run_tool("x509", "-req", "-in", "signer.req", "-CA", "ca.pem", "-CAkey", "ca.key",
                     "-set_serial", "2", "-days", "2", "-out", "signer.pem", "-extfile", "config",
                     "-extensions", "signext")

    @classmethod
    def run_tool(cls, *args):
        proc = subprocess.run(["openssl", *args], cwd=cls.root, capture_output=True, timeout=20)
        if proc.returncode:
            raise AssertionError(proc.stderr.decode("utf-8", "replace"))
        return proc.stdout

    def local_signer(self, endpoint, query):
        self.assertEqual(endpoint.hostname, "test.invalid")
        (self.root / "query.tsq").write_bytes(query)
        return self.run_tool("ts", "-reply", "-config", "config", "-queryfile", "query.tsq")

    def test_verify_real_reply_and_reject_substitution(self):
        digest = hashlib.sha256(b"synthetic salted checkpoint").hexdigest()
        with patch.dict(os.environ, {"PAPERROOM_TSA_URL": "https://test.invalid/ts",
                                     "PAPERROOM_TSA_CA_FILE": str(self.ca)}), \
                patch.object(tsa, "_post", side_effect=self.local_signer):
            proof = tsa.stamp(digest)
            other = tsa.stamp(digest)
            self.assertEqual(proof["authority"], "test.invalid")
            self.assertRegex(proof["verified_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$")
            query, token = proof["query_der"], proof["reply_der"]
            self.assertNotEqual(query, other["query_der"])
            self.assertEqual(tsa.verify_receipt(digest, query, token, self.ca), proof["verified_at"])
            for incorrect_digest, request, reply in [
                    ("0"*64, query, token), (digest, other["query_der"], token),
                    (digest, query, token[:120]), (digest, b"", token)]:
                with self.assertRaises(ValueError):
                    tsa.verify_receipt(incorrect_digest, request, reply)
            # An otherwise valid answer signed by an authority outside the trust store.
            with self.assertRaises(ValueError):
                tsa.verify_receipt(digest, query, token, self.root / "signer.pem")

    def test_unconfigured_or_non_https_never_contacts_provider(self):
        for value in ("", "http://test.invalid/tsa", "https://user:pass@test.invalid/tsa",
                      "https://test.invalid:bad/tsa", "https://test.invalid:0/tsa"):
            with patch.dict(os.environ, {"PAPERROOM_TSA_URL": value}), patch.object(tsa, "_post") as send:
                self.assertFalse(tsa.configured())
                with self.assertRaises(ValueError):
                    tsa.stamp("0"*64)
                send.assert_not_called()

    def test_transport_sends_only_query_and_rejects_redirects_and_large_responses(self):
        endpoint = urlsplit("https://test.invalid:8443/witness")
        with patch.object(tsa.http.client, "HTTPSConnection") as connection:
            conn = connection.return_value
            response = Mock(status=200, read1=io.BytesIO(b"receipt").read1)
            conn.getresponse.return_value = response
            self.assertEqual(tsa._post(endpoint, b"query"), b"receipt")
            connection.assert_called_once_with("test.invalid", 8443, timeout=tsa.TIMEOUT)
            conn.request.assert_called_once_with("POST", "/witness", body=b"query", headers={
                "Content-Type": "application/timestamp-query", "Accept": "application/timestamp-reply"})
            conn.close.assert_called_once()
            response.status = 307
            with self.assertRaisesRegex(ValueError, "307"):
                tsa._post(endpoint, b"query")
            response.status = 200
            response.read1 = io.BytesIO(b"x" * (tsa.MAX_REPLY + 1)).read1
            with self.assertRaisesRegex(ValueError, "1 MiB"):
                tsa._post(endpoint, b"query")


if __name__ == "__main__":
    unittest.main()
