"""Write-time paragraph gate, driven with the hook payloads Claude Code and Codex send."""
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import outline
import paperroom
from workspace_server import database_path

OLD_1 = "Each exact evaluation can dominate the cost of a search, which is why we count them carefully in every run."
OLD_2 = "We compare a screening rule with an unscreened search in three paired runs on the same benchmark suite."
NEW = ("Screening is assessed here through a separate cost model whose parameters come from earlier "
       "benchmarks rather than from the paired runs reported in the remainder of this paper.")
MAIN = r"""\documentclass{article}
\begin{document}
\begin{abstract}
We study screening.
\end{abstract}
\section{Introduction}
%s

%s
\section{Related Work}
Prior screening rules exist.
\end{document}
"""


class GateTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = Path(folder.name).resolve()
        self.main = self.project / "main.tex"
        self.write(OLD_1, OLD_2)
        with closing(paperroom.connect(database_path(self.project))) as db:
            state = outline.update_assets(db, self.project, 0, "Q?", "E.")
            state = outline.submit(db, self.project, state["version"], "paper",
                                   [{"title": "Introduction", "purpose": "Cost"}])
            section = state["sections"][0]["id"]
            state = outline.submit(db, self.project, state["version"], "section",
                                   [{"purpose": "a"}, {"purpose": "b"}], section=section)
            first = state["sections"][0]["paragraphs"][0]["id"]
            outline.submit(db, self.project, state["version"], "paragraph", ["s"], section=section, paragraph=first)
        self.data = Path(folder.name) / ".gate-data"
        self.hook({"hook_event_name": "PostToolUse", "tool_name": "mcp__paperroom__open_writing_workspace",
                   "tool_input": {"project": str(self.project)}, "tool_response": {
                       "paperroom_selected": True, "project_path": str(self.project)}})

    def write(self, first, second, main=MAIN):
        self.main.write_text(main % (first, second))

    def hook(self, payload, cwd=None):
        payload = {"session_id": "s", "cwd": str(cwd or self.project), "tool_use_id": "t1", **payload}
        run = subprocess.run([sys.executable, str(RUNTIME / "tex_gate.py")], input=json.dumps(payload),
                             capture_output=True, text=True, timeout=60,
                             env={"PATH": "/usr/bin:/bin", "PAPERROOM_STATE_DIR": str(self.data)})
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout) if run.stdout.strip() else None

    def edit(self, old, new, tool="Edit"):
        return self.hook({"hook_event_name": "PreToolUse", "tool_name": tool,
                          "tool_input": {"file_path": str(self.main), "old_string": old, "new_string": new}})

    def denied(self, result):
        return result and result["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_unrelated_chat_ignores_pre_upgrade_polish_requests(self):
        with closing(paperroom.connect(database_path(self.project))) as db, db:
            plan = outline.state(db, self.project)
            sid = plan["sections"][0]["id"]
            record = {"section": sid, "state": "requested", "request_id": "old"}
            db.execute("CREATE TABLE v2_section_polish (section TEXT PRIMARY KEY, details TEXT NOT NULL)")
            db.execute("INSERT INTO v2_section_polish VALUES (?, ?)", (sid, json.dumps(record)))
        self.assertIsNone(self.hook({"hook_event_name": "UserPromptSubmit", "prompt": "Discuss the data."}))

    def test_small_edits_pass_and_whole_paragraphs_need_intents(self):
        self.assertIsNone(self.edit("three paired runs", "four paired runs"))
        # Paragraph 2 has no sentence intents yet.
        result = self.edit(OLD_2, NEW)
        self.assertTrue(self.denied(result))
        self.assertIn("main.tex:9", result["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("第 2 段的逐句意图", result["hookSpecificOutput"]["permissionDecisionReason"])
        # Paragraph 1 is unlocked by the author's intents.
        self.assertIsNone(self.edit(OLD_1, NEW))
        # A whole paragraph in a section the author has not outlined.
        result = self.edit("Prior screening rules exist.", NEW)
        self.assertIn("不在作者的论文大纲里", result["hookSpecificOutput"]["permissionDecisionReason"])
        # A new abstract is prose too.
        self.assertTrue(self.denied(self.edit("We study screening.", NEW)))

    def test_small_steps_add_up_to_a_rewrite(self):
        long_old = " ".join(f"w{i}" for i in range(40))
        self.write(OLD_1, long_old)
        # Each step replaces about a third of the words: fine alone, a rewrite together.
        step_one = " ".join([f"a{i}" for i in range(14)] + [f"w{i}" for i in range(14, 40)])
        self.assertIsNone(self.edit(long_old, step_one))
        self.write(OLD_1, step_one)
        step_two = " ".join([f"a{i}" for i in range(14)] + [f"b{i}" for i in range(14, 28)] +
                            [f"w{i}" for i in range(28, 40)])
        result = self.edit(step_one, step_two)
        self.assertTrue(self.denied(result))

    def test_author_written_prose_can_be_polished(self):
        # The author typed this paragraph by hand; it has no lineage and no draft.
        self.write(OLD_1, NEW)
        self.assertIsNone(self.edit("paired runs reported", "paired runs presented"))

    def test_codex_patch_multiedit_write_and_paper_md(self):
        patch = ("*** Begin Patch\n*** Update File: main.tex\n@@\n " + "\\section{Introduction}" + "\n " + OLD_1 +
                 "\n \n-" + OLD_2 + "\n+" + NEW + "\n*** End Patch\n")
        result = self.hook({"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                            "tool_input": {"command": patch}})
        self.assertTrue(self.denied(result))
        multi = self.hook({"hook_event_name": "PreToolUse", "tool_name": "MultiEdit", "tool_input": {
            "file_path": str(self.main), "edits": [{"old_string": "three", "new_string": "four"},
                                                    {"old_string": OLD_2.replace("three", "four"), "new_string": NEW}]}})
        self.assertTrue(self.denied(multi))
        whole = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {
            "file_path": str(self.main), "content": MAIN % (OLD_1, NEW)}})
        self.assertTrue(self.denied(whole))
        outline_edit = self.hook({"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {
            "file_path": str(self.project / "paper.md"), "content": "faked intents"}})
        self.assertIn("paper.md", outline_edit["hookSpecificOutput"]["permissionDecisionReason"])

    def test_shell_writes_are_reported_after_the_fact(self):
        before = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "python3 x.py"}}
        after = dict(before, hook_event_name="PostToolUse", tool_response={})
        self.assertIsNone(self.hook(before))
        self.write(OLD_1, NEW)
        result = self.hook(after)
        self.assertEqual(result["decision"], "block")
        self.assertIn("撤回", result["reason"])
        self.write(OLD_1, OLD_2)
        self.assertIsNone(self.hook(before))
        (self.project / "paper.md").write_text((self.project / "paper.md").read_text() + "\nedited")
        self.assertIn("paper.md", self.hook(after)["reason"])

    def test_outside_paperroom_and_non_tex_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as other:
            plain = Path(other) / "main.tex"
            plain.write_text(MAIN % (OLD_1, OLD_2))
            self.assertIsNone(self.hook({"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {
                "file_path": str(plain), "content": MAIN % (OLD_1, NEW)}}, cwd=other))
        self.assertIsNone(self.hook({"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {
            "file_path": str(self.project / "notes.txt"), "content": NEW}}))
        # Malformed input never blocks the tool.
        self.assertIsNone(self.hook({"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                                     "tool_input": {"command": "*** Begin Patch\n*** Update File: missing.tex\n@@\n-x\n+y\n*** End Patch"}}))

    def test_mixed_patch_checks_the_selected_manuscript_whichever_file_comes_first(self):
        with tempfile.TemporaryDirectory() as other:
            elsewhere = Path(other) / "main.tex"
            # The first file belongs to another paper and has no matching hunk.
            patch = (f"*** Begin Patch\n*** Update File: {elsewhere}\n@@\n-other\n+outside\n"
                     f"*** Update File: {self.main}\n@@\n-{OLD_2}\n+{NEW}\n*** End Patch")
            self.assertTrue(self.denied(self.hook({"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
                                                   "tool_input": {"command": patch}})))

    def test_plugin_hook_file_matches_both_clients(self):
        hooks = json.loads((ROOT / "plugins/paperroom/hooks/hooks.json").read_text())["hooks"]
        pre = hooks["PreToolUse"][0]
        for tool in ("Edit", "Write", "apply_patch", "Bash"):
            self.assertIn(tool, pre["matcher"].split("|"))
        self.assertIn("runtime/tex_gate.py", pre["hooks"][0]["command"])
        self.assertEqual(hooks["PostToolUse"][0]["matcher"], "Bash")
        self.assertNotIn("UserPromptSubmit", hooks)


if __name__ == "__main__":
    unittest.main()
