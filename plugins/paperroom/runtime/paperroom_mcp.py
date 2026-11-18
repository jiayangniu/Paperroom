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
from urllib.parse import urlencode

import paperroom as pr
import outline
import section_review
import workspace_server as workspace
from workspace_server import database_path

VERSION = "0.3.0"
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
PROJECT = {"type":"string","description":"Absolute directory of the active manuscript. Use the same manuscript root in both clients. When multiple papers are open, choose the one named by the author."}
TASK = {"type":"string","description":"Task id returned by writing_status or begin_writing."}
REFERENCE = {"type":"string","minLength":1,"description":"Agreed discussion notes for the author to consult. Submit discussion only."}
VERSION_FIELD = {"type":"integer","minimum":1,"description":"Current task version, obtained from writing_status."}
POSITIVE = {"type":"integer","minimum":1}
INSTRUCTIONS = """Paperroom is an author-led manuscript workspace for Codex and Claude.
Discuss research questions, evidence, section choices and edits freely. Record agreed research
assets with update_research_assets. When asked to draft or rewrite (写摘要、重写引言),
read workspace_status or open_writing_workspace. The author fills three outline levels
in the browser: article sections, one section's paragraphs, and sentence intent for one
paragraph. Show only the authorized parent outline and evidence as guidance; leave the
author's own fields for the author. Never submit their outline or review through HTTP,
browser automation, shell, or edits to paper.md. Never supply an answer for them to copy.
Before drafting any paragraph, check that exact paragraph's ready flag. Draft only the
unlocked paragraph, from its sentence intents, then call save_paragraph_draft.
Other sections/paragraphs may remain blank. Publish a completed section using publish_section
for a rendered, whole-section review. At review wait for the author's anchored observations
on that version. Use submitted feedback for revisions and present each revised version
for another review. Never mark the author's review complete. For pre-v2 tasks with
a legacy ID, resume with writing_status and open_author_room. Do not create legacy tasks."""


def tool(name, description, fields, required):
    return {"name":name, "description":description,
            "inputSchema":{"type":"object","properties":{"project":PROJECT, **fields},
                           "required":["project",*required], "additionalProperties":False}}


TOOLS = [
    tool("open_writing_workspace", "Open the local author workspace at the relevant outline or review when the author requests manuscript prose. Free discussion needs no checkpoint.",
         {"section":{"type":"string","description":"Section ID from workspace_status."},
          "paragraph":{"type":"string","description":"Paragraph ID within that section."},
          "view":{"type":"string","enum":["assets","paper","section","paragraph","review"]}}, []),
    tool("workspace_status", "Read paper.md, outline IDs and per-paragraph write permissions. Select a section to read its draft versions, rendered review history and author notes.",
         {"section":{"type":"string"}}, []),
    tool("update_research_assets", "Record the research question and evidence summary agreed with the author. This only updates the reference material, never writes an author's outline or review.",
         {"version":{"type":"integer","minimum":0},"question":{"type":"string"},"evidence":{"type":"string"},
          "affected_sections":{"type":"array","items":{"type":"string"},"description":"IDs whose plans the author explicitly wants to reconsider because the assets changed."}},
         ["version","question","evidence"]),
    tool("save_paragraph_draft", "Save LaTeX prose for ONE paragraph after its author-written sentence intents unlock it. Check workspace_status first. No other paragraph is unlocked by this.",
         {"section":{"type":"string"},"paragraph":{"type":"string"},"plan_revision":POSITIVE,
          "expected_version":{"type":"integer","minimum":0,"description":"0 for a first draft; otherwise the current draft version."},
          "text":{"type":"string","description":"LaTeX paragraph body only, based on the author's intent."}},
         ["section","paragraph","plan_revision","expected_version","text"]),
    tool("publish_section", "Publish the saved paragraphs in section order as one rendered LaTeX section and open the author review. External matching TeX/PDF and pages are optional. Wait until review is submitted before revising.",
         {"section":{"type":"string"},"expected_revision":{"type":"integer","minimum":0,"description":"0 for the first publication, otherwise the latest published revision."},
          "tex":{"type":"string","description":"Optional standalone TeX source inside the manuscript project containing the registered paragraphs."},
          "pdf":{"type":"string","description":"Optional matching PDF built from the supplied TeX."},
          "pages":{"type":"string","description":"Section excerpt pages such as 2-3, or all."},
          "minimum":dict(POSITIVE, description="Minimum number of distinct anchored author comments; defaults to 3.")},
         ["section","expected_revision"]),
    tool("begin_writing", "Enter the author workflow by section title. Resumes a matching pre-v2 task when present. Otherwise opens the new three-level workspace. Does not author outline entries.",
         {"title":{"type":"string","minLength":1}, "reference":REFERENCE,"paragraphs":POSITIVE,
          "min_notes":POSITIVE,"single":{"type":"boolean","description":"True for an edit to a specific existing paragraph. For a one-paragraph section such as an Abstract use paragraphs=1."}},
         ["title"]),
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


def manuscript_file(root, name):
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Choose a manuscript file inside the current project.")
    if not candidate.is_file():
        raise ValueError(f"File does not exist: {name}")
    return candidate


SERVER_LOCK = threading.Lock()


def show_author(database, task=None, *, project=None, query=None):
    if project is None:
        project = database.parent.parent
        if project.name == "paperroom_tool":
            project = project.parent
    with SERVER_LOCK:
        if database not in SERVERS:
            handler = workspace.handler_for(database, secrets.token_urlsafe(32), project)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=httpd.serve_forever, name="paperroom-author", daemon=True).start()
            SERVERS[database] = httpd
        port = SERVERS[database].server_port
    route = "/#" + task if task else "/workspace"
    if query:
        route += "?" + urlencode({k:v for k,v in query.items() if v is not None})
    url = f"http://127.0.0.1:{port}{route}"
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
    types = {"boolean":bool,"string":str,"integer":int,"array":list}
    for key, value in arguments.items():
        spec = schema["properties"].get(key)
        if not spec or type(value) is not types[spec["type"]]:
            raise ValueError(f"Invalid option: {key}")
        if spec["type"] == "array" and any(not isinstance(item, str) for item in value):
            raise ValueError(f"Invalid list: {key}")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"Invalid option: {key}")
        if spec["type"] == "string" and not value.strip() and key not in ("question", "evidence"):
            raise ValueError(f"Empty argument: {key}")
        if "minimum" in spec and value < spec["minimum"]:
            raise ValueError(f"{key} must be positive.")


def attach_room(payload, project, *, task=None, query=None):
    try:
        payload.update(show_author(database_path(project), task, project=project, query=query))
    except OSError as exc:
        payload["room_error"] = f"无法打开本机浏览器工作区：{exc}。可重新打开同一工作区。"
    return payload


def open_workspace(project, args, state=None):
    requested_section = args.get("section")
    data = state or workspace.read_snapshot(project, requested_section)
    sections = data["outline"]["sections"]
    if requested_section is not None and requested_section != data["section"]:
        raise ValueError("所选章节不存在，请刷新工作区。")
    section = next((s for s in sections if s["id"] == data["section"]), None)
    paragraph_id = args.get("paragraph")
    if paragraph_id and (not section or not any(p["id"] == paragraph_id for p in section["paragraphs"])):
        raise ValueError("所选段落不属于当前章节。")
    view = args.get("view")
    if not view:
        if data["section"] and section is None:
            view = "review"
        elif not data["outline"]["question"] or not data["outline"]["evidence"]:
            view = "assets"
        elif not section:
            view = "paper"
        elif data["review"] and data["review"]["phase"] == "review":
            view = "review"
        elif not section["planned"]:
            view = "section"
        elif paragraph_id:
            view = "paragraph"
        else:
            paragraph_id = next((p["id"] for p in section["paragraphs"] if not p["ready"]), None)
            if not paragraph_id:
                drafts = data["review"]["drafts"]
                paragraph_id = next((p["id"] for p in section["paragraphs"]
                                     if not drafts.get(p["id"], {}).get("current")), None)
            view = "paragraph" if paragraph_id else "review"
    return attach_room(data, project, query={"view":view,"section":data["section"],"paragraph":paragraph_id})


def workspace_call(name, args, project):
    if name == "workspace_status":
        state = workspace.read_snapshot(project, args.get("section"))
        if "section" in args and state["section"] != args["section"]:
            raise ValueError("所选章节不存在，请刷新工作区。")
        return state
    if name == "open_writing_workspace":
        return open_workspace(project, args)
    path = database_path(project)
    with closing(pr.connect(path)) as db:
        if name == "update_research_assets":
            plan = outline.update_assets(db, project, args["version"], args["question"], args["evidence"],
                                         affected_sections=args.get("affected_sections", []))
            return {"outline": plan}
        if name == "save_paragraph_draft":
            return section_review.save_paragraph_draft(
                db, project, args["section"], args["paragraph"], args["plan_revision"],
                args["text"], expected_version=args["expected_version"])
        options = {k:args[k] for k in ("pages","minimum","expected_revision") if k in args}
        for key in ("tex", "pdf"):
            if key in args:
                options[key] = manuscript_file(project, args[key])
        result = section_review.publish_section(db, project, args["section"], **options)
    return attach_room(result, project, query={"view":"review","section":args["section"]})


def invoke(name, a):
    validate(name,a)
    raw = Path(a["project"]).expanduser()
    if not raw.is_absolute() or not raw.is_dir():
        raise ValueError("Use the absolute path to the active paper's existing directory.")
    root = raw.resolve()
    path = database_path(root)
    if name in ("open_writing_workspace", "workspace_status", "update_research_assets",
                "save_paragraph_draft", "publish_section"):
        return workspace_call(name, a, root)
    if name == "begin_writing":
        data = workspace.read_snapshot(root)
        title = a["title"].strip().casefold()
        match = next((s for s in data["outline"]["sections"] if s["title"].casefold() == title), None)
        if match:
            return open_workspace(root, {"section":match["id"]})
        legacy = next((j for j in data["legacy"] if j["title"].casefold() == title
                       and j["phase"] != "reviewed"), None)
        if not legacy:
            return open_workspace(root, {"view":"paper"} if data["outline"]["sections"] else {}, data)
        a = {**a, "task":legacy["id"]}
        name = "open_author_room"
    if not path.is_file():
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
        if name == "open_author_room":
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
        return attach_room(job, root, task=job["id"])
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
