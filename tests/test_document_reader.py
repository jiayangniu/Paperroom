"""Before/after reading: version pairing logic and real-browser interaction checks."""
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


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
    html = (RUNTIME / "workspace.html").read_text(encoding="utf-8")
    start = html.index("function documentNumber")
    end = html.index("/* A reading spot")
    return html[start:end]


class PairingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to run the page script.")
    def test_pairs_each_edition_with_its_own_before_and_never_invents_one(self):
        harness = r"""
const assert = require("node:assert/strict");
const arr = x => Array.isArray(x) ? x : [];
eval(process.argv[1]);
const doc = (id, created) => ({id, created, kind: id.startsWith("rev") ? "edition" : "reference", title: id});
const ids = p => [p.before?.id ?? null, p.after?.id ?? null];
// The original is frozen first, then the rewrite is published.
assert.deepEqual(ids(pairedVersions([doc("ref-1","1"), doc("rev-1","2")], 1)), ["ref-1","rev-1"]);
// Later revisions compare with the previous edition.
const three = [doc("ref-1","1"), doc("rev-1","2"), doc("rev-2","3")];
assert.deepEqual(ids(pairedVersions(three, 2)), ["rev-1","rev-2"]);
assert.deepEqual(ids(pairedVersions(three, 1)), ["ref-1","rev-1"]);
assert.deepEqual(ids(pairedVersions(three, 0)), ["rev-1","rev-2"]);
// New writing with no saved original shows only itself.
assert.deepEqual(ids(pairedVersions([doc("rev-1","2")], 1)), [null,"rev-1"]);
// A reference imported after the edition is not its before.
assert.deepEqual(ids(pairedVersions([doc("rev-1","2"), doc("ref-1","3")], 1)), [null,"rev-1"]);
// Only an original: shown alone.
assert.deepEqual(ids(pairedVersions([doc("ref-1","1")], 0)), [null,"ref-1"]);
assert.deepEqual(ids(pairedVersions([], 0)), [null,null]);
assert.equal(versionName(doc("rev-3","1")), "第 3 版成稿");
"""
        subprocess.run(["node", "-e", harness, pairing_source()], check=True, capture_output=True, text=True)


def seed(project, pdfs):
    import outline
    import paperroom
    import section_review
    import workspace_server
    for name in ("before.pdf", "after.pdf"):
        shutil.copyfile(pdfs / name, project / name)
    paragraphs = ["Screening reduces exact evaluations in paired runs.",
                  "A common stopping rule is needed for a larger comparison."]
    (project / "after.tex").write_text("\\documentclass{article}\\begin{document}\n" + "\n\n".join(paragraphs) +
                                       "\n\\end{document}\n", encoding="utf-8")
    with closing(paperroom.connect(workspace_server.database_path(project))) as db:
        state = outline.update_assets(db, project, 0, "Question?", "Evidence.")
        state = outline.submit(db, project, state["version"], "paper",
                               [{"title": "Introduction", "purpose": "p"}, {"title": "Results", "purpose": "r"}])
        intro, results = (s["id"] for s in state["sections"])
        section_review.import_reference(db, project, intro, title="改写前的引言", pdf="before.pdf")
        section_review.import_reference(db, project, results, title="只有原稿", pdf="before.pdf", pages="1-2")
        state = outline.submit(db, project, state["version"], "section", [{"purpose": "a"}, {"purpose": "b"}],
                               section=intro)
        for item, text in zip(state["sections"][0]["paragraphs"], paragraphs):
            state = outline.submit(db, project, state["version"], "paragraph", ["s1", "s2"],
                                   section=intro, paragraph=item["id"])
            plan = outline.require_paragraph(db, project, intro, item["id"])
            section_review.save_paragraph_draft(db, project, intro, item["id"], plan["revision"], text)
        section_review.publish_section(db, project, intro, tex="after.tex", pdf="after.pdf", minimum=1)
    return intro, results


class BrowserReaderTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node") and chrome() and sys.platform == "darwin",
                         "Needs Node.js, Chrome and macOS PDFKit page rendering.")
    def test_flip_compare_and_keep_unsent_notes_in_a_real_browser(self):
        import workspace_server
        with tempfile.TemporaryDirectory(prefix="paperroom-reader-") as folder:
            base = Path(folder)
            pdfs, project = base / "pdfs", base / "paper"
            pdfs.mkdir(); project.mkdir()
            env = {**os.environ, "PAPERROOM_BROWSER_TMP": folder}
            subprocess.run(["node", str(BROWSER / "make_pdfs.mjs"), chrome(), str(pdfs), str(free_port())],
                           check=True, capture_output=True, text=True, timeout=60, env=env)
            intro, results = seed(project, pdfs)
            handler = workspace_server.handler_for(workspace_server.database_path(project),
                                                   secrets.token_urlsafe(16), project)
            with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    run = subprocess.run(
                        ["node", str(BROWSER / "compare.mjs"), chrome(),
                         f"http://127.0.0.1:{server.server_port}/workspace?", intro, results, str(free_port())],
                        capture_output=True, text=True, timeout=180, env=env)
                finally:
                    server.shutdown()
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertGreaterEqual(len(re.findall(r"^ok ", run.stdout, re.M)), 18, run.stdout)


class BrowserIterationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node") and chrome(), "Needs Node.js and Chrome.")
    def test_second_round_shows_answers_and_can_pass(self):
        import outline
        import paperroom
        import section_review
        import workspace_server
        page = (ROOT / "demo/examples/intro.png").read_bytes()
        with tempfile.TemporaryDirectory(prefix="paperroom-iteration-") as folder, \
                patch.object(paperroom, "render_document", return_value=(b"%PDF-1.4 test", [page])), \
                patch.object(section_review.excerpt, "check", return_value=None):
            project = Path(folder) / "paper"
            project.mkdir()
            with closing(paperroom.connect(workspace_server.database_path(project))) as db:
                state = outline.update_assets(db, project, 0, "Q?", "E.")
                state = outline.submit(db, project, state["version"], "paper", [{"title": "Intro", "purpose": "p"}])
                section = state["sections"][0]["id"]
                state = outline.submit(db, project, state["version"], "section",
                                       [{"purpose": "a"}, {"purpose": "b"}], section=section)
                ids = [p["id"] for p in state["sections"][0]["paragraphs"]]
                for pid, text in zip(ids, ["First paragraph.", "Second paragraph."]):
                    state = outline.submit(db, project, state["version"], "paragraph", ["s"], section=section, paragraph=pid)
                    section_review.save_paragraph_draft(db, project, section, pid, 1, text)
                section_review.publish_section(db, project, section, minimum=2)
                section_review.submit_review(db, project, section, 1, [
                    {"kind": "change", "paragraph": ids[1], "text": "Narrow the claim."},
                    {"kind": "change", "paragraph": ids[0], "text": "Cite the survey."}])
                section_review.save_paragraph_draft(db, project, section, ids[1], 1, "Second, narrower.", 1)
                section_review.publish_section(db, project, section, expected_revision=1, responses=[
                    {"note": 1, "status": "changed", "text": "Narrowed to Y."},
                    {"note": 2, "status": "discuss", "text": "No survey covers this."}])
            handler = workspace_server.handler_for(workspace_server.database_path(project),
                                                   secrets.token_urlsafe(16), project)
            with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    run = subprocess.run(
                        ["node", str(BROWSER / "iteration.mjs"), chrome(),
                         f"http://127.0.0.1:{server.server_port}/workspace?view=review&section={section}", str(free_port())],
                        capture_output=True, text=True, timeout=120,
                        env={**os.environ, "PAPERROOM_BROWSER_TMP": folder})
                finally:
                    server.shutdown()
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("ok approved without new notes", run.stdout)
            with closing(paperroom.connect(workspace_server.database_path(project))) as db:
                self.assertTrue(section_review.status(db, project, section)["revisions"][1]["approved"])


if __name__ == "__main__":
    unittest.main()
