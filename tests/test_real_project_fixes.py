"""Fixes from using 0.6.14 on a real manuscript: migrated labels, a whole-paper V0 after
migration, local dates, pdfLaTeX builds (no dot-files, bibliography) and a journal that is
emptied rather than deleted."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import outline
import paperroom
import versions
import workspace_server

PNG = (ROOT / "demo/examples/intro.png").read_bytes()


class Project:
    def __init__(self, test):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        with self.db() as db:
            state = outline.update_assets(db, self.root, 0, "Q?", "E.")
            state = outline.submit(db, self.root, state["version"], "paper",
                                   [{"title": "Introduction", "purpose": "a"}, {"title": "Method", "purpose": "b"}])
            self.ids = [s["id"] for s in state["sections"]]

    def db(self):
        return closing(paperroom.connect(workspace_server.database_path(self.root)))

    def migrate_two_references(self):
        """What 0.6.13 left: two frozen Method layouts, the second a new draft."""
        import section_review
        method = self.ids[1]
        with self.db() as db, db:
            section_review._create_tables(db)
            for revision, title, created in ((1, "main.tex 第 2-6 页", "2026-11-20T22:33:34+00:00"),
                                             (2, "P1–P3 草稿（第 2–6 页）", "2026-11-20T23:50:09+00:00")):
                db.execute("INSERT INTO v2_references VALUES (?,?,?,?,?,?,?)",
                           (method, revision, "Method", title, created, 1, f"f{revision}"))
                db.execute("INSERT INTO v2_reference_assets VALUES (?,?,?,?)", (method, revision, 1, PNG))
        return method


def fake_compile(texts):
    def compiled(db, project):
        return dict(pdf=b"%PDF-1.4", images=[PNG], main="main.tex", texts=texts, source_sha256=json.dumps(texts),
                    map={sid: {"title": "T", "page": 1, "paragraphs": {}} for sid in texts}, lines=[], found=[])
    return compiled


class MigratedVersions(unittest.TestCase):
    def test_references_keep_their_own_titles(self):
        paper = Project(self)
        paper.migrate_two_references()
        versions.ensure_migrated(workspace_server.database_path(paper.root))
        with paper.db() as db:
            self.assertEqual([v["label"] for v in versions.listing(db)],
                             ["Method · main.tex 第 2-6 页", "Method · P1–P3 草稿（第 2–6 页）"])

    def test_labels_written_by_0_6_14_are_repaired(self):
        paper = Project(self)
        paper.migrate_two_references()
        with paper.db() as db, db:
            versions.create_tables(db)
            versions.migrate(db)
            for body in versions._bodies(db):  # how 0.6.14 named them
                body["label"] = "Method · 原稿"
                db.execute("UPDATE v2_versions SET body=? WHERE number=?", (json.dumps(body), body["number"]))
        versions.ensure_migrated(workspace_server.database_path(paper.root))
        with paper.db() as db:
            self.assertEqual([v["label"] for v in versions.listing(db)][1], "Method · P1–P3 草稿（第 2–6 页）")

    def test_a_whole_paper_v0_is_still_frozen_after_migration(self):
        paper = Project(self)
        paper.migrate_two_references()
        texts = {paper.ids[0]: ["Intro."], paper.ids[1]: ["Method."]}
        prose = (Path("main.tex"), [], [({"id": paper.ids[0]}, 0, 1)])  # a section with one paragraph
        with paper.db() as db, \
                patch.object(versions, "_located_sections", return_value=prose), \
                patch.object(versions.L, "paragraphs", return_value=[{"text": "Intro."}]), \
                patch.object(versions, "_compile", side_effect=fake_compile(texts)):
            v0 = versions.freeze_original(db, paper.root)
            self.assertEqual(v0["number"], 0)
            self.assertIsNone(versions.freeze_original(db, paper.root))
            changed = dict(texts, **{paper.ids[1]: ["Method, revised."]})
            with patch.object(versions, "_compile", side_effect=fake_compile(changed)):
                v3 = versions.save(db, paper.root)
        # The new version follows the migrated V1 and V2, and is measured against V0.
        self.assertEqual((v3["number"], v3["compared_with"]), (3, 0))
        self.assertEqual(v3["changed"], {paper.ids[1]: [0]})


class LocalDates(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Needs Node.js.")
    def test_dates_follow_the_author_time_zone(self):
        html = (RUNTIME / "workspace.html").read_text()
        source = html[html.index("function localDate"):html.index("function documentNumber")]
        out = subprocess.run(["node", "-e", source + "console.log(localDate('2026-11-20T23:50:09.069991+00:00'))"],
                             capture_output=True, text=True, check=True, env={**os.environ, "TZ": "Australia/Sydney"})
        self.assertEqual(out.stdout.strip(), "2026-11-21")


class PdfLatexBuilds(unittest.TestCase):
    def test_marked_copy_keeps_the_paper_name_without_a_leading_dot(self):
        with tempfile.TemporaryDirectory() as folder:
            paper = Path(folder)
            (paper / "main.tex").write_text("x")
            (paper / "main.bbl").write_text("bbl")
            seen = {}

            def fake(tex, out, sources):
                seen["name"] = tex.name
                seen["bbl"] = (tex.parent / "main.bbl").read_text()
                (Path(out) / "main.aux").write_text("%paperroom-start 1\n")
                return Path(out) / "main.pdf"
            with patch.object(paperroom, "compile_tex", side_effect=fake):
                with paperroom.marked_build(paper / "main.tex", "marked") as (_, aux):
                    self.assertIn("paperroom-start", aux)
        self.assertEqual(seen, {"name": "main.tex", "bbl": "bbl"})

    def run_bibliography(self, *, bbl, cites=True):
        with tempfile.TemporaryDirectory() as folder:
            farm, out = Path(folder) / "paper", Path(folder) / "out"
            farm.mkdir(); out.mkdir()
            tex = farm / "main.tex"
            (out / "main.aux").write_text("\\bibdata{references}\n" if cites else "\\relax\n")
            if bbl:
                (farm / "main.bbl").write_text("x")
            with patch.object(paperroom.shutil, "which", return_value="/usr/bin/bibtex"), \
                    patch.object(paperroom.subprocess, "run") as run:
                paperroom.bibliography(tex, out, farm)
            return run

    def test_bibtex_runs_when_the_paper_cites_and_has_no_bbl(self):
        run = self.run_bibliography(bbl=False)
        self.assertEqual(run.call_args.args[0], ["bibtex", "main"])
        self.assertIn("BIBINPUTS", run.call_args.kwargs["env"])

    def test_an_existing_bbl_or_no_citations_skip_bibtex(self):
        self.assertFalse(self.run_bibliography(bbl=True).called)
        self.assertFalse(self.run_bibliography(bbl=False, cites=False).called)

    def test_pdflatex_passes_around_bibtex(self):
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            tex = Path(folder) / "main.tex"
            tex.write_text("x")
            with patch.object(paperroom.shutil, "which", side_effect=lambda name: "/bin/" + name if name == "pdflatex" else None), \
                    patch.object(paperroom, "run_program", side_effect=lambda args, cwd=None: calls.append(args[0])), \
                    patch.object(paperroom, "bibliography", side_effect=lambda *a: calls.append("bibtex")):
                paperroom.compile_tex(tex, Path(folder), Path(folder))
        self.assertEqual(calls, ["pdflatex", "bibtex", "pdflatex", "pdflatex"])


class Journal(unittest.TestCase):
    def test_the_journal_is_emptied_not_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            with closing(paperroom.connect(Path(folder) / "p.sqlite3")) as db:
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "truncate")


if __name__ == "__main__":
    unittest.main()
