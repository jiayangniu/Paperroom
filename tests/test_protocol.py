import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1]/"plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import paperroom_mcp as mcp


class ProtocolCases(unittest.TestCase):
    def test_native_launchers_and_real_stdio(self):
        plugin=RUNTIME.parent
        cc=json.loads((plugin/".mcp.json").read_text())["mcpServers"]["paperroom"]
        codex=json.loads((plugin/"codex.mcp.json").read_text())["mcpServers"]["paperroom"]
        commands=([cc["command"],cc["args"][0].replace("$"+"{CLAUDE_PLUGIN_ROOT}",str(plugin))],
                  [str(plugin/codex["command"])])
        with tempfile.TemporaryDirectory() as project:
            def envelope(n,m,p):return dict(jsonrpc="2.0",id=n,method=m,params=p)
            reqs=[envelope(1,"initialize",{"protocolVersion":"2025-06-18"}),
                  dict(jsonrpc="2.0",method="notifications/initialized"),envelope(2,"tools/list",{}),
                  envelope(3,"tools/call",{"name":"writing_status","arguments":{"project":project}})]
            for command in commands:
                result=subprocess.run(command,input="\n".join(map(json.dumps,reqs))+"\n",cwd=plugin,
                                      capture_output=True,text=True,check=True,timeout=12)
                ans=[json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual([x["id"] for x in ans],[1,2,3])
                self.assertEqual(ans[0]["result"]["protocolVersion"],"2025-06-18")
                names = {t["name"] for t in ans[1]["result"]["tools"]}
                self.assertEqual(names, {t["name"] for t in mcp.TOOLS})
                self.assertTrue({"workspace_status","open_writing_workspace","save_paragraph_draft","publish_section"} <= names)
                body=json.loads(ans[2]["result"]["content"][0]["text"])
                self.assertEqual(body,{"tasks":[]})
                self.assertFalse(list(Path(project).iterdir()))

    def test_auto_open_uses_bound_port_and_reuses_project_listener(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(mcp.SERVERS,clear=True), \
                patch.dict(os.environ, {"PAPERROOM_ROOM": "off"}):
            with patch.object(mcp,"ThreadingHTTPServer") as server, patch.object(mcp.threading,"Thread"), patch.object(mcp.webbrowser,"open",return_value=False) as opener:
                server.return_value.server_port=32791
                p=Path(temp)/"project.sqlite3"
                a=mcp.show_author(p,"abc")
                mcp.show_author(p,"def")
                self.assertEqual(server.call_count,1)
                self.assertEqual(server.call_args.args[0],("127.0.0.1",0))
                self.assertEqual(a,{"room_url":"http://127.0.0.1:32791/#abc","browser_open_requested":False})
                self.assertEqual(opener.call_count,2)

    def test_no_task_loss_when_viewer_is_unavailable(self):
        with tempfile.TemporaryDirectory() as t, patch.object(mcp,"show_author",side_effect=PermissionError("bind unavailable")):
            args={"project":t,"title":"Intro","reference":"outline discussion"}
            job=mcp.invoke("begin_writing",args)
            self.assertIn("room_error",job)
            self.assertEqual(job["outline"]["version"], 0)
            self.assertEqual(mcp.invoke("workspace_status",{"project":t})["outline"], job["outline"])
            self.assertFalse(list(Path(t).iterdir()))
