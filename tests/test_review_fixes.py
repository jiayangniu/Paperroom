"""Regressions for the ten issues found in the 0.6.0 review.

Synthetic papers in temporary folders only. PDF checks read the text of the final
PDF the author receives. The synthetic author's outline is written with
outline.submit, the function the browser endpoint uses.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import assets
import i18n
import latex_source as L
import outline
import paperroom
import paperroom_mcp as mcp
import pdf_text
import section_review
import workspace_server

BUNDLED = Path("/Applications/ChatGPT.app/Contents/Resources/tectonic/tectonic")
HAS_TEX = bool(shutil.which("pdflatex") or shutil.which("tectonic") or BUNDLED.is_file()) and \
    (sys.platform == "darwin" or shutil.which("pdftoppm"))
WORDS = " ".join(["Screening trades exact evaluations for cheap surrogate scores."] * 4)


def png(rgb):
    """A 4x4 single-colour PNG."""
    raw = b"".join(b"\x00" + bytes(rgb) * 4 for _ in range(4))
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))



def seen(state, key):
    """What the author's card shows for a float: its page in the latest build."""
    placed = next(f for f in state["build"]["floats"] if f["key"] == key)
    return dict(build=state["build"]["build"], digest=placed["digest"])

class Paper:
    """A synthetic project, its database and an MCP caller."""

    def __init__(self, test, files, sections, plans, database=None):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text) if isinstance(text, bytes) else path.write_text(text)
        self.database = self.root / database if database else workspace_server.database_path(self.root)
        with self.db() as db:
            state = outline.update_assets(db, self.root, 0, "Does screening save evaluations?", "Three paired runs.")
            state = outline.submit(db, self.root, state["version"], "paper",
                                   [{"title": t, "purpose": "Role of " + t} for t in sections])
            self.ids = {s["title"]: s["id"] for s in state["sections"]}
            for title, count in plans.items():
                state = outline.submit(db, self.root, state["version"], "section",
                                       [{"purpose": f"Paragraph {i + 1}"} for i in range(count)], section=self.ids[title])
            self.paragraphs = {s["title"]: [p["id"] for p in s["paragraphs"]] for s in state["sections"]}

    def db(self):
        return closing(paperroom.connect(self.database))

    def intents(self, title, *numbers):
        with self.db() as db:
            for n in numbers:
                version = outline.state(db, self.root)["version"]
                outline.submit(db, self.root, version, "paragraph", ["Say it plainly."],
                               section=self.ids[title], paragraph=self.paragraphs[title][n])

    def call(self, name, **args):
        with patch.object(mcp, "show_author", return_value={"room_url": "test"}):
            return json.loads(json.dumps(mcp.invoke(name, {"project": str(self.root), **args})))

    def register(self, title, *numbers):
        for n in numbers:
            self.call("save_paragraph_draft", section=self.ids[title], paragraph=self.paragraphs[title][n],
                      plan_revision=1, expected_version=0)

    def blob(self, table, revision, page):
        with self.db() as db:
            return db.execute(f"SELECT content FROM {table} WHERE revision=? AND page=?", (revision, page)).fetchone()[0]

    def pdf_text(self, table, revision):
        return "\n".join(pdf_text.read_pages(self.blob(table, revision, -1)))


INTRO_OLD = "Original introduction says the cost is dominated by exact evaluations."
INTRO_NEW = "Rewritten introduction frames screening as a trade between cost and accuracy."
MULTI = {
    "main.tex": "\\documentclass{article}\n\\begin{document}\n\\input{sections/intro}\n\\input{sections/method}\n\\end{document}\n",
    "sections/intro.tex": f"\\section{{Introduction}}\n{INTRO_OLD}\n",
    "sections/method.tex": "\\section{Method}\nThree paired runs.\n",
}


@unittest.skipUnless(HAS_TEX, "Needs a TeX engine and a page renderer.")
class FirstRewriteDefaults(unittest.TestCase):
    """1. Opening the workspace without a section still freezes the selected one."""

    def check(self, entry):
        paper = Paper(self, MULTI, ["Introduction", "Method"], {"Introduction": 1})
        first = paper.call(entry)
        self.assertEqual(first["section"], paper.ids["Introduction"])
        self.assertEqual([d["id"] for d in first["review"]["documents"]], ["ref-1"])
        (paper.root / "sections/intro.tex").write_text(f"\\section{{Introduction}}\n{INTRO_NEW}\n")
        again = paper.call(entry)
        self.assertEqual([d["id"] for d in again["review"]["documents"]], ["ref-1"])
        before = paper.pdf_text("v2_reference_assets", 1)
        self.assertIn("Original introduction", before)
        self.assertNotIn("Rewritten introduction", before)

    def test_workspace_status_without_section(self):
        self.check("workspace_status")

    def test_open_writing_workspace_without_section(self):
        self.check("open_writing_workspace")


@unittest.skipUnless(HAS_TEX, "Needs a TeX engine and a page renderer.")
class ReviewPdfMatchesTheCompiledPaper(unittest.TestCase):
    """2. Only what the real compile prints counts as shown to the author."""

    def test_includeonly_excluded_section_is_refused_and_never_reappears(self):
        files = {
            "main.tex": "\\documentclass{article}\n\\includeonly{sections/method}\n\\begin{document}\n"
                        "\\include{sections/intro}\n\\include{sections/method}\n\\end{document}\n",
            "sections/intro.tex": "\\section{Introduction}\nIntro text that must not appear.\n",
            "sections/method.tex": "\\section{Method}\nMethod text that is compiled.\n",
        }
        paper = Paper(self, files, ["Introduction", "Method"], {"Introduction": 1, "Method": 1})
        status = paper.call("workspace_status")
        self.assertEqual(status["review"]["documents"], [])
        self.assertIn("\\includeonly", status["review"]["source"]["error"])
        paper.intents("Introduction", 0)
        with self.assertRaisesRegex(ValueError, "includeonly"):
            paper.register("Introduction", 0)
        paper.intents("Method", 0)
        paper.register("Method", 0)
        paper.call("publish_section", section=paper.ids["Method"], expected_revision=0, minimum=1)
        text = paper.pdf_text("v2_pages", 1)
        self.assertIn("Method text that is compiled", text)
        self.assertNotIn("Intro text that must not appear", text)

    def test_hidden_paragraphs_are_not_counted_or_published(self):
        files = {"main.tex": "\\documentclass{article}\n\\newif\\ifdraft\n\\newcommand{\\ours}{ScreenRank}\n"
                             "\\begin{document}\n\\section{Introduction}\\label{sec:intro}\n"
                             "Visible one uses $x^2$ and \\ours{} as in Section~\\ref{sec:intro}.\n\n"
                             "\\iffalse\nHidden by iffalse.\n\\fi\n\n"
                             "\\ifdraft\nHidden by a draft switch.\n\\fi\n\n"
                             "Visible two.\n\\end{document}\n"}
        paper = Paper(self, files, ["Introduction"], {"Introduction": 3})
        paper.call("workspace_status")
        paper.intents("Introduction", 0, 1, 2)
        paper.register("Introduction", 0, 1, 2)
        # \ifdraft cannot be decided from the source: the compile shows it never printed.
        with self.assertRaisesRegex(ValueError, "第 2 段（main.tex:13）没有出现在编译结果中"):
            paper.call("publish_section", section=paper.ids["Introduction"], expected_revision=0, minimum=1)
        with paper.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM v2_editions").fetchone()[0], 0)
        # Removing the switch publishes, with math, \ref and a macro intact.
        source = (paper.root / "main.tex").read_text().replace("\\ifdraft\nHidden by a draft switch.\n\\fi",
                                                               "Shown in every build.")
        (paper.root / "main.tex").write_text(source)
        paper.call("save_paragraph_draft", section=paper.ids["Introduction"], paragraph=paper.paragraphs["Introduction"][1],
                   plan_revision=1, expected_version=1)
        result = paper.call("publish_section", section=paper.ids["Introduction"], expected_revision=0, minimum=1)
        self.assertEqual([p["text"] for p in result["revisions"][0]["paragraphs"]][1], "Shown in every build.")
        text = paper.pdf_text("v2_pages", 1)
        self.assertIn("ScreenRank", text)
        self.assertNotIn("Hidden by iffalse", text)


@unittest.skipUnless(HAS_TEX, "Needs a TeX engine and a page renderer.")
class DeferredFloats(unittest.TestCase):
    """3. A float of the section that lands on a later page is part of the review."""

    def test_two_column_table_star_on_the_next_page(self):
        body = "\n\n".join(f"Intro paragraph {i}. {WORDS}" for i in range(1, 4))
        files = {"main.tex": "\\documentclass[twocolumn]{article}\n\\begin{document}\n\\section{Introduction}\n" + body +
                             "\n\\begin{table*}[t]\n\\centering\\caption{DEFERREDTABLE wide comparison.}\n"
                             "\\begin{tabular}{lll}a&b&c\\\\\\end{tabular}\n\\end{table*}\n"
                             "\\section{Results}\nResults body.\n\\end{document}\n"}
        paper = Paper(self, files, ["Introduction", "Results"], {"Introduction": 3, "Results": 1})
        paper.call("workspace_status")
        paper.intents("Introduction", 0, 1, 2)
        paper.register("Introduction", 0, 1, 2)
        result = paper.call("publish_section", section=paper.ids["Introduction"], expected_revision=0, minimum=1)
        self.assertEqual(result["revisions"][0]["pages"], 2)
        pages = pdf_text.read_pages(paper.blob("v2_pages", 1, -1))
        self.assertIn("DEFERREDTABLE", pages[1])
        self.assertIn("Intro paragraph 1", pages[0])
        # The next section has no float of its own and gains no pages.
        paper.intents("Results", 0)
        paper.register("Results", 0)
        later = paper.call("publish_section", section=paper.ids["Results"], expected_revision=0, minimum=1)
        self.assertEqual(later["revisions"][0]["pages"], 1)


class ParagraphRecognition(unittest.TestCase):
    """4. Text after the heading counts; a comment line does not split a paragraph."""

    def test_heading_line_and_comment_lines(self):
        files = {"main.tex": "\\documentclass{article}\n\\begin{document}\n"
                             "\\section{Introduction}\\label{sec:intro} First paragraph begins here\nand goes on.\n"
                             "% a note to self\nstill the first.\n\nSecond paragraph.\n\\end{document}\n"}
        paper = Paper(self, files, ["Introduction"], {"Introduction": 2})
        source = paper.call("workspace_status", section=paper.ids["Introduction"])["review"]["source"]
        self.assertEqual((source["found"], source["expected"]), (2, 2))
        self.assertEqual([p["where"] for p in source["paragraphs"]], ["main.tex:3", "main.tex:8"])
        texts = [p["text"] for p in L.section(paper.root, "Introduction").paragraphs]
        self.assertEqual(texts, ["First paragraph begins here\nand goes on.\nstill the first.", "Second paragraph."])
        marked = L.section(paper.root, "Introduction").marked()
        # The paragraph's marker follows its last typeset words.
        self.assertGreater(marked.index("paperroom-par-0-0"), marked.index("still the first."))
        self.assertLess(marked.index("paperroom-par-0-0"), marked.index("Second paragraph."))


GATE_MAIN = ("\\documentclass{article}\n\\begin{document}\n\\input{sections/intro}\n\\end{document}\n")
GATE_INTRO = "\\section{Introduction}\n%s\n\n%s\n"
OLD_1 = "Each exact evaluation can dominate the cost of a search, which is why we count them in every run."
OLD_2 = "We compare a screening rule with an unscreened search in three paired runs on one benchmark suite."
NEW_2 = ("Screening is assessed here through a separate cost model whose parameters come from earlier "
         "benchmarks rather than from the paired runs reported in the remainder of this paper.")


def gate(payload, cwd, data_dir):
    run = subprocess.run([sys.executable, str(RUNTIME / "tex_gate.py")], input=json.dumps({"cwd": str(cwd), **payload}),
                         capture_output=True, text=True, timeout=60,
                         env={"PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_DATA": str(data_dir)})
    return json.loads(run.stdout) if run.stdout.strip() else None


class GateFindsTheProject(unittest.TestCase):
    """5. The hook identifies old projects and bound main files like the workspace."""

    def edit(self, paper, path, old, new):
        return gate({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                     "tool_input": {"file_path": str(paper.root / path), "old_string": old, "new_string": new}},
                    paper.root, paper.root.parent / (paper.root.name + "-gate"))

    def denied(self, result):
        return bool(result) and result["hookSpecificOutput"]["permissionDecision"] == "deny"

    def run_case(self, paper, path):
        self.assertTrue(self.denied(self.edit(paper, path, OLD_2, NEW_2)))
        paper.intents("Introduction", 1)
        self.assertIsNone(self.edit(paper, path, OLD_2, NEW_2))

    def test_legacy_database_under_paperroom_tool(self):
        files = {"main.tex": GATE_MAIN, "sections/intro.tex": GATE_INTRO % (OLD_1, OLD_2)}
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        legacy = Path(folder.name).resolve() / "paperroom_tool/.paperroom/project.sqlite3"
        paperroom.connect(legacy).close()
        with patch.object(tempfile, "TemporaryDirectory", lambda: folder):
            paper = Paper(self, files, ["Introduction"], {"Introduction": 2})
        self.assertEqual(paper.database, legacy)
        self.assertFalse((paper.root / ".paperroom/project.sqlite3").exists())
        self.run_case(paper, "sections/intro.tex")
        with paper.db() as db:
            assets.add_note(db, paper.root, "new", "Add a convergence figure.")
        reminder = gate({"hook_event_name": "UserPromptSubmit", "prompt": "go"}, paper.root, paper.root / ".gate")
        self.assertIsNone(reminder)

    def test_conference_and_journal_mains_with_a_binding(self):
        files = {"conference.tex": GATE_MAIN, "journal.tex": GATE_MAIN.replace("article", "report"),
                 "sections/intro.tex": GATE_INTRO % (OLD_1, OLD_2)}
        paper = Paper(self, files, ["Introduction"], {"Introduction": 2})
        paper.intents("Introduction", 0)
        with self.assertRaisesRegex(ValueError, "多个主"):
            paper.register("Introduction", 0)
        paper.call("bind_section_source", section=paper.ids["Introduction"], tex="conference.tex")
        self.run_case(paper, "sections/intro.tex")


class AnswersWithoutChanges(unittest.TestCase):
    """6. kept/discuss answers reach the author even when nothing else changed."""

    def test_answers_form_a_version_once(self):
        files = {"main.tex": "\\documentclass{article}\n\\begin{document}\n\\section{Introduction}\nOnly paragraph.\n\\end{document}\n"}
        paper = Paper(self, files, ["Introduction"], {"Introduction": 1})
        paper.intents("Introduction", 0)
        page = (ROOT / "demo/examples/intro.png").read_bytes()
        fake = lambda main, source, select: (b"%PDF-1.4 same", [page], select(
            {L.START_MARK: 1, L.END_MARK: 1, "paperroom-par-0-0": 1}), {})
        with patch.object(paperroom, "render_marked", fake):
            paper.register("Introduction", 0)
            section = paper.ids["Introduction"]
            paper.call("publish_section", section=section, expected_revision=0, minimum=1)
            with paper.db() as db:
                section_review.submit_review(db, paper.root, section, 1, [
                    {"kind": "change", "paragraph": paper.paragraphs["Introduction"][0], "text": "Cut the second clause."}])
            answers = [{"note": 1, "status": "discuss", "text": "The clause carries the scope; I suggest keeping it."}]
            first = paper.call("publish_section", section=section, expected_revision=1, responses=answers)
            again = paper.call("publish_section", section=section, expected_revision=1, responses=answers)
        self.assertEqual((first["current_revision"], again["current_revision"]), (2, 2))
        with paper.db() as db:
            rows = [json.loads(b) for b, in db.execute("SELECT body FROM v2_editions ORDER BY revision")]
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[1]["responses"], rows[1]["changed"]), (answers, []))
        # What the author's page loads: the answer, ready to approve or discuss.
        view = workspace_server.read_snapshot(paper.root, section)
        self.assertEqual(view["review"]["phase"], "review")
        self.assertEqual(view["review"]["revisions"][1]["responses"][0]["text"], answers[0]["text"])
        sys.path.insert(0, str(ROOT / "tests"))
        from test_document_reader import chrome, free_port
        if shutil.which("node") and chrome():
            import secrets, threading
            from http.server import ThreadingHTTPServer
            handler = workspace_server.handler_for(paper.database, secrets.token_urlsafe(8), paper.root)
            with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    run = subprocess.run(["node", str(ROOT / "tests/browser/answers.mjs"), chrome(),
                                          f"http://127.0.0.1:{server.server_port}/workspace?view=review&section={section}",
                                          str(free_port())], capture_output=True, text=True, timeout=120,
                                         env={**os.environ, "PAPERROOM_BROWSER_TMP": str(paper.root.parent)})
                finally:
                    server.shutdown()
            self.assertIn("ok answer shown", run.stdout, run.stdout + run.stderr)


def fake_build(main, source, select):
    page = (ROOT / "demo/examples/intro.png").read_bytes()
    located = {f"paperroom-float-{n}": 1 for n in range(4)}
    pages = select(located)
    return b"%PDF-1.4 floats", [page] * len(pages), pages, located


class FigureReplacedUnderTheSameName(unittest.TestCase):
    """7. Replacing an image file makes the build stale and the confirmation void."""

    def test_blue_then_red(self):
        files = {"main.tex": "\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n\\section{Results}\n"
                             "\\begin{figure}\\includegraphics{figs/plot.png}\\caption{Plot.}\\label{fig:plot}\\end{figure}\n"
                             "\\begin{table}\\caption{Runs.}\\label{tab:runs}\\begin{tabular}{l}x\\end{tabular}\\end{table}\n"
                             "\\end{document}\n", "figs/plot.png": png((0, 0, 255))}
        paper = Paper(self, files, ["Results"], {})
        with patch.object(paperroom, "render_marked", fake_build), paper.db() as db:
            assets.build(db, paper.root, "ai")
            state = assets.confirm(db, paper.root, "fig:plot", True, **seen(assets.state(db, paper.root), "fig:plot"))
            self.assertFalse(state["confirmed"]["fig:plot"]["changed"])
            (paper.root / "figs/plot.png").write_bytes(png((255, 0, 0)))
            state = assets.state(db, paper.root)
            self.assertTrue(state["build"]["stale"])
            self.assertTrue(state["confirmed"]["fig:plot"]["changed"])
            state = assets.build(db, paper.root, "ai")
            self.assertFalse(state["build"]["stale"])
            self.assertTrue(state["confirmed"]["fig:plot"]["changed"])
            # Confirmations from 0.6.0 recorded only the LaTeX: a figure with images
            # asks to be confirmed again, a table without images keeps its mark.
            index = assets.index(paper.root)
            table = next(t for t in index["tables"] if t["key"] == "tab:runs")
            figure = next(f for f in index["figures"] if f["key"] == "fig:plot")
            db.execute("INSERT OR REPLACE INTO v2_float_confirmations VALUES (?,?,?,?)", ("tab:runs", table["legacy_digest"], 1, "x"))
            db.execute("INSERT OR REPLACE INTO v2_float_confirmations VALUES (?,?,?,?)", ("fig:plot", figure["legacy_digest"], 1, "x"))
            db.commit()
            old = assets.state(db, paper.root)["confirmed"]
            self.assertEqual((old["tab:runs"]["changed"], old["fig:plot"]["changed"]), (False, True))


class ProjectBoundary(unittest.TestCase):
    """8. Only files really inside the project are listed, previewed or written."""

    def test_links_leading_outside(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        secret = Path(outside.name) / "private.png"
        secret.write_bytes(png((1, 2, 3)))
        (Path(outside.name) / "private.csv").write_text("secret,1\n")
        files = {"main.tex": "\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n\\section{Results}\n"
                             "\\begin{figure}\\includegraphics{figs/link.png}\\caption{X.}\\label{fig:x}\\end{figure}\n"
                             "\\end{document}\n", "figs/own.png": png((9, 9, 9)), "data/own.csv": "a,b\n1,2\n"}
        paper = Paper(self, files, ["Results"], {})
        (paper.root / "figs/link.png").symlink_to(secret)
        (paper.root / "data/link.csv").symlink_to(Path(outside.name) / "private.csv")
        index = assets.index(paper.root)
        self.assertEqual([i["where"] for i in index["images"]], ["figs/own.png"])
        self.assertEqual([d["where"] for d in index["data"]], ["data/own.csv"])
        self.assertEqual(index["figures"][0]["graphics"], [])
        own = index["images"][0]
        self.assertEqual(assets.preview(paper.root, own["id"])[1][:4], b"\x89PNG")
        # The language preference is never written through a link.
        target = Path(outside.name) / "language"
        target.write_text("unchanged")
        (paper.root / ".paperroom/language").symlink_to(target)
        with self.assertRaises(ValueError):
            i18n.set_language(paper.root, "en")
        self.assertEqual(target.read_text(), "unchanged")
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        project = Path(other.name) / "paper"
        project.mkdir()
        (project / ".paperroom").symlink_to(outside.name, target_is_directory=True)
        with self.assertRaises(ValueError):
            i18n.set_language(project, "en")
        self.assertEqual(target.read_text(), "unchanged")


class LargeDataFile(unittest.TestCase):
    """10. One malformed CSV does not take the workspace down."""

    def test_oversized_field(self):
        files = {"main.tex": "\\documentclass{article}\n\\begin{document}\n\\section{Results}\nText.\n\\end{document}\n",
                 "data/huge.csv": "name,notes\nfirst,ok\nsecond," + "x" * 150_000 + "\n",
                 "data/fine.csv": "a,b\n1,2\n"}
        paper = Paper(self, files, ["Results"], {"Results": 1})
        status = paper.call("workspace_status", section=paper.ids["Results"])
        self.assertEqual(status["outline"]["sections"][0]["title"], "Results")
        self.assertEqual(status["prepared_assets"]["tables"], 0)
        data = {d["where"]: d for d in assets.index(paper.root)["data"]}
        self.assertEqual(data["data/huge.csv"]["rows"][:2], [["name", "notes"], ["first", "ok"]])
        self.assertIn("无法预览", data["data/huge.csv"]["problem"])
        self.assertEqual(data["data/fine.csv"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
