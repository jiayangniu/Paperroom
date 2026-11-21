"""Level 1 drafted by the AI and adopted by the author; levels 2-3 written by the
author beside an optional AI reference. Synthetic projects in temporary folders."""
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
import i18n
import journal
import outline
import paperroom
import paperroom_mcp as mcp
import workspace_server
from test_document_reader import chrome, free_port

SECTIONS = [{"title": "Introduction", "purpose": "Pose the cost question."},
            {"title": "Method", "purpose": "Describe the screening rule."}]


class Project:
    def __init__(self, test):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.call("activate_project")
        with self.db() as db:
            outline.update_assets(db, self.root, 0, "Does screening save evaluations?", "Three paired runs.")

    def db(self):
        return closing(paperroom.connect(workspace_server.database_path(self.root)))

    def call(self, name, **args):
        with patch.object(mcp, "show_author", return_value={"room_url": "test"}):
            return json.loads(json.dumps(mcp.invoke(name, {"project": str(self.root), **args})))

    def state(self):
        with self.db() as db:
            return outline.state(db, self.root)

    def propose(self, sections, **extra):
        return self.call("propose_paper_outline", version=self.state()["version"], sections=sections, **extra)["outline"]

    def events(self):
        with self.db() as db:
            return [e["kind"] for e in journal.events(db)]


class ProposalAndAdoption(unittest.TestCase):
    def test_paragraph_plans_open_only_after_adoption(self):
        paper = Project(self)
        state = paper.propose(SECTIONS)
        self.assertEqual([(s["title"], s["adopted"], s["planned"]) for s in state["sections"]],
                         [("Introduction", False, False), ("Method", False, False)])
        intro = state["sections"][0]["id"]
        with paper.db() as db, self.assertRaisesRegex(ValueError, "采用"):
            outline.submit(db, paper.root, state["version"], "section", [{"purpose": "Cost."}], section=intro)
        with patch.object(mcp, "show_author", return_value={}) as shown:
            mcp.invoke("open_writing_workspace", {"project": str(paper.root)})
        self.assertEqual(shown.call_args.kwargs["query"]["view"], "paper")
        with paper.db() as db:
            state = outline.adopt(db, paper.root, state["version"])
            self.assertTrue(all(s["adopted"] for s in state["sections"]))
            with self.assertRaisesRegex(ValueError, "没有待采用"):
                outline.adopt(db, paper.root, state["version"])
            state = outline.submit(db, paper.root, state["version"], "section", [{"purpose": "Cost."}], section=intro)
        self.assertTrue(state["sections"][0]["planned"])
        self.assertEqual(paper.events(), ["paper_outline_proposed", "paper_outline_adopted", "section_outline"])
        # paper.md records the adoption beside each section.
        text = (paper.root / "paper.md").read_text()
        self.assertEqual(len(re.findall(r"<!-- paperroom:section [0-9a-f]{12} \S+ [0-9a-f]{64} -->", text)), 2)

    def test_redrafts_keep_adoption_where_nothing_changed(self):
        paper = Project(self)
        state = paper.propose(SECTIONS)
        with paper.db() as db:
            outline.adopt(db, paper.root, state["version"])
        ids = [s["id"] for s in state["sections"]]
        state = paper.propose([{"id": ids[0], **SECTIONS[0]},
                               {"id": ids[1], "title": "Method", "purpose": "Describe the rule and its cost model."},
                               {"title": "Results", "purpose": "Report the runs."}])
        self.assertEqual([s["adopted"] for s in state["sections"]], [True, False, False])

    def test_the_author_editing_the_draft_adopts_it(self):
        paper = Project(self)
        state = paper.propose(SECTIONS)
        items = [{"id": s["id"], "title": s["title"], "purpose": s["purpose"]} for s in state["sections"]]
        items[1]["purpose"] = "My own wording for the method."
        with paper.db() as db:
            state = outline.submit(db, paper.root, state["version"], "paper", items)
        self.assertTrue(all(s["adopted"] for s in state["sections"]))

    def test_planned_sections_change_only_when_the_author_agreed(self):
        paper = Project(self)
        state = paper.propose(SECTIONS)
        intro, method = (s["id"] for s in state["sections"])
        with paper.db() as db:
            state = outline.adopt(db, paper.root, state["version"])
            outline.submit(db, paper.root, state["version"], "section", [{"purpose": "Cost."}], section=intro)
        for sections in ([{"id": method, **SECTIONS[1]}],
                         [{"id": intro, "title": "Introduction", "purpose": "Another role."}, {"id": method, **SECTIONS[1]}]):
            with self.assertRaisesRegex(ValueError, "reopen"):
                paper.propose(sections)
        state = paper.propose([{"id": intro, "title": "Introduction", "purpose": "Another role."},
                               {"id": method, **SECTIONS[1]}], reopen=[intro])
        self.assertEqual([(s["adopted"], s["planned"]) for s in state["sections"]], [(False, False), (True, False)])
        # The author's paragraph plan is kept, waiting for re-adoption and review.
        self.assertEqual([p["purpose"] for p in state["sections"][0]["paragraphs"]], ["Cost."])

    def test_outlines_written_before_adoption_existed_count_as_adopted(self):
        paper = Project(self)
        with paper.db() as db:
            state = outline.submit(db, paper.root, paper.state()["version"], "paper", SECTIONS)
        path = paper.root / "paper.md"
        old = re.sub(r"(<!-- paperroom:section [0-9a-f]{12} \S+) [0-9a-f]{64} -->", r"\1 -->", path.read_text())
        path.write_text(old)
        self.assertTrue(all(s["adopted"] for s in paper.state()["sections"]))

    def test_the_ai_cannot_adopt_the_paper_outline_or_edit_paper_md(self):
        names = {t["name"] for t in mcp.TOOLS}
        self.assertFalse({name for name in names if "adopt" in name})
        paper = Project(self)
        paper.propose(SECTIONS)
        with tempfile.TemporaryDirectory() as session_state, patch.dict(os.environ, {"PAPERROOM_STATE_DIR": session_state}):
            mcp.activation.bind_session("test-conversation", paper.root)
            event = {"session_id": "test-conversation", "hook_event_name": "PreToolUse", "tool_name": "Write",
                     "cwd": str(paper.root), "tool_input": {"file_path": str(paper.root / "paper.md"), "content": "x"}}
            gate = subprocess.run([sys.executable, str(RUNTIME / "tex_gate.py")], capture_output=True, text=True,
                                  check=True, timeout=30, input=json.dumps(event),
                                  env={**os.environ, "LANG": "zh_CN.UTF-8", "PAPERROOM_LANG": ""})
        reason = json.loads(gate.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("propose_paper_outline", reason)


class SectionForm(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Needs Node.js.")
    def test_section_save_submits_only_the_author_outline(self):
        html = (RUNTIME / "workspace.html").read_text()
        functions = html[html.index("function footer("):html.index("function assetsView(")]
        functions += html[html.index("function cleanForm("):html.index("function dataUrl(")]
        subprocess.run(["node", "-e", functions + r"""
            const assert = require("node:assert/strict");
            const route = {view:"section", section:"s", paragraph:""};
            const model = {base:5, fields:{items:[{id:"p", purpose:" My own plan. "}]}};
            const sec = () => ({}), sectionRows = () => [], esc = s => s;
            const buttons = footer("Save paragraph plan").match(/<button[^>]*>[^<]*<\/button>/g);
            assert.equal(buttons.length, 1);
            assert.match(buttons[0], /type="submit".*>Save paragraph plan</);
            assert.deepEqual(cleanForm(), {action:"outline", level:"section", version:5,
                section:"s", paragraph:"", items:[{id:"p", purpose:"My own plan."}]});
        """], check=True, capture_output=True, text=True)


class SectionReference(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Needs Node.js.")
    def test_structured_hint_preserves_labels_and_escapes_source(self):
        html = (RUNTIME / "workspace.html").read_text()
        renderer = html[html.index("function referenceInline"):html.index("function outlineReferencePanel")]
        escape = re.search(r"^const esc = .+;$", html, re.M)[0]
        source = """
        const hint = "（读前说明）\\n\\n逻辑链：成本 → 收益。\\n### A. First\\n– P1 Setup: x < y.\\n" +
                     "- P2 Evidence: **数字**\\n### B. Second\\n– P1 Another: A‖B(θ).\\n" +
                     "1. <literal>\\n2. Evidence.\\n";
        const rendered = formatReference(hint);
        const assert = require("node:assert/strict");
        assert.match(rendered, /class="reference-note"/);
        assert.match(rendered, /class="reference-logic"/);
        assert.match(rendered, /<h3>A. First<\\/h3>/);
        assert.equal((rendered.match(/class="reference-role"/g)||[]).length,3);
        assert.match(rendered, /x &lt; y/);
        assert.match(rendered, /<strong>数字<\\/strong>/);
        assert.match(rendered, /<ol><li value="1">&lt;literal&gt;/);
        """
        source += r"""
        assert.match(referenceInline(String.raw`$\Delta=r-p$`), /<math /);
        assert.match(referenceInline(String.raw`\[x_i^2\]`), /display="block"/);
        assert.match(referenceInline(String.raw`$\manuscriptMacro$`), /\\manuscriptMacro/);
        """
        subprocess.run(["node", "-e", "const katex=require(process.argv[1]);\n" + escape + "\n" + renderer + "\n" + source,
                        str(RUNTIME / "katex.min.js")], check=True, capture_output=True, text=True)

    def test_reference_is_shown_and_logged_but_never_translated(self):
        paper = Project(self)
        intro = paper.propose(SECTIONS)["sections"][0]["id"]
        state = paper.call("suggest_section_plan", section=intro, text="保留：先讲代价，再提问题。")["outline"]
        self.assertEqual(state["sections"][0]["hint"]["text"], "保留：先讲代价，再提问题。")
        self.assertEqual(paper.events(), ["paper_outline_proposed", "section_hint"])
        i18n.set_language(paper.root, "en")
        status = paper.call("workspace_status")
        self.assertEqual(status["outline"]["sections"][0]["hint"]["text"], "保留：先讲代价，再提问题。")
        with self.assertRaisesRegex(ValueError, "章节"):
            paper.call("suggest_section_plan", section="missing", text="x")


class AdoptInTheBrowser(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node") and chrome(), "Needs Node.js and Chrome.")
    def test_adopt_then_plan_beside_the_reference(self):
        self.run_browser("zh")

    @unittest.skipUnless(shutil.which("node") and chrome(), "Needs Node.js and Chrome.")
    def test_the_same_in_english(self):
        self.run_browser("en")

    def run_browser(self, lang):
        paper = Project(self)
        i18n.set_language(paper.root, lang)
        intro = paper.propose(SECTIONS)["sections"][0]["id"]
        hint = ("逻辑链：从成本到实验。\n\n### A. Screening\n"
                "– P1 Cost: Motivate the cost of exact evaluations. Keep $r - p$ and A‖B(θ).\n"
                "- P2 Checks: Present the control.\n\n### B. Results\n"
                "– P1 Evidence: Report <literal> observations.\n\n" +
                "\n\n".join("More detail " + str(i) for i in range(50)))
        paper.call("suggest_section_plan", section=intro, text=hint)
        handler = workspace_server.handler_for(workspace_server.database_path(paper.root), secrets.token_urlsafe(16), paper.root)
        with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                run = subprocess.run(["node", str(ROOT / "tests/browser/adopt.mjs"), chrome(),
                                      f"http://127.0.0.1:{server.server_port}/workspace", intro, str(free_port()), lang],
                                     capture_output=True, text=True, timeout=180,
                                     env={**os.environ, "PAPERROOM_BROWSER_TMP": str(paper.root.parent)})
            finally:
                server.shutdown()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("ok paste blocked", run.stdout)
        self.assertTrue(all(s["adopted"] for s in paper.state()["sections"]))
        # The browser run ends by saving the author's paragraph plan.
        self.assertEqual(paper.events(), ["paper_outline_proposed", "section_hint", "paper_outline_adopted",
                                          "section_outline"])
        self.assertEqual([p["purpose"] for p in paper.state()["sections"][0]["paragraphs"]][:3],
                         ["Role 1", "Two continued", "Draft continues"])


if __name__ == "__main__":
    unittest.main()
