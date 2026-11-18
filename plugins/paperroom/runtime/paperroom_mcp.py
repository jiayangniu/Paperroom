#!/usr/bin/env python3
"""Local MCP entry point shared by the Claude Code and Codex plugins."""
import json
import secrets
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path

import paperroom as pr
from room_server import handler_for

VERSION = "0.2.0"
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
PROJECT = {"type":"string","description":"Absolute directory of the active manuscript. Use the same manuscript root in both clients. When multiple papers are open, choose the one named by the author."}
TASK = {"type":"string","description":"Task id returned by writing_status or begin_writing."}
REFERENCE = {"type":"string","minLength":1,"description":"Agreed discussion notes for the author to consult. Submit discussion only."}
VERSION_FIELD = {"type":"integer","minimum":1,"description":"Current task version, obtained from writing_status."}
POSITIVE = {"type":"integer","minimum":1}
INSTRUCTIONS = """For local academic manuscripts, use begin_writing when the author asks for draft or rewritten prose, including 帮我写摘要 or 重写引言. For research discussion, outline exploration, uploaded evidence, changes of research question and critique, discuss freely. Use the current manuscript directory. An author checkpoint is filled by the author in their browser. Never generate or post their response. At outline/paragraph/review present the returned room URL and wait. At discussion, read their words, discuss the next paragraph's sentence roles and set_paragraph_reference. At ready, draft from the author's notes, then publish_draft to show the LaTeX rendering. On continue/resume read writing_status. For a revision read the previous review notes, then republish. Use these tools in existing demo projects as well; they share the demo database. Read manuscripts and evidence through the host's normal workspace tools."""


def tool(name, description, fields, required):
    return {"name":name, "description":description,
            "inputSchema":{"type":"object","properties":{"project":PROJECT, **fields},
                           "required":["project",*required], "additionalProperties":False}}


TOOLS = [
    tool("begin_writing", "Start or resume the author's Paperroom checkpoint BEFORE drafting or rewriting academic manuscript prose (写摘要、写或重写论文某节). Use after discussing the section logic. Leave ordinary research discussion free.",
         {"title":{"type":"string","minLength":1}, "reference":REFERENCE,"paragraphs":POSITIVE,
          "min_notes":POSITIVE,"single":{"type":"boolean","description":"True for an edit to a specific existing paragraph. For a one-paragraph section such as an Abstract use paragraphs=1."}},
         ["title","reference"]),
    tool("writing_status", "Read existing writing tasks, author reasoning and version-specific review notes. Use on continue, during client handover, or before drafting. No write or browser launch.",
         {"task":TASK}, []),
    tool("open_author_room", "Reopen the browser for an existing author checkpoint after a restart or change of client.", {"task":TASK}, ["task"]),
    tool("set_paragraph_reference", "After the author and AI discuss the NEXT paragraph's sentence roles, open its author-only restatement form.",
         {"task":TASK,"version":VERSION_FIELD,"reference":REFERENCE}, ["task","version","reference"]),
    tool("publish_draft", "After receiving author plans, render a LaTeX excerpt and open the author's mandatory version review. For later revisions use the last submitted author feedback.",
         {"task":TASK,"version":VERSION_FIELD,"tex":{"type":"string","description":"LaTeX source in this manuscript."},
          "pdf":{"type":"string","description":"Optional matching PDF compiled using the manuscript's own build."},
          "pages":{"type":"string","description":"all or page selection e.g. 2-3."}}, ["task","version","tex"])
]
SCHEMAS = {t["name"]:t["inputSchema"] for t in TOOLS}
SERVERS = {}


def database_path(project):
    project = project.resolve()
    legacy = project / "paperroom_tool/.paperroom/project.sqlite3"
    standalone = project / ".paperroom/project.sqlite3"
    path = legacy if legacy.is_file() else standalone
    if not path.resolve().is_relative_to(project):
        raise ValueError("The project's Paperroom storage resolves outside this project.")
    return path


def manuscript_file(root, name):
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Choose a manuscript file inside the current project.")
    if not candidate.is_file():
        raise ValueError(f"File does not exist: {name}")
    return candidate


def show_author(database, task):
    if database not in SERVERS:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(database, secrets.token_urlsafe(32)))
        threading.Thread(target=httpd.serve_forever, name="paperroom-author", daemon=True).start()
        SERVERS[database] = httpd
    url = f"http://127.0.0.1:{SERVERS[database].server_port}/#{task}"
    try:
        opened = webbrowser.open(url, new=2)
    except (OSError, webbrowser.Error):
        opened = False
    return {"room_url":url,"browser_open_requested":bool(opened)}


def validate(name, arguments):
    if name not in SCHEMAS:
        raise ValueError("Unknown tool.")
    schema = SCHEMAS[name]
    if not isinstance(arguments,dict) or not set(schema["required"]).issubset(arguments):
        raise ValueError("Missing required arguments.")
    types = {"boolean":bool,"string":str,"integer":int}
    for key, value in arguments.items():
        spec = schema["properties"].get(key)
        if not spec or type(value) is not types[spec["type"]]:
            raise ValueError(f"Invalid option: {key}")
        if spec["type"] == "string" and not value.strip():
            raise ValueError(f"Empty argument: {key}")
        if "minimum" in spec and value < spec["minimum"]:
            raise ValueError(f"{key} must be positive.")


def begin(db, args):
    title = args["title"].strip()
    # The CLI's start inserts within the same connection/transaction.
    with db:
        db.execute("BEGIN IMMEDIATE")
        for (body,) in db.execute("SELECT body FROM tasks ORDER BY rowid DESC"):
            existing = json.loads(body)
            if existing["title"].casefold() == title.casefold() and existing["phase"] != "reviewed":
                return existing
        return pr.start(db,title,args["reference"],args.get("paragraphs",1),
                        args.get("min_notes",3),args.get("single",False))


def invoke(name, a):
    validate(name,a)
    raw = Path(a["project"]).expanduser()
    if not raw.is_absolute() or not raw.is_dir():
        raise ValueError("Use the absolute path to the active paper's existing directory.")
    root = raw.resolve()
    path = database_path(root)
    if name != "begin_writing" and not path.is_file():
        if name == "writing_status" and "task" not in a:
            return {"tasks":[]}
        raise ValueError("This paper has no saved task.")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) if name == "writing_status" else pr.connect(path)
    with closing(connection) as db:
        if name == "writing_status":
            if "task" in a:
                return pr.get(db,a["task"])
            jobs = (json.loads(row[0]) for row in db.execute("SELECT body FROM tasks ORDER BY rowid DESC"))
            return {"tasks":[{k:j[k] for k in ("id","title","phase","version")} for j in jobs]}
        if name == "begin_writing":
            job = begin(db,a)
        elif name == "open_author_room":
            job = pr.get(db,a["task"])
        elif name == "set_paragraph_reference":
            job = pr.plan(db,a["task"],a["reference"],a["version"])
        else:
            pr.check(pr.get(db,a["task"]),a["version"],("ready","reviewed"))
            tex = manuscript_file(root,a["tex"])
            pdf = manuscript_file(root,a["pdf"]) if "pdf" in a else None
            source = tex.read_bytes()
            images = pr.render(tex,pdf,a.get("pages","all"))
            if tex.read_bytes()!=source:
                raise ValueError("The draft changed during rendering; publish again.")
            job = pr.publish(db,a["task"],a["version"],source,images)
    if job["phase"] in ("outline","paragraph","review") or name == "open_author_room":
        try:
            job.update(show_author(path,job["id"]))
        except OSError as exc:
            job["room_error"] = f"Author checkpoint saved. Local browser service unavailable: {exc}. Retry open_author_room with this task ID."
    return job


def dispatch(request):
    if not isinstance(request,dict):
        return {"jsonrpc":"2.0","id":None,"error":{"code":-32600,"message":"Invalid request"}}
    method = request.get("method")
    rid = request.get("id")
    if "id" not in request and isinstance(method,str) and method.startswith("notifications/"):
        return None
    envelope = {"jsonrpc":"2.0","id":rid}
    if request.get("jsonrpc") != "2.0" or not isinstance(method,str):
        return {**envelope,"error":{"code":-32600,"message":"Invalid request"}}
    params = request.get("params",{})
    if not isinstance(params,dict):
        return {**envelope,"error":{"code":-32602,"message":"Invalid params"}}
    if method == "initialize":
        version = params.get("protocolVersion")
        result = {"protocolVersion":version if version in PROTOCOLS else PROTOCOLS[0],
                  "capabilities":{"tools":{"listChanged":False}},
                  "serverInfo":{"name":"paperroom","version":VERSION},"instructions":INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools":TOOLS}
    elif method == "tools/call":
        try:
            payload = invoke(params.get("name",""),params.get("arguments",{}))
            result = {"content":[{"type":"text","text":json.dumps(payload,ensure_ascii=False)}]}
        except (ValueError, TypeError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
            result = {"content":[{"type":"text","text":str(exc)}],"isError":True}
    else:
        return {**envelope,"error":{"code":-32601,"message":"Unsupported method"}}
    return {**envelope,"result":result}


def main():
    for line in sys.stdin.buffer:
        try:
            response = dispatch(json.loads(line))
        except (UnicodeError, json.JSONDecodeError):
            response = {"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Invalid JSON"}}
        if response is not None:
            print(json.dumps(response,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
