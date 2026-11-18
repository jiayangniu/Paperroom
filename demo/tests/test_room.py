import http.client
import json
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import paperroom as pr
from room_server import handler_for
from install import install


class BrowserRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "state.sqlite3"
        self.handler = handler_for(self.path, "form-token")

    def request(self, method, route, data=None, origin="http://127.0.0.1:8765"):
        client, server = socket.socketpair()
        body = json.dumps(data).encode() if data is not None else b""
        def handle():
            with server:
                self.handler(server, ("127.0.0.1", 0), SimpleNamespace(server_port=8765))
        t = threading.Thread(target=handle)
        t.start()
        with client:
            client.sendall((f"{method} {route} HTTP/1.0\r\nHost: 127.0.0.1:8765\r\n"
                            f"Origin: {origin}\r\nX-Paperroom-Token: form-token\r\n"
                            f"Content-Length: {len(body)}\r\n\r\n").encode()+body)
            response = http.client.HTTPResponse(client)
            response.begin()
            packet = response.read()
        t.join(3)
        self.assertFalse(t.is_alive())
        return response.status, packet

    def test_browser_submits_and_state_is_visible_to_agent(self):
        with closing(pr.connect(self.path)) as db:
            job = pr.start(db, "Intro", "ref", 1, 1, True)
        self.assertIn(b"form-token", self.request("GET", "/")[1])
        self.assertEqual(json.loads(self.request("GET", "/api/tasks")[1])[0]["id"], job["id"])
        info = dict(id=job["id"], version=1, answers=["第一句介绍任务，第二句给出限制。"])
        self.assertEqual(self.request("POST", "/api/author", info, "https://elsewhere.invalid")[0], 403)
        self.assertEqual(self.request("POST", "/api/author", info)[0], 200)
        self.assertEqual(self.request("POST", "/api/author", info)[0], 409)
        with closing(pr.connect(self.path)) as db:
            state = pr.get(db, job["id"])
            self.assertEqual(state["phase"], "ready")
            png = (pr.HERE/"examples"/"intro.png").read_bytes()
            pr.publish(db, job["id"], state["version"], b"tex", [png])
        status, image = self.request("GET", f"/image/{job['id']}/1/1")
        self.assertEqual((status, image), (200, png))
        self.assertEqual(self.request("POST", "/api/author", dict(id=job["id"], version=3,
                         answers=["P2 的范围应限定。"]))[0], 200)

    def test_install_preserves_existing_instructions_on_repeat(self):
        root = Path(self.tmp.name)
        (root/"CLAUDE.md").write_text("Keep my rules.")
        install(root)
        install(root)
        self.assertEqual((root/"CLAUDE.md").read_text().count("@paperroom_tool/AGENTS.md"), 1)
        self.assertTrue((root/"CLAUDE.md").read_text().startswith("Keep my rules."))
        self.assertTrue((root/"paperroom_tool"/"room.html").is_file())
