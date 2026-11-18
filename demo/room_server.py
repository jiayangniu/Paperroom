"""Local author UI. Agent processes coordinate via the SQLite database."""
import json
import re
import secrets
import threading
import webbrowser
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from paperroom import HERE, connect, get, respond


def handler_for(database, token):
    class Room(BaseHTTPRequestHandler):
        def send_bytes(self, status, mime, content):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(content)

        def reply(self, content, status=200):
            self.send_bytes(status, "application/json; charset=utf-8",
                            json.dumps(content, ensure_ascii=False).encode())

        def local_host(self):
            port = self.server.server_port
            return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def do_GET(self):
            if not self.local_host():
                return self.reply({"error":"请使用本机地址。"}, 403)
            path = urlsplit(self.path).path
            if path == "/":
                html = (HERE / "room.html").read_text("utf-8").replace("/*SERVER_SETTINGS*/", "window.roomToken=" + json.dumps(token) + ";")
                return self.send_bytes(200, "text/html; charset=utf-8", html.encode())
            with closing(connect(database)) as db:
                if path == "/api/tasks":
                    return self.reply([json.loads(body) for (body,) in
                                       db.execute("SELECT body FROM tasks ORDER BY rowid DESC")])
                match = re.fullmatch(r"/image/([0-9a-f]{12})/(\d+)/([1-9]\d*)", path)
                if match:
                    row = db.execute("SELECT content FROM artifacts WHERE task=? AND revision=? AND page=?",
                                     match.groups()).fetchone()
                    if row:
                        return self.send_bytes(200, "image/png", row[0])
            self.reply({"error":"找不到内容。"}, 404)

        def do_POST(self):
            if not self.local_host() or self.headers.get("Origin") != "http://" + self.headers.get("Host", ""):
                return self.reply({"error":"请从本机写作页面提交。"}, 403)
            if self.headers.get("X-Paperroom-Token") != token:
                return self.reply({"error":"请重新加载小黑屋。"}, 403)
            if self.path != "/api/author":
                return self.reply({"error":"找不到操作。"}, 404)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("提交内容过长或为空。")
                payload = json.loads(self.rfile.read(size))
                with closing(connect(database)) as db:
                    job = respond(db, payload["id"], payload["version"], payload["answers"])
                self.reply(job)
            except (ValueError, TypeError, KeyError) as exc:
                self.reply({"error":str(exc)}, 409)

        def log_message(self, fmt, *args):
            pass
    return Room


def serve(database, port, open_browser):
    token = secrets.token_urlsafe(32)
    with ThreadingHTTPServer(("127.0.0.1", port), handler_for(database, token)) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Paperroom · {url}\n保持这个终端打开，在另一个终端启动 Codex 或 Claude Code。", flush=True)
        if open_browser:
            threading.Timer(.15, webbrowser.open, args=(url,)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
