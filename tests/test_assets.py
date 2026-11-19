"""Figures, tables and data indexed from the paper and served as previews."""
from http.server import ThreadingHTTPServer
import http.client
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import assets
import workspace_server

BUNDLED = Path("/Applications/ChatGPT.app/Contents/Resources/tectonic/tectonic")
HAS_TEX = bool(shutil.which("pdflatex") or shutil.which("tectonic") or BUNDLED.is_file())
MAIN = r"""\documentclass{article}
\usepackage{graphicx}
\graphicspath{{figs/}}
\newcommand{\ours}{ScreenRank}
\begin{document}
\section{Introduction}
\begin{figure}[t]
\includegraphics[width=.5\linewidth]{runs}
\caption{Evaluations for \ours{} \cite{x}, see Table~\ref{tab:runs}.}\label{fig:runs}
\end{figure}
% \begin{figure}\includegraphics{unused}\end{figure}
\section{Results}
\input{sections/table}
\end{document}
"""
TABLE = r"""\begin{table}[h]
\centering\caption{Paired runs.}\label{tab:runs}
\begin{tabular}{lr}Run & \ours{} \\ 1 & 76 \\\end{tabular}
\end{table}
"""



def seen(state, key):
    """What the author's card shows for a float: its page in the latest build."""
    placed = next(f for f in state["build"]["floats"] if f["key"] == key)
    return dict(build=state["build"]["build"], digest=placed["digest"])

class AssetTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = root = Path(folder.name).resolve()
        for sub in ("figs", "sections", "data", "build"):
            (root / sub).mkdir()
        png = (ROOT / "demo/examples/intro.png").read_bytes()
        (root / "figs/runs.png").write_bytes(png)
        (root / "figs/unused.png").write_bytes(png)
        (root / "figs/plot.pdf").write_bytes((ROOT / "demo/examples/intro.pdf").read_bytes())
        (root / "build/main.pdf").write_bytes(b"%PDF-1.4 not a figure")
        (root / "main.tex").write_text(MAIN)
        (root / "sections/table.tex").write_text(TABLE)
        (root / "data/runs.csv").write_text("run,baseline,screened\n" + "".join(f"{i},100,{70 + i}\n" for i in range(1, 11)))
        (root / "main.aux").write_text("\\newlabel{fig:runs}{{3}{2}}\n")

    def test_index_reads_floats_through_inputs_and_lists_the_rest(self):
        data = assets.index(self.project)
        self.assertEqual(data["main"], "main.tex")
        [figure] = data["figures"]
        self.assertEqual((figure["label"], figure["number"], figure["numbered_by"]), ("fig:runs", "3", "aux"))
        self.assertEqual(figure["graphics"], ["figs/runs.png"])
        # Formatting and references are dropped; simple preamble macros are spelled out.
        self.assertEqual(figure["caption"], "Evaluations for ScreenRank [引用], see Table [tab:runs].")
        self.assertEqual((figure["section"], figure["where"]), ("Introduction", "main.tex:7"))
        [table] = data["tables"]
        self.assertEqual((table["number"], table["section"], table["where"]), ("1", "Results", "sections/table.tex:1"))
        # Unused figure files, but not the paper's own build output.
        self.assertEqual(sorted(i["where"] for i in data["images"]), ["figs/plot.pdf", "figs/unused.png"])
        [csv] = data["data"]
        self.assertEqual((csv["total"], len(csv["rows"]), csv["rows"][0]), (11, 6, ["run", "baseline", "screened"]))

    def test_previews_are_served_only_for_indexed_items(self):
        data = assets.index(self.project)
        handler = workspace_server.handler_for(workspace_server.database_path(self.project),
                                               secrets.token_urlsafe(8), self.project)
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                def get(path):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=60)
                    connection.request("GET", path)
                    response = connection.getresponse()
                    return response.status, response.getheader("Content-Type"), response.read()
                status, _, body = get("/api/assets")
                self.assertEqual((status, len(json.loads(body)["figures"])), (200, 1))
                status, mime, body = get("/api/assets/" + data["figures"][0]["id"])
                self.assertEqual((status, mime, body[:4]), (200, "image/png", b"\x89PNG"))
                self.assertEqual(get("/api/assets/0123456789abcdef")[0], 404)
                self.assertEqual(get("/api/assets/../../main.tex")[0], 404)
                if sys.platform == "darwin" or shutil.which("pdftoppm"):
                    pdf = next(i for i in data["images"] if i["where"].endswith(".pdf"))
                    status, mime, body = get("/api/assets/" + pdf["id"])
                    self.assertEqual((status, body[:4]), (200, b"\x89PNG"))
            finally:
                server.shutdown()

    @unittest.skipUnless(HAS_TEX and (sys.platform == "darwin" or shutil.which("pdftoppm")), "Needs TeX.")
    def test_ai_builds_floats_author_instructs_and_confirms(self):
        import paperroom
        import paperroom_mcp as mcp
        from contextlib import closing
        from unittest.mock import patch
        before = sorted(p.relative_to(self.project) for p in self.project.rglob("*") if ".paperroom" not in p.parts)
        call = lambda name, **a: json.loads(json.dumps(mcp.invoke(name, {"project": str(self.project), **a})))
        first = call("publish_floats")
        self.assertEqual(sorted((f["key"], f["physical"]) for f in first["floats"]), [("fig:runs", 1), ("tab:runs", 1)])
        after = sorted(p.relative_to(self.project) for p in self.project.rglob("*") if ".paperroom" not in p.parts)
        self.assertEqual(before, after)
        with closing(paperroom.connect(workspace_server.database_path(self.project))) as db:
            assets.add_note(db, self.project, "tab:runs", "Add a column for the standard deviation.")
            assets.add_note(db, self.project, "new", "Add a figure of the convergence curve.")
            shown = seen(assets.state(db, self.project), "fig:runs")
            state = assets.confirm(db, self.project, "fig:runs", True, **shown)
            self.assertFalse(state["confirmed"]["fig:runs"]["changed"])
            withdrawn = assets.withdraw(db, self.project, 2)
            self.assertEqual([n["status"] for n in withdrawn["notes"]], ["open", "withdrawn"])
        status = call("workspace_status")["floats"]
        self.assertEqual([r["id"] for r in status["open_requests"]], [1])
        self.assertFalse(status["latest_build"]["stale"])
        # The author's message brings the open instruction to the AI.
        hook = subprocess.run([sys.executable, str(ROOT / "plugins/paperroom/runtime/tex_gate.py")],
                              input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "go", "cwd": str(self.project)}),
                              capture_output=True, text=True, timeout=30)
        context = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("#1 表 1 · tab:runs", context)
        self.assertIn("publish_floats", context)
        # The AI edits the table, rebuilds and answers.
        (self.project / "sections/table.tex").write_text(TABLE.replace("{lr}", "{lrr}").replace("76 \\\\", "76 & 3 \\\\"))
        self.assertTrue(call("workspace_status")["floats"]["latest_build"]["stale"])
        with self.assertRaisesRegex(Exception, "尚未处理"):
            call("publish_floats", responses=[{"request": 2, "text": "Done."}])
        second = call("publish_floats", responses=[{"request": 1, "text": "Added the SD column."}])
        self.assertEqual((second["build"], second["open_requests"]), (2, []))
        with closing(paperroom.connect(workspace_server.database_path(self.project))) as db:
            state = assets.state(db, self.project)
            self.assertEqual((state["notes"][0]["status"], state["notes"][0]["answered_build"]), ("done", 2))
            # Confirmation stays, and shows that the figure is unchanged; editing it would flag it.
            self.assertFalse(state["confirmed"]["fig:runs"]["changed"])
            (self.project / "main.tex").write_text(MAIN.replace("Evaluations for", "Exact evaluations for"))
            self.assertTrue(assets.state(db, self.project)["confirmed"]["fig:runs"]["changed"])

    def test_author_actions_and_build_pages_over_http(self):
        from contextlib import closing
        import paperroom
        with closing(paperroom.connect(workspace_server.database_path(self.project))) as db:
            assets._tables(db)
            db.execute("INSERT INTO v2_float_builds VALUES (1, ?)", (json.dumps(dict(
                build=1, created="2026-11-18T00:00:00+00:00", origin="ai", digest="x", pages=[1], floats=[], main="main.tex")),))
            db.execute("INSERT INTO v2_float_pages VALUES (1, 1, ?)", (b"\x89PNG page",))
            db.commit()
        token = secrets.token_urlsafe(8)
        handler = workspace_server.handler_for(workspace_server.database_path(self.project), token, self.project)
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                host = f"127.0.0.1:{server.server_port}"
                def request(method, path, body=None, headers=None):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=60)
                    connection.request(method, path, body=body, headers=headers or {})
                    response = connection.getresponse()
                    return response.status, response.read()
                self.assertEqual(request("GET", "/api/floats/1/pages/1"), (200, b"\x89PNG page"))
                self.assertEqual(request("GET", "/api/floats/1/pages/2")[0], 404)
                post = lambda data, tok=token: request("POST", "/api/workspace", json.dumps(data).encode(), {
                    "Content-Type": "application/json", "Origin": "http://" + host, "X-Paperroom-Token": tok})
                self.assertEqual(post({"action": "float_note", "target": "tab:runs", "text": "Wider."}, "wrong")[0], 403)
                status, body = post({"action": "float_note", "target": "tab:runs", "text": "Wider."})
                self.assertEqual((status, json.loads(body)["floats"]["notes"][0]["label"]), (200, "表 1 · tab:runs"))
                self.assertEqual(post({"action": "float_note", "target": "missing", "text": "x"})[0], 409)
                # This build placed no floats, so the card showed the table's source as loaded.
                listed = json.loads(request("GET", "/api/assets")[1])
                digest = next(t for t in listed["tables"] if t["key"] == "tab:runs")["digest"]
                self.assertEqual(post({"action": "float_confirm", "target": "tab:runs", "confirmed": True})[0], 409)
                self.assertEqual(post({"action": "float_confirm", "target": "tab:runs", "confirmed": True,
                                       "build": 1, "digest": digest})[0], 409)
                status, body = post({"action": "float_confirm", "target": "tab:runs", "confirmed": True,
                                     "build": None, "digest": digest})
                self.assertIn("tab:runs", json.loads(body)["floats"]["confirmed"])
                status, body = request("GET", "/api/assets")
                self.assertEqual(json.loads(body)["floats"]["build"]["build"], 1)
            finally:
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
