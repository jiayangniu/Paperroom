"""Chinese/English: catalog, backend messages, MCP and hooks, and full English UI coverage."""
from contextlib import closing
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(ROOT / "tests"))
import activation
import i18n
import latex_source
import outline
import paperroom
import paperroom_mcp as mcp
import section_review
import workspace_server
from test_document_reader import chrome, free_port

INTRO = ["Exact evaluations dominate the cost of many searches, so a cheaper route to the target matters.",
         "We ask whether screening reduces the exact evaluations needed to reach a fixed target."]
MAIN = r"""\documentclass{article}
\begin{document}
\section{Introduction}
%s

%s
\begin{figure}\caption{Evaluations per run.}\label{fig:runs}\end{figure}
\section{Results}
\begin{table}\caption{Paired runs.}\label{tab:runs}\begin{tabular}{l}x\end{tabular}\end{table}
Results text.
\end{document}
"""


class CatalogTest(unittest.TestCase):
    def test_patterns_compile_and_messages_translate(self):
        data = json.loads((RUNTIME / "i18n_en.json").read_text())
        for pattern, template in data["patterns"]:
            re.compile(pattern)
            self.assertNotRegex(template, "[一-鿿]")
        self.assertFalse([v for v in data["exact"].values() if re.search("[一-鿿]", v) and v != "中文"])
        cases = {
            activation.NOT_MANAGED: "This directory has no Paperroom workspace. Call activate_project only when the author explicitly asks Paperroom to manage this manuscript.",
            activation.NOT_SELECTED: "This manuscript's Paperroom workspace has not been selected in this conversation. Wait for the author to ask to open or use Paperroom.",
            "第 3 段 · 作者写的作用": "Paragraph 3 · 作者写的作用",
            "源码中本节有 3 段，作者大纲有 2 段（sections/intro.tex:1）。请让两者按顺序一一对应后再发布。":
                "The source has 3 paragraphs in this section and the author's plan has 2 (sections/intro.tex:1). Make them match in order before publishing.",
            "改前，main.tex 第 1 页，第 2 页": "Before, main.tex, page 1, page 2",
            "作者自己写的话": "作者自己写的话",
        }
        for zh, en in cases.items():
            self.assertEqual(i18n.translate(zh), en)
            self.assertEqual(i18n.translate(zh, "zh"), zh)

    def test_every_backend_message_has_an_english_form(self):
        """Literal messages in the runtime that reach the author or the AI are all covered."""
        import ast
        exact, patterns = i18n.catalog()
        skip = {"[⺀-鿿가-힯豈-﫿＀-￯\U00020000-\U000323af]", "摘要", "[引用]"}
        missing = []
        for source in RUNTIME.glob("*.py"):
            name = source.name
            for node in ast.walk(ast.parse(source.read_text())):
                if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and node.exc.args:
                    arg = node.exc.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.search("[一-鿿]", arg.value):
                        if arg.value not in skip and i18n.translate(arg.value) == arg.value:
                            missing.append(f"{name}:{node.lineno} {arg.value}")
        self.assertEqual(missing, [])


class LanguageChoiceTest(unittest.TestCase):
    def test_mcp_errors_and_gate_follow_the_author_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            with closing(paperroom.connect(workspace_server.database_path(project))) as db:
                outline.update_assets(db, project, 0, "Q?", "E.")
            args = {"project": str(project)}
            with patch.object(mcp, "show_author", return_value={"room_url": "test"}):
                opened = mcp.dispatch({"jsonrpc": "2.0", "id": 0, "method": "tools/call", "params": {
                    "name": "open_writing_workspace", "arguments": args}})["result"]
            request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "name": "bind_section_source", "arguments": {"project": str(project), "section": "missing", "tex": "main.tex"}}}
            with patch.dict(os.environ, {"LANG": "zh_CN.UTF-8", "PAPERROOM_LANG": ""}):
                self.assertEqual(mcp.dispatch(request)["result"]["content"][0]["text"], "请先选择论文大纲中的章节。")
                i18n.set_language(project, "en")
                self.assertEqual(mcp.dispatch(request)["result"]["content"][0]["text"],
                                 "Choose a section from the paper outline first.")
            def gate(event, name, arguments, **result):
                event_data = {"hook_event_name": event, "tool_name": name, "cwd": str(project), "session_id": "i18n",
                              "tool_input": arguments, **result}
                return subprocess.run([sys.executable, str(RUNTIME / "tex_gate.py")], input=json.dumps(event_data),
                                      capture_output=True, text=True, check=True, timeout=30,
                                      env={**os.environ, "PAPERROOM_STATE_DIR": str(project / ".gate")})
            gate("PostToolUse", "mcp__paperroom__open_writing_workspace", args, tool_response=opened)
            denied = gate("PreToolUse", "Write", {"file_path": str(project / "paper.md"), "content": "x"})
            reason = json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertTrue(reason.startswith("paper.md holds the author's three-level outline"), reason)
            self.assertNotRegex(reason, "[一-鿿]")


def fake_render_marked(main, source, select):
    page = (ROOT / "demo/examples/intro.png").read_bytes()
    located = {latex_source.START_MARK: 1, latex_source.END_MARK: 1,
               **{f"paperroom-float-{n}": 1 for n in range(8)}, **{f"paperroom-par-{n}-0": 1 for n in range(8)}}
    pages = select(located)
    return b"%PDF-1.4 test", [page] * len(pages), pages, located


class EnglishInterfaceTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node") and chrome() and paperroom.tex_available(),
                         "Needs Node.js, Chrome and a TeX engine.")
    def test_no_chinese_interface_text_is_left_in_english_mode(self):
        page = (ROOT / "demo/examples/intro.png").read_bytes()
        with tempfile.TemporaryDirectory(prefix="paperroom-english-") as folder, \
                patch.object(paperroom, "render_marked", fake_render_marked), \
                patch.object(paperroom, "render_document", return_value=(b"%PDF-1.4 test", [page])):
            project = Path(folder) / "paper"
            project.mkdir()
            (project / "main.tex").write_text(MAIN % tuple(INTRO))
            prepared = project / "paperroom-assets"
            (prepared / "figures").mkdir(parents=True)
            (prepared / "tables").mkdir()
            (prepared / "figures/原稿.png").write_bytes(page)
            from test_reference_pdf import two_page_pdf
            (prepared / "figures/comparison.pdf").write_bytes(two_page_pdf())
            # Files elsewhere in the paper are not part of the prepared gallery.
            (project / "private.png").write_bytes(page)
            # The author-chosen PDF name stays as written. Preparation inputs remain off the list.
            (prepared / "tables/保留.pdf").write_bytes(two_page_pdf())
            (prepared / "tables/runs.csv").write_text("label,value\ncode,1\n")
            (prepared / "tables/runs.tex").write_text(r"\begin{tabular}{l}A\end{tabular}")
            with closing(paperroom.connect(workspace_server.database_path(project))) as db:
                state = outline.update_assets(db, project, 0, "保留", "图 1")
                state = outline.submit(db, project, state["version"], "paper", [
                    {"title": "Introduction", "purpose": "Pose the cost question"}, {"title": "Results", "purpose": "Report runs"},
                    # A section name that equals an interface word stays as the author wrote it.
                    {"title": "研究问题", "purpose": "保留"}])
                section = state["sections"][0]["id"]
                import versions
                versions.freeze_original(db, project)
                state = outline.submit(db, project, state["version"], "section",
                                       [{"purpose": "保留"}, {"purpose": "Question"}], section=section)
                ids = [p["id"] for p in state["sections"][0]["paragraphs"]]
                for pid in ids:
                    state = outline.submit(db, project, state["version"], "paragraph", ["Say it plainly."],
                                           section=section, paragraph=pid)
                    section_review.save_paragraph_draft(db, project, section, pid, 1)
                versions.save(db, project, label="初稿")
                versions.submit_review(db, 1, [
                    {"kind": "change", "page": 1, "section": section, "paragraph": ids[1], "text": "Narrow the question."},
                    {"kind": "keep", "page": 1, "pin": {"x": .5, "y": .5}, "text": "Good opening."}])
                (project / "main.tex").write_text(MAIN % (INTRO[0], INTRO[1] + " Only three runs are reported."))
                section_review.save_paragraph_draft(db, project, section, ids[1], 1, expected_version=1)
                versions.save(db, project, expected=1, responses=[
                    {"note": 1, "status": "changed", "text": "Narrowed."}, {"note": 2, "status": "kept", "text": "Kept."}])
                import assets
                assets.build(db, project, "ai")
                assets.add_note(db, project, "tab:runs", "Add a column.")
                built = assets.state(db, project)["build"]
                placed = next(f for f in built["floats"] if f["key"] == "fig:runs")
                assets.confirm(db, project, "fig:runs", True, build=built["build"], digest=placed["digest"])
            handler = workspace_server.handler_for(workspace_server.database_path(project), secrets.token_urlsafe(16), project)
            with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    run = subprocess.run(["node", str(ROOT / "tests/browser/english.mjs"), chrome(),
                                          f"http://127.0.0.1:{server.server_port}/workspace", section, ids[0], str(free_port())],
                                         capture_output=True, text=True, timeout=180,
                                         env={**os.environ, "PAPERROOM_BROWSER_TMP": folder})
                finally:
                    server.shutdown()
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("ok no Chinese interface text left", run.stdout)
            # The switch is remembered for the AI's messages too.
            self.assertEqual(i18n.chosen(project), "en")


if __name__ == "__main__":
    unittest.main()
