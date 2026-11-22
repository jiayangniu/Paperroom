"""Figures, tables and data indexed from the paper and served as previews."""
from contextlib import closing
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
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import assets
import paperroom
import workspace_server

HAS_TEX = paperroom.tex_available()
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
        prepared = self.project / "paperroom-assets/figures"
        prepared.mkdir(parents=True)
        for name in ("runs.png", "plot.pdf"):
            shutil.copyfile(self.project / "figs" / name, prepared / name)
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
                self.assertEqual(status, 200)
                items = {i["name"]: i for i in json.loads(body)["figures"]}
                self.assertEqual(set(items), {"runs.png", "plot.pdf"})
                status, mime, body = get(items["runs.png"]["preview_url"])
                self.assertEqual((status, mime, body[:4]), (200, "image/png", b"\x89PNG"))
                self.assertEqual(get("/api/assets/0123456789abcdef")[0], 404)
                self.assertEqual(get("/api/assets/../../main.tex")[0], 404)
                status, mime, body = get(items["plot.pdf"]["preview_url"])
                self.assertEqual((status, mime, body[:4]), (200, "application/pdf", b"%PDF"))
            finally:
                server.shutdown()

    @unittest.skipUnless(HAS_TEX and (sys.platform == "darwin" or shutil.which("pdftoppm")), "Needs TeX.")
    def test_old_build_remains_archived_without_reactivating_author_instructions(self):
        import paperroom
        import paperroom_mcp as mcp
        from contextlib import closing
        with closing(paperroom.connect(workspace_server.database_path(self.project))) as db:
            build = assets.build(db, self.project, "ai")["build"]
            assets.add_note(db, self.project, "new", "Add a convergence figure.")
            record = assets.build_record(db, build["build"])
            self.assertEqual({f["key"] for f in record["floats"]}, {"fig:runs", "tab:runs"})

        with patch.object(mcp, "show_author", return_value={"room_url": "local"}):
            mcp.invoke("open_writing_workspace", {"project": str(self.project)})
        status = mcp.invoke("workspace_status", {"project": str(self.project)})
        self.assertEqual(status["prepared_assets"]["figures"], 0)
        self.assertNotIn("floats", status)
        with self.assertRaisesRegex(ValueError, "Unknown tool"):
            mcp.invoke("publish_floats", {"project": str(self.project)})

    def test_archived_floats_and_retried_publish_keep_their_actual_build(self):
        def render(main, source, select):
            physical = 4 if "Paired runs." in source else 7
            located = {"paperroom-float-0": physical, "paperroom-float-1": physical}
            return f"pdf{physical}".encode(), [f"page{physical}".encode()], select(located), located

        with closing(paperroom.connect(workspace_server.database_path(self.project))) as db, patch.object(
                paperroom, "render_marked", side_effect=render) as compiler:
            assets.add_note(db, self.project, "tab:runs", "Explain the units.")
            reply = [{"request": 1, "text": "The table now states the units."}]
            v1 = assets.build(db, self.project, "ai", responses=reply, request_id="reply-01")["build"]
            (self.project / "sections/table.tex").write_text(TABLE.replace("Paired runs.", "Error rates."))
            v2 = assets.build(db, self.project, "author")["build"]
            self.assertEqual((v1["build"], v2["build"]), (1, 2))
            archived = assets.review_index(db, self.project, 1)
            self.assertEqual((archived["tables"][0]["caption"], archived["tables"][0]["physical"]),
                             ("Paired runs.", 4))
            self.assertEqual(archived["data"], [])
            self.assertIsNone(archived["floats"]["build"]["stale"])
            self.assertEqual([b["build"] for b in archived["floats"]["history"]], [2, 1])
            self.assertEqual(archived["floats"]["latest_build"], 2)
            self.assertEqual(archived["floats"]["notes"][0]["answered_build"], 1)
            self.assertEqual(assets.build_asset(db, 1), b"pdf4")
            self.assertEqual(assets.build_asset(db, 2, 1), b"page7")
            self.assertIsNone(assets.review_index(db, self.project, 99))
            replay = assets.build(db, self.project, "ai", responses=reply, request_id="reply-01")
            self.assertEqual((replay["build"]["build"], replay["latest_build"], compiler.call_count), (1, 2, 2))
            with self.assertRaises(ValueError):
                assets.build(db, self.project, "ai", request_id="reply-01")
            # A comment about the page actually reviewed remains pinned to it.
            assets.add_note(db, self.project, "tab:runs", "Look at the old page.", build=1,
                            digest=archived["tables"][0]["digest"])
            self.assertEqual(assets.open_requests(db)[0]["build"], 1)
            self.assertFalse(assets.review_index(db, self.project, 2)["floats"]["notes"])

    def test_parallel_ai_retries_create_one_build_and_answer_once(self):
        from concurrent.futures import ThreadPoolExecutor
        barrier = threading.Barrier(2)
        def render(main, source, select):
            barrier.wait(timeout=8)
            loc = {"paperroom-float-0": 1, "paperroom-float-1": 1}
            return b"pdf", [b"page"], select(loc), loc
        path = workspace_server.database_path(self.project)
        with closing(paperroom.connect(path)) as db:
            assets.add_note(db, self.project, "tab:runs", "Review this table.")
        def run():
            with closing(paperroom.connect(path)) as db:
                return assets.build(db, self.project, "ai", [{"request": 1, "text": "Updated."}], "same")["build"]["build"]
        with patch.object(paperroom, "render_marked", side_effect=render), ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(run) for _ in range(2)]
            self.assertEqual([f.result(timeout=12) for f in futures], [1, 1])
        with closing(paperroom.connect(path)) as db:
            state = assets.review_index(db, self.project)["floats"]
            self.assertEqual(len(state["history"]), 1)
            self.assertEqual(state["notes"][0]["answered_build"], 1)

    def test_source_changed_during_compile_does_not_claim_a_version_or_answer(self):
        (self.project / "main.tex").write_text(MAIN.replace("Paired runs", "Runs") +
                                              "\n% table input: data/runs.csv")
        def render(main, source, select):
            (self.project / "data/runs.csv").write_text("run,metric\n2,5\n")
            loc = {"paperroom-float-0": 1, "paperroom-float-1": 1}
            return b"pdf", [b"page"], select(loc), loc
        with closing(paperroom.connect(workspace_server.database_path(self.project))) as db, patch.object(
                paperroom, "render_marked", side_effect=render):
            assets.add_note(db, self.project, "tab:runs", "Refresh data.")
            with self.assertRaisesRegex(ValueError, "编译期间"):
                assets.build(db, self.project, "ai", [{"request": 1, "text": "Updated."}], "publish-once")
            self.assertIsNone(assets.state(db, self.project)["build"])
            self.assertEqual(assets.open_requests(db)[0]["id"], 1)

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
                code, raw = request("GET", "/api/assets?build=1")
                self.assertEqual((code, json.loads(raw)["tables"], json.loads(raw)["images"]), (200, [], []))
                self.assertEqual(request("GET", "/api/assets?build=99")[0], 404)
                self.assertEqual(request("GET", "/api/assets?build=latest")[0], 404)
                self.assertEqual(request("GET", "/api/floats/1/pages/1"), (200, b"\x89PNG page"))
                self.assertEqual(request("GET", "/api/floats/1/pages/2")[0], 404)
                post = lambda data, tok=token: request("POST", "/api/workspace", json.dumps(data).encode(), {
                    "Content-Type": "application/json", "Origin": "http://" + host, "X-Paperroom-Token": tok})
                self.assertEqual(post({"action": "float_note", "target": "tab:runs", "text": "Wider."}, "wrong")[0], 403)
                for action in ("float_note", "float_build", "float_withdraw", "float_confirm"):
                    self.assertEqual(post({"action": action})[0], 410)
                status, body = request("GET", "/api/prepared-assets")
                self.assertEqual(status, 200)
                self.assertNotIn("archive", json.loads(body))
            finally:
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
