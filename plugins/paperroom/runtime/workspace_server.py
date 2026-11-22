"""Run the local Paperroom workspace and its browser-only author forms."""
import argparse
import hashlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import outline
import paperroom as pr
import section_review
import sentence_references
import timestamps
import versions as paper_versions
import assets
import i18n
import room
from room_server import handler_for as legacy_handler


def pdf_layout(blob):
    """Read the display box from the exact PDF served by the versioned link."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf:
            pdf.write(blob)
            pdf.flush()
            if sys.platform == "darwin":
                command = ["osascript", "-l", "JavaScript", str(pr.HERE / "render_pdf.js"), pdf.name, "", "geometry"]
                output = subprocess.check_output(command, timeout=6, stderr=subprocess.DEVNULL)
                return json.loads(output)
            info = subprocess.check_output(["pdfinfo", "-box", "-f", "1", "-l", "1", pdf.name],
                                           env={**os.environ, "LC_ALL": "C"}, text=True,
                                           stderr=subprocess.DEVNULL, timeout=6)
            pages = re.search(r"^Pages:\s+(\d+)", info, re.M)
            box = re.search(r"CropBox:\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)\s+([\d.-]+)", info)
            if pages and box:
                x0, y0, x1, y1 = map(float, box.groups())
                rotation = re.search(r"rot:\s+(-?\d+)", info)
                ratio = (y1-y0)/(x1-x0)
                return {"pages": int(pages[1]), "ratio": 1/ratio if rotation and int(rotation[1]) % 180 else ratio}
    except (OSError, subprocess.SubprocessError, ValueError, ZeroDivisionError):
        pass
    return {}


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
    active = next((s for s in plan["sections"] if s["id"] == selected), None)
    return {"project": project_key, "outline": plan, "section": selected, "review": review,
            "sentence_references": sentence_references.status(db, plan, active),
            "versions": paper_versions.listing(db), "tex_available": pr.tex_available(),
            "archived": archived, "legacy": legacy_tasks(db)}


def read_snapshot(project, section=None):
    path = database_path(project)
    if not path.is_file():
        return snapshot(None, project, section)
    paper_versions.ensure_migrated(path)
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
    elif action == "adopt_outline":
        outline.adopt(db, project, data["version"])
    elif action == "reference":
        imported = section_review.import_reference(db, project, section, title=data.get("title"), tex=data.get("tex"),
                                                   pdf=data.get("pdf"), pages=data.get("pages", "all"))
        return {**snapshot(db, project, section), "reference_id": imported["reference_id"]}
    elif action == "language":
        i18n.set_language(project, data["language"])
    elif action == "review" and "version" in data:
        paper_versions.submit_review(db, data["version"], data["notes"], approve=data.get("approve", False))
    elif action == "review":
        section_review.submit_review(db, project, section, data["revision"], data["notes"],
                                     approve=data.get("approve", False))
    else:
        raise ValueError("找不到此表单操作。")
    return snapshot(db, project, section)


def _draft_keys(key):
    # Browser storage must distinguish checkouts even when a port is reused.
    # The SQLite file already identifies the project, including after a handoff.
    match = re.fullmatch(
        r"paperroom-author-v2:/workspace:[0-9a-f]{24}:(paper|section|paragraph|review):([\w-]*):([\w-]*):(\d*)",
        key if isinstance(key, str) and len(key) <= 300 else "")
    if not match:
        raise ValueError("Invalid outline draft key.")
    view, section, paragraph, revision = match.groups()
    # A whole-paper review belongs to its version, whichever outline link opened it.
    if view == "review":
        section = paragraph = ""
    slot = ":".join((view, section, paragraph, revision))
    return "form:" + slot, "paperroom-author-v2:/workspace:*:" + slot


def outline_draft(db, key):
    slot, aliases = _draft_keys(key)
    if db is not None and db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_author_autosaves'").fetchone():
        # 0.6.16 stored the original absolute path hash in the key. Pick up
        # the most recent legacy form even if the original directory is gone.
        row = db.execute("SELECT etag, body FROM v2_author_autosaves WHERE key=? OR key GLOB ? "
                         "ORDER BY rowid DESC LIMIT 1", (slot, aliases)).fetchone()
        if row:
            return {"etag": row[0], "draft": json.loads(row[1])}
    return {"etag": "", "draft": None}


def save_outline_draft(db, request):
    """Save an unsubmitted outline or review in this project, outside its public journal."""
    key, draft = request["key"], request["draft"]
    if draft is not None and (not isinstance(draft, dict) or not isinstance(draft.get("base"), int)
                              or not isinstance(draft.get("fields"), dict)):
        raise ValueError("Invalid outline draft.")
    with db:
        db.execute("BEGIN IMMEDIATE")
        current = outline_draft(db, key)
        if current["etag"] != request["etag"]:
            raise ValueError("Another window has changed this draft.")
        if draft is None and not current["etag"]:
            return {"etag": ""}
        db.execute("CREATE TABLE IF NOT EXISTS v2_author_autosaves "
                   "(key TEXT PRIMARY KEY, etag TEXT NOT NULL, body TEXT NOT NULL)")
        slot, aliases = _draft_keys(key)
        db.execute("DELETE FROM v2_author_autosaves WHERE key GLOB ?", (aliases,))
        if draft is None:
            db.execute("DELETE FROM v2_author_autosaves WHERE key=?", (slot,))
            return {"etag": ""}
        etag = secrets.token_hex(12)
        db.execute("INSERT OR REPLACE INTO v2_author_autosaves VALUES (?,?,?)",
                   (slot, etag, json.dumps(draft, ensure_ascii=False)))
        return {"etag": etag}


def handler_for(database, token, project, room_version=None):
    """room_version is set when this server is the project's lasting background room."""
    project = Path(project).resolve()
    project_info = {"room": room.project_key(project), "name": project.name or str(project),
                    "parent": project.parent.name, "path": str(project)}

    class Workspace(legacy_handler(database, token)):
        def end_headers(self):
            if room_version is not None:
                # Lets an open page notice that a newer Paperroom took over the room.
                self.send_header("X-Paperroom-Version", room_version)
            super().end_headers()

        def parse_request(self):
            parsed = super().parse_request()
            # Health checks from clients don't keep an unused room alive; page and tool requests do.
            if parsed and urlsplit(self.path).path != "/api/room":
                self.server.last_seen = time.monotonic()
            return parsed

        def inline_pdf(self, blob, filename):
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.end_headers()
            self.wfile.write(blob)

        def do_GET(self):
            if not self.local_host():
                return self.reply({"error": "请使用本机地址。"}, 403)
            url = urlsplit(self.path)
            room_keys = parse_qs(url.query, keep_blank_values=True).get("room")
            if room_keys is None and url.path.startswith("/api/"):
                # Assets opened by a tab also belong to the paper shown in its address bar.
                referer = self.headers.get("Referer", "").partition("?")
                if referer[0] == "http://" + self.headers.get("Host", "") + "/workspace":
                    room_keys = parse_qs(referer[2], keep_blank_values=True).get("room")
            if room_keys is not None and room_keys != [project_info["room"]]:
                message = "This link belongs to another paper. Ask Paperroom to reopen the intended project."
                if url.path == "/workspace":
                    return self.send_bytes(409, "text/plain; charset=utf-8",
                                           ("该链接对应另一篇论文。请回到原对话，让 Paperroom 重新打开目标论文。\n" + message).encode())
                return self.reply({"error": message}, 409)
            if url.path == "/api/room" and room_version is not None:
                if self.headers.get("X-Paperroom-Token") != token:
                    return self.reply({"error": "请从本机的 Paperroom 打开。"}, 403)
                return self.reply({"project": str(project), "version": room_version, "pid": os.getpid()})
            if url.path == "/workspace":
                template = (pr.HERE / "workspace.html").read_text("utf-8")
                settings = ("window.roomToken=" + json.dumps(token) + ";window.paperroomVersion=" +
                            json.dumps(room_version or "") + ";window.paperroomLanguage=" +
                            json.dumps(i18n.chosen(project)) + ";window.paperroomProject=" +
                            json.dumps(project_info).replace("<", "\\u003c") + ";window.paperroomCatalog=" +
                            (pr.HERE / "i18n_en.json").read_text("utf-8").replace("</", "<\\/") + ";")
                html = template.replace("/*SERVER_SETTINGS*/", settings)
                return self.send_bytes(200, "text/html; charset=utf-8", html.encode())
            if url.path in ("/workspace.css", "/workspace.js", "/katex.min.js"):
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
                if url.path == "/api/outline-draft":
                    if self.headers.get("X-Paperroom-Token") != token:
                        return self.reply({"error": "请从本机的 Paperroom 页面提交。"}, 403)
                    key = parse_qs(url.query).get("key", [""])[0]
                    if database.is_file():
                        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                            return self.reply(outline_draft(db, key))
                    return self.reply(outline_draft(None, key))
                if url.path == "/api/workspace":
                    section = parse_qs(url.query).get("section", [None])[0]
                    return self.reply(read_snapshot(project, section))
                if url.path in ("/api/assets", "/api/prepared-assets"):
                    requested = parse_qs(url.query, keep_blank_values=True).get("build")
                    if requested is None:
                        return self.reply(assets.prepared_index(project))
                    if (url.path != "/api/assets" or len(requested) != 1
                            or not re.fullmatch(r"[1-9]\d{0,8}", requested[0])):
                        return self.reply({"error": "这次编译没有保存所请求的页面。"}, 404)
                    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) if database.is_file() else None
                    try:
                        if db is not None:
                            db.execute("BEGIN")
                        review = assets.review_index(db, project, int(requested[0]))
                        if review is None:
                            return self.reply({"error": "这次编译没有保存所请求的页面。"}, 404)
                        return self.reply(review)
                    finally:
                        if db is not None:
                            db.close()
                if url.path.startswith(("/api/prepared-assets/", "/api/assets/")):
                    preview = re.fullmatch(r"/api/prepared-assets/([0-9a-f]{16})", url.path)
                    versions = parse_qs(url.query, keep_blank_values=True).get("v", [])
                    if not preview or len(versions) != 1 or not re.fullmatch(r"[0-9a-f]{64}", versions[0]):
                        return self.reply({"error": "没有可预览的内容。"}, 404)
                    found = assets.prepared_preview(project, preview.group(1), versions[0])
                    if found is None:
                        return self.reply({"error": "没有可预览的内容。"}, 404)
                    mime, blob = found
                    if mime == "application/pdf":
                        if parse_qs(url.query).get("layout") == ["1"]:
                            return self.reply(pdf_layout(blob))
                        return self.inline_pdf(blob, f"{preview.group(1)}.pdf")
                    return self.send_bytes(200, mime, blob)
                build_page = re.fullmatch(r"/api/floats/([1-9]\d{0,8})/(pdf|pages/([1-9]\d{0,4}))", url.path)
                if build_page:
                    number, fmt, page = build_page.groups()
                    blob = None
                    if database.is_file():
                        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                            blob = assets.build_asset(db, int(number), int(page) if page else None)
                    if blob is None:
                        return self.reply({"error": "这次编译没有保存所请求的页面。"}, 404)
                    if fmt == "pdf":
                        return self.inline_pdf(blob, f"figures-{number}.pdf")
                    return self.send_bytes(200, "image/png", blob)
                asset = re.fullmatch(r"/api/sections/([A-Za-z0-9_-]+)/documents/(rev|ref)-([1-9]\d{0,8})/(pdf|pages/([1-9]\d{0,5}))", url.path)
                if asset:
                    section, kind, revision, fmt, number = asset.groups()
                    if database.is_file():
                        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                            blob = section_review.document_asset(db, section, kind, int(revision),
                                                                 int(number) if number else None)
                        if blob is not None:
                            if fmt == "pdf":
                                return self.inline_pdf(blob, f"{section}-{kind}-{revision}.pdf")
                            return self.send_bytes(200, "image/png", blob)
                    return self.reply({"error": "此版本未保存所请求的排版文件。"}, 404)
                version = re.fullmatch(r"/api/versions/(0|[1-9]\d*)/(pdf|pages/([1-9]\d*))", url.path)
                if version:
                    number, kind, page = version.groups()
                    blob = None
                    if database.is_file():
                        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                            blob = paper_versions.page(db, int(number), -1 if kind == "pdf" else int(page))
                    if blob is None:
                        return self.reply({"error": "这个版本没有所请求的页面。"}, 404)
                    if kind == "pdf":
                        return self.inline_pdf(blob, f"paper-V{number}.pdf")
                    return self.send_bytes(200, "image/png", blob)
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
            if url.path == "/api/room/stop" and room_version is not None:
                origin = self.headers.get("Origin")
                if (not self.local_host() or self.headers.get("X-Paperroom-Token") != token
                        or origin not in (None, "http://" + self.headers.get("Host", ""))):
                    return self.reply({"error": "请从本机的 Paperroom 操作。"}, 403)
                self.reply({"stopping": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            upload = re.fullmatch(r"/api/sections/([A-Za-z0-9_-]+)/references", url.path)
            if not upload and url.path not in ("/api/workspace", "/api/timestamps", "/api/outline-draft"):
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
                if (url.path == "/api/workspace" and isinstance(data, dict)
                        and data.get("action") in ("float_build", "float_note", "float_confirm", "float_withdraw")):
                    return self.reply({"error": "图表为只读。请在原对话中更新准备好的文件。"}, 410)
                with closing(pr.connect(database)) as db:
                    if url.path == "/api/outline-draft":
                        return self.reply(save_outline_draft(db, data))
                    result = author_action(db, project, data)
                self.reply(result)
            except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
                self.reply({"error": str(exc)}, 409)
    return Workspace


def serve_room(project, port):
    """Background room started by room.ensure: stable token, announced port, idle exit."""
    token = os.environ.pop("PAPERROOM_ROOM_TOKEN", "") or secrets.token_urlsafe(32)
    version = os.environ.get("PAPERROOM_ROOM_VERSION", "")
    handler = handler_for(database_path(project), token, project, room_version=version)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        if not port:
            raise
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)  # the old port was taken meanwhile
    server.daemon_threads = True
    server.last_seen = time.monotonic()
    idle = room.idle_seconds()

    def watch():
        while True:
            time.sleep(min(30.0, idle / 4))
            if time.monotonic() - server.last_seen > idle:
                server.shutdown()
                return
    threading.Thread(target=watch, daemon=True).start()
    with server:
        room.announce(project, server.server_port, token, version)
        server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="在浏览器打开论文提纲和作者审阅工作区")
    parser.add_argument("project", type=Path, help="论文项目文件夹")
    parser.add_argument("--port", type=int, default=0, help="监听端口，默认自动选择")
    parser.add_argument("--no-browser", action="store_true", help="只输出本机链接")
    parser.add_argument("--room", action="store_true", help=argparse.SUPPRESS)
    options = parser.parse_args()
    project = options.project.expanduser().resolve()
    if not project.is_dir():
        parser.error("论文项目文件夹不存在。")
    if options.room:
        return serve_room(project, options.port)
    from activation import is_managed
    if not is_managed(project):
        parser.error("请先在聊天中明确要求使用 Paperroom 管理这篇论文。")
    handler = handler_for(database_path(project), secrets.token_urlsafe(32), project)
    with ThreadingHTTPServer(("127.0.0.1", options.port), handler) as server:
        url = room.workspace_url(project, server.server_port)
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
