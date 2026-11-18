"""Run the local Paperroom workspace and its browser-only author forms."""
import argparse
import hashlib
import json
import re
import secrets
import sqlite3
import subprocess
import sys
import webbrowser
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import outline
import paperroom as pr
import section_review
import timestamps
from room_server import handler_for as legacy_handler


def database_path(project):
    project = Path(project).resolve()
    legacy = project / "paperroom_tool/.paperroom/project.sqlite3"
    database = legacy if legacy.is_file() else project / ".paperroom/project.sqlite3"
    if not database.resolve().is_relative_to(project):
        raise ValueError("Paperroom 数据目录必须位于本论文项目内。")
    return database


def legacy_tasks(db):
    if db is None or not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'"
    ).fetchone():
        return []
    tasks = (json.loads(row[0]) for row in db.execute("SELECT body FROM tasks ORDER BY rowid DESC"))
    return [{key: task[key] for key in ("id", "title", "phase", "version")} for task in tasks]


def snapshot(db, project, section=None):
    plan = outline.state(db, project)
    ids = [item["id"] for item in plan["sections"]]
    archived = section_review.archived_sections(db, ids)
    archive_ids = [item["id"] for item in archived]
    choices = ids + archive_ids
    selected = section if section in choices else next(iter(choices), None)
    review = section_review.status(db, project, selected) if selected else None
    project_key = hashlib.sha256(str(Path(project).resolve()).encode("utf-8")).hexdigest()[:24]
    return {"project": project_key, "outline": plan, "section": selected, "review": review,
            "archived": archived, "legacy": legacy_tasks(db)}


def read_snapshot(project, section=None):
    path = database_path(project)
    if not path.is_file():
        return snapshot(None, project, section)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        return snapshot(db, project, section)


def author_action(db, project, data):
    if not isinstance(data, dict):
        raise ValueError("提交内容格式不正确。")
    action = data["action"]
    section = data.get("section")
    if action == "assets":
        outline.update_assets(db, project, data["version"], data["question"], data["evidence"],
                              affected_sections=data.get("affected_sections", []))
    elif action == "outline":
        outline.submit(db, project, data["version"], data["level"], data["items"],
                       section=section, paragraph=data.get("paragraph"))
    elif action == "reference":
        imported = section_review.import_reference(db, project, section, title=data.get("title"), tex=data.get("tex"),
                                                   pdf=data.get("pdf"), pages=data.get("pages", "all"))
        return {**snapshot(db, project, section), "reference_id": imported["reference_id"]}
    elif action == "review":
        section_review.submit_review(db, project, section, data["revision"], data["notes"])
    else:
        raise ValueError("找不到此表单操作。")
    return snapshot(db, project, section)


def handler_for(database, token, project):
    class Workspace(legacy_handler(database, token)):
        def do_GET(self):
            if not self.local_host():
                return self.reply({"error": "请使用本机地址。"}, 403)
            url = urlsplit(self.path)
            if url.path == "/workspace":
                template = (pr.HERE / "workspace.html").read_text("utf-8")
                html = template.replace("/*SERVER_SETTINGS*/", "window.roomToken=" + json.dumps(token) + ";")
                return self.send_bytes(200, "text/html; charset=utf-8", html.encode())
            if url.path in ("/workspace.css", "/workspace.js"):
                path = pr.HERE / url.path.lstrip("/")
                if path.is_file():
                    mime = "text/css" if path.suffix == ".css" else "text/javascript"
                    return self.send_bytes(200, mime + "; charset=utf-8", path.read_bytes())
                return self.reply({"error": "文件不存在。"}, 404)
            try:
                if url.path == "/api/timestamps":
                    return self.reply(timestamps.history(database))
                if url.path == "/api/timestamps/export":
                    if self.headers.get("X-Paperroom-Token") != token:
                        return self.reply({"error": "请从本机的时间记录页面导出。"}, 403)
                    payload = json.dumps(timestamps.history(database, export=True), ensure_ascii=False, indent=2).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Disposition", 'attachment; filename="paperroom-timestamps.json"')
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                if url.path == "/api/workspace":
                    section = parse_qs(url.query).get("section", [None])[0]
                    return self.reply(read_snapshot(project, section))
                asset = re.fullmatch(r"/api/sections/([A-Za-z0-9_-]+)/documents/(rev|ref)-([1-9]\d{0,8})/(pdf|pages/([1-9]\d{0,5}))", url.path)
                if asset:
                    section, kind, revision, fmt, number = asset.groups()
                    if database.is_file():
                        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                            blob = section_review.document_asset(db, section, kind, int(revision),
                                                                 int(number) if number else None)
                        if blob is not None:
                            if fmt == "pdf":
                                self.send_response(200)
                                self.send_header("Content-Type", "application/pdf")
                                self.send_header("Content-Length", str(len(blob)))
                                self.send_header("Content-Disposition", f'inline; filename="{section}-{kind}-{revision}.pdf"')
                                self.send_header("Cache-Control", "no-store")
                                self.send_header("X-Content-Type-Options", "nosniff")
                                self.send_header("X-Frame-Options", "SAMEORIGIN")
                                self.end_headers()
                                self.wfile.write(blob)
                                return
                            return self.send_bytes(200, "image/png", blob)
                    return self.reply({"error": "此版本未保存所请求的排版文件。"}, 404)
                image = re.fullmatch(r"/api/sections/([A-Za-z0-9_-]+)/revisions/([1-9]\d*)/pages/([1-9]\d*)", url.path)
                if image:
                    section, revision, number = image.groups()
                    if database.is_file():
                        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                            blob = section_review.page(db, section, int(revision), int(number))
                        if blob is not None:
                            return self.send_bytes(200, "image/png", blob)
                    return self.reply({"error": "这页审阅图不存在。"}, 404)
            except (OSError, ValueError, sqlite3.Error) as exc:
                return self.reply({"error": str(exc)}, 409)
            return super().do_GET()

        def do_POST(self):
            url = urlsplit(self.path)
            upload = re.fullmatch(r"/api/sections/([A-Za-z0-9_-]+)/references", url.path)
            if not upload and url.path not in ("/api/workspace", "/api/timestamps"):
                return super().do_POST()
            if (not self.local_host()
                    or self.headers.get("Origin") != "http://" + self.headers.get("Host", "")
                    or self.headers.get("X-Paperroom-Token") != token):
                return self.reply({"error": "请从本机的 Paperroom 页面提交。"}, 403)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if upload:
                    if self.headers.get_content_type() != "application/pdf":
                        return self.reply({"error": "请选择 PDF 文件。"}, 415)
                    if not 0 < size <= pr.MAX_DOCUMENT_BYTES:
                        return self.reply({"error": "PDF 须大于零且不超过 32 MiB。"}, 413)
                    values = parse_qs(url.query, max_num_fields=3)
                    section = upload.group(1)
                    blob = self.rfile.read(size)
                    if len(blob) != size:
                        raise ValueError("PDF 上传不完整。")
                    with closing(pr.connect(database)) as db:
                        imported = section_review.import_reference(db, project, section, upload=blob,
                                                                   title=values.get("title", [None])[0],
                                                                   pages=values.get("pages", ["all"])[0])
                        return self.reply({**snapshot(db, project, section), "reference_id": imported["reference_id"]})
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("表单为空或超过 1 MiB。")
                data = json.loads(self.rfile.read(size))
                if url.path == "/api/timestamps":
                    return self.reply(timestamps.request_receipt(database, data))
                with closing(pr.connect(database)) as db:
                    result = author_action(db, project, data)
                self.reply(result)
            except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
                self.reply({"error": str(exc)}, 409)
    return Workspace


def main():
    parser = argparse.ArgumentParser(description="在浏览器打开论文提纲和作者审阅工作区")
    parser.add_argument("project", type=Path, help="论文项目文件夹")
    parser.add_argument("--port", type=int, default=0, help="监听端口，默认自动选择")
    parser.add_argument("--no-browser", action="store_true", help="只输出本机链接")
    options = parser.parse_args()
    project = options.project.expanduser().resolve()
    if not project.is_dir():
        parser.error("论文项目文件夹不存在。")
    handler = handler_for(database_path(project), secrets.token_urlsafe(32), project)
    with ThreadingHTTPServer(("127.0.0.1", options.port), handler) as server:
        url = f"http://127.0.0.1:{server.server_port}/workspace"
        print(f"Paperroom · {url}", flush=True)
        if not options.no_browser:
            webbrowser.open(url, new=2)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    try:
        main()
    except OSError as exc:
        sys.exit(f"Paperroom · {exc}")
