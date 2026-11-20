"""Prepared files, content-pinned previews, and the read-only legacy archive."""
from contextlib import closing
import hashlib
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import assets
import paperroom
import workspace_server


class PreparedAssets(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve() / "paper"
        self.root.mkdir()
        self.database = workspace_server.database_path(self.root)

    def file(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def request(self, path, action=None):
        handler = workspace_server.handler_for(self.database, "test-token", self.root)
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            worker = threading.Thread(target=server.handle_request)
            worker.start()
            with closing(http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)) as connection:
                if action:
                    connection.request("POST", path, json.dumps({"action": action}), headers={
                        "Origin": f"http://127.0.0.1:{server.server_port}", "X-Paperroom-Token": "test-token"})
                else:
                    connection.request("GET", path)
                response = connection.getresponse()
                result = response.status, response.headers, response.read()
            worker.join(5)
            return result

    def test_only_prepared_deliverables_are_listed_and_summary_reads_no_contents(self):
        self.file("drafts/fig01.png", b"draft")
        self.file("paperroom-assets/figures/section-1/result.WEBP", b"preview")
        self.file("paperroom-assets/figures/intermediate.csv", b"not a figure")
        self.file("paperroom-assets/tables/measurements.TSV", b"unit\tmean\nms\t12\n")
        self.file("paperroom-assets/tables/Method/print.PDF", b"%PDF-")
        self.file("paperroom-assets/tables/source.tex", b"unrendered")
        self.file("paperroom-assets/figures/.temp.png", b"temp")
        (self.root / "paperroom-assets/figures/link.png").symlink_to(self.root / "drafts/fig01.png")
        (self.root / "paperroom-assets/figures/more").symlink_to(self.root / "drafts", target_is_directory=True)
        with patch.object(assets, "_open_prepared", side_effect=AssertionError("count must not open files")):
            self.assertEqual(assets.prepared_summary(self.root),
                             {"figures": 1, "tables": 1, "directories": assets.PREPARED_DIRS})
        listing = assets.prepared_index(self.root)
        [figure] = listing["figures"]
        self.assertEqual((figure["path"], figure["mime"]), ("paperroom-assets/figures/section-1/result.WEBP", "image/webp"))
        [pdf] = listing["tables"]
        self.assertEqual((pdf["group"], pdf["kind"], pdf["path"], pdf["mime"]),
                         ("tables", "pdf", "paperroom-assets/tables/Method/print.PDF", "application/pdf"))
        self.assertFalse(self.database.exists())

    def test_same_name_replacement_never_serves_new_bytes_under_old_link(self):
        path = self.file("paperroom-assets/tables/print.pdf", b"%PDF-1.4 previous")
        [first] = assets.prepared_index(self.root)["tables"]
        self.assertEqual(first["digest"], hashlib.sha256(path.read_bytes()).hexdigest())
        status, headers, body = self.request(first["preview_url"])
        self.assertEqual((status, headers["X-Frame-Options"], body), (200, "SAMEORIGIN", path.read_bytes()))
        path.write_bytes(b"%PDF-1.4 new")
        [second] = assets.prepared_index(self.root)["tables"]
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["digest"], second["digest"])
        self.assertEqual(self.request(first["preview_url"])[0], 409)
        self.assertEqual(self.request(second["preview_url"])[2], path.read_bytes())
        self.assertEqual(self.request(second["preview_url"].partition("?")[0])[0], 404)
        path.unlink()
        self.assertEqual(self.request(second["preview_url"])[0], 404)
        self.assertFalse(self.database.exists())

    def test_non_pdf_table_files_are_ignored_and_old_preview_links_do_not_serve_them(self):
        for suffix in ("csv", "TSV", "png", "jpg", "jpeg", "webp", "tex"):
            with self.subTest(suffix=suffix):
                relative = "paperroom-assets/tables/benchmarks." + suffix
                content = b"author's original file"
                path = self.file(relative, content)
                asset_id = assets._id("prepared", relative)
                digest = hashlib.sha256(content).hexdigest()
                self.assertEqual(self.request(f"/api/prepared-assets/{asset_id}?v={digest}")[0], 404)
                self.assertEqual(path.read_bytes(), content)
        self.assertEqual(assets.prepared_index(self.root)["tables"], [])
        self.assertEqual(assets.prepared_summary(self.root)["tables"], 0)

    def test_history_is_read_without_sources_or_compilation_and_old_actions_cannot_write(self):
        self.assertEqual(self.request("/api/workspace", "float_build")[0], 410)
        self.assertFalse(self.database.exists())
        body = dict(build=2, created="2026-03-02", origin="ai", main="paper.tex", pages=[3],
                    digest="old", floats=[{"kind": "table", "key": "tab:old", "caption": "As published"}])
        with closing(paperroom.connect(self.database)) as db, db:
            assets._tables(db)
            db.execute("INSERT INTO v2_float_builds VALUES (2, ?)", (json.dumps(body),))
            db.execute("INSERT INTO v2_float_pages VALUES (2, -1, ?)", (b"old PDF bytes",))
        with patch.object(assets, "index", side_effect=AssertionError("must not consult the working paper")):
            with patch.object(assets, "build_history", side_effect=AssertionError("only list prepared files")):
                status, _, listing = self.request("/api/prepared-assets")
            self.assertEqual(status, 200)
            self.assertEqual(set(json.loads(listing)), {"directories", "figures", "tables"})
            status, _, archive = self.request("/api/assets?build=2")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(archive)["tables"][0]["caption"], "As published")
            self.assertEqual(self.request("/api/floats/2/pdf")[2], b"old PDF bytes")
            self.assertEqual(self.request("/api/assets?build=1")[0], 404)
