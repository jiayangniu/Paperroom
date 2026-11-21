"""Explicit project selection on real MCP stdio and Code hook boundaries."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"


class Activation(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.a, self.b = self.root / "A", self.root / "B"
        self.a.mkdir()
        self.b.mkdir()
        self.env = {**os.environ, "PAPERROOM_STATE_DIR": str(self.root / "state"),
                    "PAPERROOM_ROOM": "off", "PAPERROOM_CLIENT": "code"}

    def server(self, client):
        proc = subprocess.Popen([sys.executable, str(RUNTIME / "paperroom_mcp.py")], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True, env={**self.env, "PAPERROOM_CLIENT": client})
        def stop():
            proc.stdin.close()
            proc.wait(timeout=10)
            proc.stdout.close()
        self.addCleanup(stop)
        return proc

    def call(self, proc, name, project=None, *, fails=False, **kwargs):
        args = {"project": str(project), **kwargs} if project is not None else kwargs
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        result = json.loads(proc.stdout.readline())["result"]
        self.assertEqual(bool(result.get("isError")), fails, result)
        return result if fails else json.loads(result["content"][0]["text"])

    def hook(self, session, name, args, *, event="PreToolUse", response=None):
        event = {"session_id": session, "hook_event_name": event, "tool_name": name,
                 "cwd": str(self.root), "tool_input": args, "tool_response": response}
        proc = subprocess.run([sys.executable, str(RUNTIME / "tex_gate.py")], input=json.dumps(event),
                              capture_output=True, text=True, env=self.env, check=True, timeout=15)
        return json.loads(proc.stdout) if proc.stdout else None

    def test_only_explicit_enrollment_creates_files_and_local_connections_select_one_root(self):
        first, other = self.server("code"), self.server("code")
        self.call(first, "get_usage")
        self.call(first, "open_writing_workspace", self.a, fails=True)
        self.call(first, "begin_writing", self.a, title="Method", fails=True)
        self.call(first, "suggest_section_plan", self.a, section="absent", text="hint", fails=True)
        self.assertEqual(list(self.a.iterdir()), [])
        self.assertFalse((self.root / "state").exists())
        a = self.call(first, "activate_project", self.a)
        self.assertEqual(a["project_path"], str(self.a))
        self.assertFalse(a.get("browser_open_requested"))
        self.assertNotIn("outline", a)
        self.call(first, "update_research_assets", self.a, version=0, question="Question A", evidence="Evidence A")
        self.call(other, "workspace_status", self.a, fails=True)
        self.call(other, "open_writing_workspace", self.a)
        self.call(first, "activate_project", self.b)
        self.call(first, "workspace_status", self.a, fails=True)
        self.assertEqual(self.call(other, "workspace_status", self.a)["outline"]["question"], "Question A")
        self.assertEqual(self.call(first, "workspace_status", self.b)["outline"]["question"], "")

    def test_desktop_shared_server_requires_this_chats_handle_and_the_same_root(self):
        chat = self.server("claude-chat")
        a = self.call(chat, "activate_project", self.a)
        b = self.call(chat, "activate_project", self.b)
        token = a["workspace_session"]
        self.assertNotEqual(token, b["workspace_session"])
        self.assertNotIn(token, a.get("room_url", ""))
        args = dict(version=0, question="Private A", evidence="A data")
        self.call(chat, "update_research_assets", self.a, fails=True, **args)
        self.call(chat, "update_research_assets", self.a, workspace_session=b["workspace_session"], fails=True, **args)
        self.call(chat, "update_research_assets", self.a, workspace_session=token, **args)
        again = self.call(chat, "open_writing_workspace", self.a)
        self.assertNotEqual(token, again["workspace_session"])
        self.assertEqual(self.call(chat, "workspace_status", self.a, workspace_session=token)["outline"]["question"], "Private A")
        after_restart = self.server("claude-chat")
        self.call(after_restart, "workspace_status", self.a, workspace_session=token, fails=True)
        for f in self.root.rglob("*"):
            if f.is_file():
                self.assertNotIn(token.encode(), f.read_bytes())

    def test_hook_selection_uses_host_session_and_only_successful_mcp_receipts(self):
        code = self.server("code")
        a = self.call(code, "activate_project", self.a)
        b = self.call(code, "activate_project", self.b)
        def edit(session, path):
            return self.hook(session, "Write", {"file_path": str(path / "paper.md"), "content": "words"})
        def select(session, project, result):
            wrapper = {"content": [{"type": "text", "text": json.dumps(result)}]}
            self.hook(session, "mcp__plugin_paperroom_paperroom__open_writing_workspace", {"project": str(project)},
                      event="PostToolUse", response=wrapper)
        self.assertIsNone(edit("one", self.a))
        select("one", self.a, b)
        select("one", self.a, {"isError": True, "content": a})
        self.assertIsNone(edit("one", self.a))
        select("one", self.a, a)
        select("two", self.b, b)
        self.assertIsNotNone(edit("one", self.a))
        self.assertIsNone(edit("two", self.a))
        self.assertIsNotNone(edit("two", self.b))
        self.assertIsNone(edit("one", self.b))
        self.assertIsNotNone(self.hook("two", "mcp__paperroom__update_research_assets", {"project": str(self.a)}))
        self.assertIsNone(self.hook("two", "mcp__paperroom__update_research_assets", {"project": str(self.b)}))
        select("one", self.b, b)
        self.assertIsNone(edit("one", self.a))
        self.assertIsNotNone(edit("one", self.b))
        self.hook("one", "", {}, event="SessionEnd")
        self.assertIsNone(edit("one", self.b))
        self.assertIsNotNone(edit("two", self.b))
