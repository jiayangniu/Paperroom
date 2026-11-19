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
import assets
import i18n
import section_review
import workspace_server as workspace
from workspace_server import database_path

VERSION = "0.6.2"
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
PROJECT = {"type":"string","description":"Absolute directory of the active manuscript. Use the same manuscript root in both clients. When multiple papers are open, choose the one named by the author."}
TASK = {"type":"string","description":"Task id returned by writing_status or begin_writing."}
REFERENCE = {"type":"string","minLength":1,"description":"Agreed discussion notes for the author to consult. Submit discussion only."}
VERSION_FIELD = {"type":"integer","minimum":1,"description":"Current task version, obtained from writing_status."}
POSITIVE = {"type":"integer","minimum":1}
INSTRUCTIONS = """Paperroom is an author-led manuscript workspace for Codex and Claude.
Discuss research questions, evidence, section choices and edits freely. Record agreed research
assets with update_research_assets. When asked to draft or rewrite (写摘要、重写引言),
read workspace_status or open_writing_workspace. The outline has three levels.
Level 1 (the article's sections and each section's role): after discussing the paper's
structure with the author, draft it with propose_paper_outline; for an existing paper,
take the sections from its .tex headings. The author reads it in the browser and adopts
it (or edits it); a section's paragraph plan opens only after adoption. Never adopt for
the author. Levels 2 and 3 (one section's paragraphs and their roles; sentence intent for
one paragraph) are written by the author in the browser. You may give a short reference
for a section's paragraph plan with suggest_section_plan (what the section might need to
cover, points from the discussion); it is shown beside the author's form, and the author
writes the plan in their own words. Never submit the author's plans or review through
HTTP, browser automation, shell, or edits to paper.md.
The paper's .tex files are the single source of prose. A section is the text under its
\\section heading in the main .tex (input/include files are followed); paragraphs are
blank-line separated and map in order to the author's paragraph outline.
Before editing an existing section, call workspace_status with its section ID: if the
section has prose and no saved layout, Paperroom freezes the original pages first
(review.original_saved). Check review.source for each paragraph's file:line and state.
Small edits to any prose need no checkpoint; a plugin hook denies file edits that add or
mostly rewrite a paragraph without the author's intents, and any direct edit of paper.md. Writing a new paragraph, or rewriting more
than half of one, requires that paragraph's ready flag: draft only the unlocked paragraph,
from its sentence intents, write it into the .tex at review.source, then call
save_paragraph_draft without text to register it.
Figures and tables are not prose and need no checkpoint: write their LaTeX into the
paper, then call publish_floats so the author sees them on the real pages. The author
may leave figure/table instructions in Paperroom (floats.open_requests): handle them,
then call publish_floats with responses. Confirmations are the author's own marks.
Other sections/paragraphs may remain blank. Publish a completed section using publish_section
for a rendered, whole-section review; omit tex/pdf/pages so the paper's own template and
section pages are used. The reader automatically pairs the before and after versions. At review wait for the author's anchored observations
on that version. Use submitted feedback for revisions and present each revised version
for another review: pass responses answering every note of the reviewed version
(changed, kept or discuss, with a reason). Never mark the author's review complete. For pre-v2 tasks with
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
    tool("import_section_reference", "Freeze a reading reference for a section. With no tex/pdf, compiles the paper's main .tex and keeps exactly this section's pages (workspace_status already does this once before a rewrite). Or freeze an existing PDF/standalone TeX with explicit pages. This leaves the author outline and review gates intact.",
         {"section":{"type":"string","description":"Existing section ID from workspace_status."},
          "pdf":{"type":"string","description":"Path inside the project to the compiled PDF."},
          "tex":{"type":"string","description":"Path inside the project to the unchanged main .tex (compiled by Paperroom) or the source of the provided PDF."},
          "pages":{"type":"string","description":"Physical PDF pages, counted from 1, e.g. 2-3. Defaults to all."},
          "title":{"type":"string","description":"Optional author-facing name for this reference."}}, ["section"]),
    tool("update_research_assets", "Record the research question and evidence summary agreed with the author. This only updates the reference material, never writes an author's outline or review.",
         {"version":{"type":"integer","minimum":0},"question":{"type":"string"},"evidence":{"type":"string"},
          "affected_sections":{"type":"array","items":{"type":"string"},"description":"IDs whose plans the author explicitly wants to reconsider because the assets changed."}},
         ["version","question","evidence"]),
    tool("propose_paper_outline", "Draft the paper-level outline (sections and each section's role) after discussing the structure with the author. The author adopts or edits it in the workspace; paragraph plans open only after adoption. Pass existing section IDs to keep them; unchanged sections keep the author's adoption.",
         {"version":{"type":"integer","minimum":0,"description":"outline.version from workspace_status."},
          "sections":{"type":"array","minItems":1,"items":{"type":"object","properties":{
              "id":{"type":"string","description":"Existing section ID, to keep that section."},
              "title":{"type":"string","description":"Section name; for an existing paper, its \\section heading."},
              "purpose":{"type":"string","description":"What this section does in the argument, in the author's language."}},
              "required":["title","purpose"],"additionalProperties":False}},
          "reopen":{"type":"array","items":{"type":"string"},"description":"IDs of sections that already have the author's paragraph plan and that the author agreed to change or remove."}},
         ["version","sections"]),
    tool("suggest_section_plan", "Leave a short reference for one section's paragraph plan (what it might need to cover, points from the discussion). Shown beside the author's own form; the author writes the plan. Replaces any earlier reference for that section.",
         {"section":{"type":"string"},"text":{"type":"string","description":"The reference, in the author's language, at most 4000 characters."}},
         ["section","text"]),
    tool("publish_floats", "After writing or adjusting figure/table LaTeX, compile the whole paper and show the author each float on the page where it lands. Answer the author's open figure/table instructions (floats.open_requests in workspace_status) in the same call.",
         {"responses":{"type":"array","description":"One entry per instruction you handled in this change.",
                       "items":{"type":"object","properties":{
                           "request":{"type":"integer","minimum":1,"description":"Instruction id from floats.open_requests."},
                           "text":{"type":"string","description":"What you changed, in the author's language."}},
                           "required":["request","text"],"additionalProperties":False}}}, []),
    tool("bind_section_source", "Point a section at its heading when the main .tex or the section title is ambiguous, e.g. several main files or a renamed heading.",
         {"section":{"type":"string"},"tex":{"type":"string","description":"Main .tex inside the project."},
          "label":{"type":"string","description":"Optional \\label of the section heading."}}, ["section","tex"]),
    tool("save_paragraph_draft", "Register ONE paragraph after its author-written sentence intents unlock it. Write the paragraph into the .tex first (see review.source); without text it is read from there. No other paragraph is unlocked by this.",
         {"section":{"type":"string"},"paragraph":{"type":"string"},"plan_revision":POSITIVE,
          "expected_version":{"type":"integer","minimum":0,"description":"0 for a first draft; otherwise the current draft version."},
          "text":{"type":"string","description":"Only for papers without a main .tex: the LaTeX paragraph body. Otherwise omit; the .tex is the source."}},
         ["section","paragraph","plan_revision","expected_version"]),
    tool("publish_section", "Publish the section for whole-section author review. Without tex/pdf, renders it from the paper's main .tex with its own template and pages, accepting small edits since registration. Wait until review is submitted before revising.",
         {"section":{"type":"string"},"expected_revision":{"type":"integer","minimum":0,"description":"0 for the first publication, otherwise the latest published revision."},
          "tex":{"type":"string","description":"Only for papers without a usable main .tex: standalone TeX containing the registered paragraphs."},
          "pdf":{"type":"string","description":"Optional matching PDF built from the supplied TeX."},
          "pages":{"type":"string","description":"Section excerpt pages such as 2-3, or all."},
          "minimum":dict(POSITIVE, description="Minimum number of distinct anchored author comments; defaults to 3 for the first version and 1 afterwards."),
          "responses":{"type":"array","description":"Required after a reviewed version with notes: one entry per note of that version.",
                       "items":{"type":"object","properties":{
                           "note":{"type":"integer","minimum":1,"description":"1-based number of the author's note."},
                           "status":{"type":"string","enum":["changed","kept","discuss"],"description":"changed: revised; kept: text kept on purpose; discuss: you disagree and explain why."},
                           "text":{"type":"string","description":"What you did, or why, in the author's language."}},
                           "required":["note","status","text"],"additionalProperties":False}}},
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
        item_type = dict if spec.get("items", {}).get("type") == "object" else str
        if spec["type"] == "array" and any(not isinstance(item, item_type) for item in value):
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


def selected_section(project, requested):
    """The section a call will actually show: the requested one, or the one the
    workspace selects by default (e.g. the introduction)."""
    if requested:
        return requested
    try:
        return workspace.read_snapshot(project)["section"]
    except (ValueError, OSError, sqlite3.Error):
        return None


def open_workspace(project, args, state=None):
    requested_section = args.get("section")
    original = ensure_original(project, selected_section(project, requested_section))
    data = workspace.read_snapshot(project, requested_section) if state is None or original else state
    if original and data["review"] is not None:
        data["review"]["original_saved"] = original
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
        elif not section or not section.get("adopted", True):
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


def with_original_hint(state, project):
    section = next((s for s in state["outline"]["sections"] if s["id"] == state["section"]), None)
    if section and state["review"] is not None:
        hint = section_review.original_hint(project, section["title"], state["review"]["documents"])
        if hint:
            state["review"]["original_hint"] = hint
    return state


def ensure_original(project, section_id):
    """Freeze an existing section's pages once, before the AI edits its source."""
    if not section_id:
        return None
    with closing(pr.connect(database_path(project))) as db:
        plan = next((s for s in outline.state(db, project)["sections"] if s["id"] == section_id), None)
        if plan is None or section_review.status(db, project, section_id)["documents"]:
            return None
        try:
            located = section_review.source_section(db, project, plan)
            if located is None or not located.paragraphs:
                return None
            saved = section_review.import_reference(db, project, section_id)
        except (ValueError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            return {"error": f"未能自动保存改前排版：{exc}"}
        doc = next(d for d in saved["documents"] if d["id"] == saved["reference_id"])
        return {"reference": doc["id"], "title": doc["title"], "pages": doc["pages"]}


def workspace_call(name, args, project):
    if name == "workspace_status":
        original = ensure_original(project, selected_section(project, args.get("section")))
        state = workspace.read_snapshot(project, args.get("section"))
        if original and state["review"] is not None:
            state["review"]["original_saved"] = original
        if "section" in args and state["section"] != args["section"]:
            raise ValueError("所选章节不存在，请刷新工作区。")
        state = with_original_hint(state, project)
        if database_path(project).is_file():
            # Figure/table status is supplementary: a problem there (an unreadable data
            # file, say) must never hide the outline, prose or reviews.
            try:
                with closing(sqlite3.connect(database_path(project).as_uri() + "?mode=ro", uri=True)) as db:
                    floats = assets.state(db, project)
                build = floats["build"]
                state["floats"] = {"open_requests": [{k: n[k] for k in ("id", "target", "label", "text")}
                                                     for n in floats["notes"] if n["status"] == "open"],
                                   "latest_build": build and {k: build.get(k) for k in ("build", "created", "stale")},
                                   "confirmed": sorted(floats["confirmed"])}
            except Exception as exc:  # noqa: BLE001 - reported, never fatal
                state["floats"] = {"error": "未能读取图表状态，大纲、正文和审阅记录不受影响。", "detail": str(exc)[:300]}
        return state
    if name == "open_writing_workspace":
        return open_workspace(project, args)
    path = database_path(project)
    with closing(pr.connect(path)) as db:
        if name == "update_research_assets":
            plan = outline.update_assets(db, project, args["version"], args["question"], args["evidence"],
                                         affected_sections=args.get("affected_sections", []))
            return {"outline": plan}
        if name == "propose_paper_outline":
            plan = outline.propose(db, project, args["version"], args["sections"], args.get("reopen"))
            return attach_room({"outline": plan, "note": "请作者在写作间的整篇大纲中读过后采用。"}, project,
                               query={"view": "paper"})
        if name == "suggest_section_plan":
            plan = outline.set_hint(db, project, args["section"], args["text"])
            return attach_room({"outline": plan}, project, query={"view": "section", "section": args["section"]})
        if name == "save_paragraph_draft":
            result = section_review.save_paragraph_draft(
                db, project, args["section"], args["paragraph"], args["plan_revision"],
                args.get("text"), expected_version=args["expected_version"])
            section = next((s for s in outline.state(db, project)["sections"] if s["id"] == args["section"]), None)
            hint = section and section_review.original_hint(project, section["title"], result["documents"])
            return {**result, "original_hint": hint} if hint else result
        options = {k:args[k] for k in ("pages","minimum","expected_revision","title","responses") if k in args}
        for key in ("tex", "pdf"):
            if key in args:
                options[key] = manuscript_file(project, args[key])
        if name == "import_section_reference":
            return section_review.import_reference(db, project, args["section"], **options)
        if name == "publish_floats":
            answered = assets.check_responses(db, args.get("responses", []))
            result = assets.build(db, project, "ai")
            if answered:
                result = assets.answer(db, project, answered, result["build"]["build"])
            build = result["build"]
            return {"build": build["build"], "pages": build["pages"],
                    "floats": [{k: f.get(k) for k in ("key", "kind", "number", "label", "physical", "where")} for f in build["floats"]],
                    "open_requests": [n for n in result["notes"] if n["status"] == "open"],
                    "note": "作者可在写作间的「图表与数据」中查看。"}
        if name == "bind_section_source":
            return section_review.bind_source(db, project, args["section"], args["tex"], args.get("label"))
        result = section_review.publish_section(db, project, args["section"], **options)
    return attach_room(result, project, query={"view":"review","section":args["section"]})


def invoke(name, a):
    validate(name,a)
    raw = Path(a["project"]).expanduser()
    if not raw.is_absolute() or not raw.is_dir():
        raise ValueError("Use the absolute path to the active paper's existing directory.")
    root = raw.resolve()
    path = database_path(root)
    if name in ("open_writing_workspace", "workspace_status", "update_research_assets", "bind_section_source", "publish_floats",
                "propose_paper_outline", "suggest_section_plan",
                "save_paragraph_draft", "import_section_reference", "publish_section"):
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


MESSAGE_KEYS = {"message", "problem", "error", "note", "label"}


def author_language(arguments):
    """Messages follow the language the author chose in the workspace."""
    project = arguments.get("project") if isinstance(arguments, dict) else None
    try:
        root = Path(project).expanduser().resolve() if isinstance(project, str) else None
    except OSError:
        root = None
    return i18n.language(root if root and root.is_dir() else None)


def localize(value, lang):
    """Translate Paperroom's own messages, never the author's text."""
    if lang != "en":
        return value
    if isinstance(value, dict):
        return {k: (i18n.translate(v, lang) if k in MESSAGE_KEYS and isinstance(v, str) else localize(v, lang))
                for k, v in value.items()}
    if isinstance(value, list):
        return [localize(v, lang) for v in value]
    return value


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
        lang = author_language(params.get("arguments"))
        try:
            payload = localize(invoke(params.get("name",""),params.get("arguments",{})), lang)
            result = {"content":[{"type":"text","text":json.dumps(payload,ensure_ascii=False)}]}
        except (ValueError, TypeError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
            result = {"content":[{"type":"text","text":i18n.translate(str(exc), lang)}],"isError":True}
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
