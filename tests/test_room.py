"""The lasting workspace room: one background server per manuscript, found again by every client."""
import http.client
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import time
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "plugins/paperroom/runtime"
sys.path.insert(0, str(RUNTIME))
import paperroom_mcp as mcp
import room
from workspace_server import database_path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_document_reader import chrome, free_port
import shutil
import subprocess


def get(port, path, token=None, host=None, method="GET", origin=None, referer=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if token:
        headers["X-Paperroom-Token"] = token
    if origin:
        headers["Origin"] = origin
    if referer:
        headers["Referer"] = referer
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        return response.status, response.getheader("X-Paperroom-Version"), response.read()
    finally:
        connection.close()


def wait_until(check, seconds=6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


class RoomTests(unittest.TestCase):
    def setUp(self):
        state = tempfile.TemporaryDirectory(prefix="paperroom-state-")
        paper = tempfile.TemporaryDirectory(prefix="paperroom-paper-")
        self.addCleanup(state.cleanup)
        self.addCleanup(paper.cleanup)
        env = patch.dict(os.environ, {"PAPERROOM_STATE_DIR": state.name, "PAPERROOM_ROOM": "",
                                      "PAPERROOM_ROOM_IDLE": "600"})
        env.start()
        self.addCleanup(env.stop)
        self.project = Path(paper.name).resolve()
        self.addCleanup(self.stop_room)

    def stop_room(self):
        record = room.read_record(self.project)
        info = record and room.probe(record)
        if info:
            room.stop(record, info)
        for process in list(room.LAUNCHED):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            room.LAUNCHED.remove(process)

    def record(self):
        return room.read_record(self.project)

    def test_second_client_reuses_the_running_room(self):
        port = room.ensure(self.project, "1.0.0")
        first = self.record()
        self.assertEqual(room.ensure(self.project, "1.0.0"), port)
        self.assertEqual(self.record()["pid"], first["pid"])
        status, version, html = get(port, "/workspace")
        self.assertEqual((status, version), (200, "1.0.0"))
        self.assertIn(('window.roomToken=' + json.dumps(first["token"])).encode(), html)
        self.assertIn(b'window.paperroomVersion="1.0.0"', html)
        self.assertEqual(stat.S_IMODE(room.record_path(self.project).stat().st_mode), 0o600)

    def test_restart_keeps_the_address_so_an_open_page_reconnects(self):
        port = room.ensure(self.project, "1.0.0")
        before = self.record()
        os.kill(before["pid"], signal.SIGTERM)
        self.assertTrue(wait_until(lambda: room.probe(before) is None))
        self.assertEqual(room.ensure(self.project, "1.0.0"), port)
        after = self.record()
        self.assertNotEqual(after["pid"], before["pid"])
        self.assertEqual(after["token"], before["token"])
        # The page's embedded token still works against the new process.
        status, _, body = get(port, "/api/room", before["token"])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["pid"], after["pid"])

    def test_links_to_same_named_papers_only_open_their_own_room(self):
        first = self.project / "group-a" / "draft"
        second = self.project / "group-b" / "draft"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        ports = [room.ensure(paper, "1.0.0") for paper in (first, second)]
        for paper in (first, second):
            record = room.read_record(paper)
            self.addCleanup(room.stop, record, room.probe(record))
        self.assertNotEqual(*ports)
        for index, paper in enumerate((first, second)):
            link = urlsplit(room.workspace_url(paper, ports[index], {"view": "paper"}))
            status, _, html = get(ports[index], link.path + "?" + link.query)
            self.assertEqual(status, 200)
            self.assertIn(json.dumps(str(paper)).encode(), html)
            self.assertIn(json.dumps(paper.parent.name).encode(), html)
            other_port = ports[1 - index]
            self.assertEqual(get(other_port, link.path + "?" + link.query)[0], 409)
            self.assertEqual(get(other_port, "/api/workspace?" + link.query)[0], 409)
            stale_tab = room.workspace_url(paper, other_port)
            self.assertEqual(get(other_port, "/api/prepared-assets", referer=stale_tab)[0], 409)

    def test_newer_version_takes_over_and_older_never_replaces_it(self):
        port = room.ensure(self.project, "0.6.12")
        old = self.record()
        self.assertEqual(room.ensure(self.project, "0.6.13"), port)
        new = self.record()
        self.assertNotEqual(new["pid"], old["pid"])
        self.assertEqual(new["token"], old["token"])
        self.assertEqual(get(port, "/api/workspace")[1], "0.6.13")
        self.assertEqual(room.ensure(self.project, "0.6.12"), port)
        self.assertEqual(self.record()["pid"], new["pid"])

    def test_room_exits_after_idle_time(self):
        with patch.dict(os.environ, {"PAPERROOM_ROOM_IDLE": "1"}):
            room.ensure(self.project, "1.0.0")
        record = self.record()
        self.assertTrue(wait_until(lambda: room.probe(record) is None, 8))
        # The address is kept for the next start.
        self.assertEqual(room.ensure(self.project, "1.0.0"), record["port"])

    def test_room_controls_need_the_token_and_a_local_page(self):
        port = room.ensure(self.project, "1.0.0")
        token = self.record()["token"]
        self.assertEqual(get(port, "/api/room")[0], 403)
        self.assertEqual(get(port, "/api/room", token, host="evil.example:80")[0], 403)
        self.assertEqual(get(port, "/api/room/stop", token, method="POST", origin="http://evil.example")[0], 403)
        self.assertEqual(get(port, "/api/room/stop", method="POST")[0], 403)
        self.assertIsNotNone(room.probe(self.record()))

    def test_mcp_opens_the_lasting_room(self):
        with patch.dict(mcp.SERVERS, clear=True):
            opened = mcp.show_author(database_path(self.project), project=self.project,
                                     query={"view": "paper"}, open_browser=False)
        port = self.record()["port"]
        self.assertEqual(opened["room_url"], room.workspace_url(self.project, port, {"view": "paper"}))
        self.assertEqual(mcp.SERVERS, {})
        self.assertEqual(self.record()["version"], mcp.VERSION)

    def test_falls_back_to_an_in_process_server_when_the_room_cannot_start(self):
        with patch.dict(mcp.SERVERS, clear=True), \
                patch.object(room, "ensure", side_effect=RuntimeError("no background process")):
            opened = mcp.show_author(database_path(self.project), project=self.project, open_browser=False)
            server = mcp.SERVERS[database_path(self.project)]
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        self.assertEqual(opened["room_url"], room.workspace_url(self.project, server.server_port))


    @unittest.skipUnless(shutil.which("node") and chrome(), "Needs Node.js and Chrome.")
    def test_open_page_reconnects_after_restart_and_reloads_after_update(self):
        port = room.ensure(self.project, "1.0.0")
        page = subprocess.Popen(["node", str(Path(__file__).resolve().parent / "browser/room.mjs"), chrome(),
                                 f"http://127.0.0.1:{port}/workspace", str(free_port()), "1.0.1"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                env={**os.environ, "PAPERROOM_BROWSER_TMP": str(self.project.parent)})
        self.addCleanup(page.stdout.close)
        self.addCleanup(page.kill)
        def expect(marker):
            line = page.stdout.readline()
            self.assertTrue(line.startswith(marker), line + page.stdout.read() if not line else line)
        expect("ready 1.0.0")
        record = self.record()
        room.stop(record, room.probe(record))           # e.g. every chat window closed, then idle
        page.stdin.write("next\n"); page.stdin.flush()
        expect("offline")
        self.assertEqual(room.ensure(self.project, "1.0.0"), port)   # a new chat opens the workspace
        page.stdin.write("next\n"); page.stdin.flush()
        expect("reconnected")
        self.assertEqual(room.ensure(self.project, "1.0.1"), port)   # the plugin was updated
        page.stdin.write("next\n"); page.stdin.flush()
        expect("reloaded 1.0.1")
        page.stdin.close()
        self.assertEqual(page.wait(30), 0)


if __name__ == "__main__":
    unittest.main()
