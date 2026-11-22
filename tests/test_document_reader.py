"""Whole-paper versions: pairing and naming logic, and real-browser reading and review checks."""
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins/paperroom/runtime"
BROWSER = ROOT / "tests/browser"
sys.path.insert(0, str(RUNTIME))


def chrome():
    candidates = [os.environ.get("PAPERROOM_CHROME"),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  shutil.which("google-chrome"), shutil.which("chromium")]
    return next((c for c in candidates if c and Path(c).is_file()), None)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pairing_source():
    """The page's whole-paper version helpers, from versionRevisions to anchorPage."""
    html = (RUNTIME / "workspace.html").read_text(encoding="utf-8")
    start = html.index("/* Whole-paper versions")
    end = html.index("/* A reading spot")
    return html[start:end]


HARNESS = r"""
const assert = require("node:assert/strict");
const arr = x => Array.isArray(x) ? x : [];
let data = {outline: {sections: [{id: "intro", title: "Introduction",
                                  paragraphs: [{id: "p1", purpose: "Gap"}, {id: "p2", purpose: "Aim"}]},
                                 {id: "res", title: "Results", paragraphs: [{id: "r1", purpose: "Runs"}]}]},
            versions: [
  {number: 0, kind: "original", label: "原稿", pages: 4, has_pdf: true,
   map: {intro: {title: "Introduction", page: 1, paragraphs: {p1: 1, p2: 2}}, res: {title: "Results", page: 3, paragraphs: {r1: 3}}}},
  {number: 1, kind: "version", label: "", pages: 5, has_pdf: false,
   map: {intro: {title: "Introduction", page: 1, paragraphs: {p1: 1, p2: 3}}, res: {title: "Results", page: 4, paragraphs: {r1: 4}}}},
  {number: 2, kind: "version", label: "导师会前", pages: 5, has_pdf: true,
   map: {intro: {title: "Introduction", page: 2, paragraphs: {p1: 2, p2: 3}}}}]};
eval(process.argv[1]);
"""


class PairingTests(unittest.TestCase):
    def run_harness(self, checks):
        run = subprocess.run(["node", "-e", HARNESS + checks, pairing_source()], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to run the page script.")
    def test_versions_are_named_and_opened_at_the_outline_place(self):
        self.run_harness(r"""
const docs = versionDocs();
assert.deepEqual(docs.map(d => [d.id, d.number, d.pdf_url, d.page_url]), [
  ["v-0", 0, "/api/versions/0/pdf", "/api/versions/0/pages/"],
  ["v-1", 1, null, "/api/versions/1/pages/"],
  ["v-2", 2, "/api/versions/2/pdf", "/api/versions/2/pages/"]]);
assert.deepEqual(docs.map(versionName), ["V0 · 原稿", "V1", "V2 · 导师会前"]);
assert.equal(versionName({number: 0, kind: "original", title: ""}), "V0 · 原稿");
assert.equal(versionName(null), "");
assert.equal(documentNumber({id: "v-12"}), 12);
assert.equal(versionName({id: "v-3", kind: "version"}), "V3");
// Each version lists its paragraphs with the page they start on, for notes and anchors.
const revisions = versionRevisions();
assert.deepEqual(revisions.map(r => r.revision), [0, 1, 2]);
assert.deepEqual(revisions[1].paragraphs.map(p => [p.section, p.id, p.sectionTitle, p.index, p.purpose, p.page]),
  [["intro", "p1", "Introduction", 1, "Gap", 1], ["intro", "p2", "Introduction", 2, "Aim", 3],
   ["res", "r1", "Results", 1, "Runs", 4]]);
// The reader opens every version at the section or paragraph being written.
assert.equal(anchorPage(docs[1], "res"), 4);
assert.equal(anchorPage(docs[1], "intro", "p2"), 3);
assert.equal(anchorPage(docs[1], "intro", "unknown"), 1);
assert.equal(anchorPage(docs[2], "res"), 1, "a section missing from a version opens at its first page");
assert.equal(anchorPage(undefined, "intro"), 1);
""")

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to run the page script.")
    def test_cleanup_keeps_exact_link_targets_and_renumbers_labels(self):
        self.run_harness(r"""
const previous = data.versions[1];
data.archived_versions = [{...previous, cleaned_at:"2026-01-01", last_display_number:1}];
data.versions = [data.versions[0], {...data.versions[2], display_number:1}];
const docs = versionDocs();
assert.equal(versionName(docs[1]), "V1 · 导师会前");
assert.equal(docs[1].pdf_url, "/api/versions/2/pdf");
assert.equal(versionById(1).cleaned_at, "2026-01-01");
assert.equal(versionById(2).display_number, 1);
assert.equal(readerPair(docs, {before:0, after:1}), null);
assert.equal(readerPair(docs, {mode:"latest", after:2}).after.id, "v-2");
assert.equal(readerPair(docs, {mode:"latest", before:1, after:2}).after.id, "v-2");
assert.equal(readerPair(docs, {mode:"latest", before:2, after:1}), null);
""")

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to run the page script.")
    def test_latest_is_compared_with_the_previous_unless_two_are_named(self):
        self.run_harness(r"""
const [v0, v1, v2] = versionDocs();
const numbers = p => p && [p.before?.number ?? null, p.after?.number ?? null];
assert.deepEqual(numbers(readerPair([v0, v1, v2])), [1, 2]);
assert.deepEqual(numbers(readerPair([v0])), [null, 0], "a lone version is never given a partner");
assert.deepEqual(numbers(readerPair([])), [null, null]);
// A named pair is kept exactly, also when the numbers come from the URL as text.
assert.deepEqual(numbers(readerPair([v0, v1, v2], {before: 0, after: 2})), [0, 2]);
assert.deepEqual(numbers(readerPair([v0, v1, v2], {before: "0", after: "1"})), [0, 1]);
// Both or neither, existing and different.
assert.equal(readerPair([v0, v1, v2], {after: 2}), null);
assert.equal(readerPair([v0, v1, v2], {before: 1, after: 1}), null);
assert.equal(readerPair([v0, v1, v2], {before: 0, after: 9}), null);
""")


def page_png(rgb, width=420, height=594):
    """A plain page image in one colour, A-paper proportions."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


class Paper:
    """A two-section outline whose whole-paper versions are stored as save_version stores
    them, from stand-in builds: page images and the page each section and paragraph starts on."""

    def __init__(self, project):
        import outline
        import paperroom
        import workspace_server
        self.project = project
        self.database = workspace_server.database_path(project)
        with closing(paperroom.connect(self.database)) as db:
            state = outline.update_assets(db, project, 0, "Question?", "Evidence.")
            state = outline.submit(db, project, state["version"], "paper",
                                   [{"title": "Introduction", "purpose": "p"}, {"title": "Results", "purpose": "r"}])
            self.intro, self.results = (s["id"] for s in state["sections"])
            state = outline.submit(db, project, state["version"], "section", [{"purpose": "a"}, {"purpose": "b"}],
                                   section=self.intro)
            state = outline.submit(db, project, state["version"], "section", [{"purpose": "c"}], section=self.results)
            self.p1, self.p2 = (p["id"] for p in state["sections"][0]["paragraphs"])
            self.r1 = state["sections"][1]["paragraphs"][0]["id"]

    def db(self):
        import paperroom
        return closing(paperroom.connect(self.database))

    def build(self, pages, p2, results, texts, shade):
        """A stand-in for versions._compile: `pages` pages, the second introduction paragraph
        starting on page p2 and the results on page `results`."""
        place = {self.intro: {"title": "Introduction", "page": 1, "paragraphs": {self.p1: 1, self.p2: p2}},
                 self.results: {"title": "Results", "page": results, "paragraphs": {self.r1: results}}}
        images = [page_png((255 - 12 * n, 250 - shade, 240 - shade)) for n in range(pages)]
        return lambda db, project, pdf=None: dict(pdf=b"%PDF-1.4 stand-in", images=images, main="main.tex", map=place,
                                        texts={self.intro: texts[:2], self.results: texts[2:]},
                                        source_sha256="|".join(texts), found=[], lines=[])

    def original(self, pages, p2, results, texts):
        import versions
        with self.db() as db, db:
            versions.create_tables(db)
            versions._store(db, 0, "original", "原稿", self.build(pages, p2, results, texts, 0)(db, self.project), None)

    def save(self, pages, p2, results, texts, label=None, responses=None):
        import versions
        with self.db() as db, patch.object(versions, "_compile", self.build(pages, p2, results, texts, 20 * pages)):
            return versions.save(db, self.project, label=label, responses=responses)

    def review(self, number, notes):
        import versions
        with self.db() as db:
            return versions.submit_review(db, number, notes)

    def version(self, number):
        import versions
        with self.db() as db:
            return versions.get(db, number)


def serve(project, script, *args, timeout=180):
    """Run a browser script against a workspace server for this project."""
    import workspace_server
    handler = workspace_server.handler_for(workspace_server.database_path(project), secrets.token_urlsafe(16), project)
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            return subprocess.run(["node", str(BROWSER / script), chrome(),
                                   f"http://127.0.0.1:{server.server_port}/workspace?", *args, str(free_port())],
                                  capture_output=True, text=True, timeout=timeout,
                                  env={**os.environ, "PAPERROOM_BROWSER_TMP": str(project.parent)})
        finally:
            server.shutdown()


TEXTS = ["Screening reduces exact evaluations.", "A common stopping rule is needed.", "Three paired runs."]


class BrowserReaderTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node") and chrome(), "Needs Node.js and Chrome.")
    def test_flip_compare_and_keep_unsent_notes_in_a_real_browser(self):
        with tempfile.TemporaryDirectory(prefix="paperroom-reader-") as folder:
            project = Path(folder) / "paper"
            project.mkdir()
            paper = Paper(project)
            # V0 has the results on page 3, V1 on page 4 and V2 on page 5: a reading spot
            # moves between versions by the section it is in, not by page number.
            paper.original(4, 2, 3, TEXTS)
            paper.save(5, 2, 4, [TEXTS[0], "A shared stopping rule is needed.", TEXTS[2]], label="导师会前")
            paper.save(6, 3, 5, [TEXTS[0], "A shared stopping rule is needed here.", TEXTS[2]])
            run = serve(project, "compare.mjs", paper.intro, paper.results)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertGreaterEqual(len(re.findall(r"^ok ", run.stdout, re.M)), 18, run.stdout)
            note, = paper.version(2)["notes"]
            self.assertEqual((note["kind"], note["page"]), ("change", 2))
            self.assertTrue(note["text"].startswith("第二段的转折还没写完"))
            self.assertTrue(0 <= note["pin"]["x"] <= 1 and 0 <= note["pin"]["y"] <= 1)


class BrowserIterationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node") and chrome(), "Needs Node.js and Chrome.")
    def test_second_round_shows_answers_and_can_pass(self):
        with tempfile.TemporaryDirectory(prefix="paperroom-iteration-") as folder:
            project = Path(folder) / "paper"
            project.mkdir()
            paper = Paper(project)
            paper.save(2, 1, 2, TEXTS)
            paper.review(1, [{"kind": "change", "page": 1, "section": paper.intro, "paragraph": paper.p2,
                              "text": "Narrow the claim."},
                             {"kind": "change", "page": 1, "pin": {"x": 0.3, "y": 0.4}, "text": "Cite the survey."}])
            paper.save(2, 1, 2, [TEXTS[0], "A narrower stopping rule.", TEXTS[2]], label="第二轮", responses=[
                {"note": 1, "status": "changed", "text": "Narrowed to Y."},
                {"note": 2, "status": "discuss", "text": "No survey covers this."}])
            run = serve(project, "iteration.mjs", timeout=120)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("ok approved without new notes", run.stdout)
            latest = paper.version(2)
            self.assertTrue(latest["approved"])
            self.assertEqual(latest["notes"], [])

if __name__ == "__main__":
    unittest.main()
