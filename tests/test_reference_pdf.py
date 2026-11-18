"""A reference PDF is readable before a paragraph is authorized for drafting."""
import http.client
import json
from pathlib import Path
import shutil
import socket
import struct
import threading
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import outline
import paperroom
import section_review as review
import workspace_server as web


def two_page_pdf():
    # Different page dimensions let us verify both the content and the order.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Resources << >> >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 300] /Resources << >> >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(b"xref\n0 5\n0000000000 65535 f \n")
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(pdf)


class ReferencePDFTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = Path(folder.name)
        self.db = paperroom.connect(web.database_path(self.project))
        self.addCleanup(self.db.close)
        outline.update_assets(self.db, self.project, 0, "Why?", "Data")
        self.section = outline.submit(self.db, self.project, 1, "paper", [
            {"title": "Intro", "purpose": "Motivate"}, {"title": "Results", "purpose": "Test"}
        ])["sections"][0]["id"]

    def test_reference_permissions_dedup_and_archive(self):
        pdf = two_page_pdf()
        with patch.object(paperroom, "render_document", return_value=(pdf, [b"png"])):
            for title in ("Original", "Revision", "Original"):
                view = review.import_reference(self.db, self.project, self.section, title=title, upload=pdf)
        self.assertEqual([d["id"] for d in view["documents"]], ["ref-1", "ref-2"])
        self.assertEqual(view["reference_id"], "ref-1")
        self.assertEqual(view["phase"], "outlining")
        self.assertFalse(view["drafts"] or view["revisions"])
        with self.assertRaises(ValueError):
            review.publish_section(self.db, self.project, self.section)
        self.assertIsNone(review.document_asset(self.db, self.section, "rev", 1))
        state = outline.state(self.db, self.project)
        other = state["sections"][1]
        outline.submit(self.db, self.project, state["version"], "paper", [other])
        state = web.snapshot(self.db, self.project, self.section)
        self.assertEqual(state["archived"][0]["title"], "Intro")
        self.assertEqual(state["review"]["documents"][0]["title"], "Original")
        self.assertEqual(review.document_asset(self.db, self.section, "ref", 1), pdf)
        self.assertEqual(review.document_asset(self.db, self.section, "ref", 1, 1), b"png")

    def test_legacy_editions_offer_only_existing_page_images(self):
        review._create_tables(self.db)
        edition = dict(title="Intro", revision=1, pages=1, created="2025", reviewed=None)
        with self.db:
            self.db.execute("INSERT INTO v2_editions VALUES (?,?,?)", (self.section, 1, json.dumps(edition)))
            self.db.execute("INSERT INTO v2_pages VALUES (?,?,?,?)", (self.section, 1, 1, b"png"))
        doc = review.status(self.db, self.project, self.section)["documents"][0]
        self.assertIsNone(doc["pdf_url"])
        self.assertEqual(review.document_asset(self.db, self.section, "rev", 1, 1), b"png")

    @unittest.skipUnless(sys.platform == "darwin" or all(shutil.which(k) for k in
                         ("pdftoppm", "pdfinfo", "pdfseparate", "pdfunite")), "Requires PDFKit or Poppler")
    def test_downloaded_pdf_is_the_requested_excerpt(self):
        path = self.project / "original.pdf"
        path.write_bytes(two_page_pdf())
        data = web.author_action(self.db, self.project, dict(action="reference", section=self.section,
                                                              pdf="original.pdf", pages="2"))
        self.assertEqual(data["review"]["documents"][0]["pages"], 1)
        frozen = review.document_asset(self.db, self.section, "ref", 1)
        self.assertTrue(frozen.startswith(b"%PDF-"))
        path.write_bytes(frozen)
        _, pages = paperroom.render_document(None, path, "all")
        self.assertEqual(len(pages), 1)
        width, height = struct.unpack(">II", pages[0][16:24])
        self.assertLess(width, height)
        with self.assertRaises(ValueError):
            review.import_reference(self.db, self.project, self.section, pdf=path, pages="2")
        self.assertEqual(len(review.status(self.db, self.project, self.section)["documents"]), 1)

    def http(self, method, url, body=b"", token="token", mime="application/pdf"):
        handler = web.handler_for(web.database_path(self.project), "token", self.project)
        client, server = socket.socketpair()
        with client, server:
            context = type("LocalServer", (), {"server_port": 8765})()
            thread = threading.Thread(target=handler, args=(server, ("127.0.0.1", 9000), context))
            thread.start()
            header = (f"{method} {url} HTTP/1.0\r\nHost: localhost:8765\r\nOrigin: http://localhost:8765\r\n"
                      f"X-Paperroom-Token: {token}\r\nContent-Type: {mime}\r\nContent-Length: {len(body)}\r\n\r\n")
            client.sendall(header.encode() + body)
            response = http.client.HTTPResponse(client)
            response.begin()
            status, mime, result = response.status, response.getheader("Content-Type"), response.read()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            return status, mime, result

    def test_upload_and_download_routes_require_correct_resource_and_scope(self):
        url = f"/api/sections/{self.section}/references?title=Original&pages=1"
        pdf = two_page_pdf()
        self.assertEqual(self.http("POST", url, pdf, token="wrong")[0], 403)
        self.assertEqual(self.http("POST", url, pdf, mime="text/plain")[0], 415)
        with patch.object(paperroom, "render_document", return_value=(pdf, [b"page image"])):
            status, _, body = self.http("POST", url, pdf)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["reference_id"], "ref-1")
        doc = json.loads(body)["review"]["documents"][0]
        self.assertEqual(self.http("GET", doc["pdf_url"]), (200, "application/pdf", pdf))
        self.assertEqual(self.http("GET", doc["page_url"] + "1"), (200, "image/png", b"page image"))
        self.assertEqual(self.http("GET", doc["pdf_url"].replace("ref-1", "rev-1"))[0], 404)
        self.assertEqual(self.http("GET", doc["page_url"] + "2")[0], 404)

    def test_bad_upload_and_outside_path(self):
        with self.assertRaisesRegex(ValueError, "PDF"):
            review.import_reference(self.db, self.project, self.section, upload=b"not a PDF")
        outside = ROOT / "demo/examples/intro.pdf"
        with self.assertRaises(ValueError):
            review.import_reference(self.db, self.project, self.section, pdf=outside)


class IncludeBuildTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pdftoppm") or sys.platform == "darwin", "Needs a page renderer.")
    def test_pdflatex_output_folder_has_include_directories(self):
        # pdfLaTeX writes sections/method.aux inside -output-directory for \\include.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tools, paper = root / "bin", root / "paper"
            tools.mkdir(); (paper / "sections").mkdir(parents=True)
            (paper / "sections/method.tex").write_text("Method.\n")
            main = paper / "main.tex"
            main.write_text("\\documentclass{article}\\begin{document}\\include{sections/method}\\end{document}\n")
            (root / "page.pdf").write_bytes(two_page_pdf())
            fake = tools / "pdflatex"
            fake.write_text("#!" + sys.executable + "\n"
                            "import shutil, sys\nfrom pathlib import Path\n"
                            "out = Path(next(a.split('=', 1)[1] for a in sys.argv if a.startswith('-output-directory=')))\n"
                            "if not (out / 'sections').is_dir():\n"
                            "    sys.exit(\"I can't write on file `sections/method.aux'.\")\n"
                            f"shutil.copyfile({str(root / 'page.pdf')!r}, out / 'main.pdf')\n")
            fake.chmod(0o755)
            with patch.dict("os.environ", {"PATH": str(tools) + ":/usr/bin:/bin"}):
                captured, images = paperroom.render_document(main, None, "1")
            self.assertTrue(captured.startswith(b"%PDF"))
            self.assertEqual(len(images), 1)


if __name__ == "__main__":
    unittest.main()
