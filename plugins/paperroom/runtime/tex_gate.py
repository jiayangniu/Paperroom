#!/usr/bin/env python3
"""Write-time paragraph gate for Claude Code and Codex hooks.

Small edits to manuscript prose pass silently. A blank-line paragraph that is new,
or more than half rewritten (see latex_source.is_whole_paragraph), may only be
written where the author has written that paragraph's sentence intents.

- PreToolUse on file edits (Claude Code Edit/Write/MultiEdit, Codex apply_patch):
  the pending .tex content is checked and the edit is denied with a reason.
- PreToolUse/PostToolUse on shell commands: a command cannot be previewed, so the
  paragraphs are compared before and after it and the AI is asked to undo.

Anything unexpected lets the tool run: registration and publishing check again.
"""
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import latex_source as L  # noqa: E402
import outline  # noqa: E402
import section_review  # noqa: E402
import i18n  # noqa: E402
import re  # noqa: E402

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "apply_patch"}
SHELL_TOOLS = {"Bash", "shell", "exec_command", "local_shell"}


def find_project(start):
    """The nearest folder holding a Paperroom workspace, found the same way the
    workspace finds its database (including paperroom_tool/.paperroom/)."""
    path = Path(start).resolve()
    for folder in [path, *path.parents]:
        if (folder / ".paperroom" / "project.sqlite3").is_file() or \
                (folder / "paperroom_tool" / ".paperroom" / "project.sqlite3").is_file():
            return folder
    return None


def _resolve(path, cwd):
    candidate = Path(path)
    return (candidate if candidate.is_absolute() else Path(cwd) / candidate).resolve()


def _current(path, files):
    if path in files:
        return files[path]
    return path.read_text("utf-8") if path.is_file() else ""


def apply_patch_files(patch, cwd):
    """New contents for each file in a Codex apply_patch envelope."""
    lines = patch.splitlines()
    if not any(line.strip() == "*** Begin Patch" for line in lines[:3]):
        return None
    files, i = {}, 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("*** Add File: "):
            path, body, i = _resolve(line[14:].strip(), cwd), [], i + 1
            while i < len(lines) and not lines[i].startswith("*** "):
                body.append(lines[i][1:] if lines[i].startswith("+") else lines[i])
                i += 1
            files[path] = "\n".join(body) + "\n"
        elif line.startswith("*** Delete File: "):
            files[_resolve(line[17:].strip(), cwd)] = None
            i += 1
        elif line.startswith("*** Update File: "):
            path, i = _resolve(line[17:].strip(), cwd), i + 1
            target = path
            if i < len(lines) and lines[i].startswith("*** Move to: "):
                target, i = _resolve(lines[i][13:].strip(), cwd), i + 1
            content = _current(path, files)
            if content is None:
                raise ValueError("update of a deleted file")
            text, trailing = content.split("\n"), content.endswith("\n")
            if trailing:
                text = text[:-1]
            hunks, hunk = [], []
            while i < len(lines) and (not lines[i].startswith("*** ") or lines[i] == "*** End of File"):
                row = lines[i]
                if row.startswith("@@"):
                    if hunk:
                        hunks.append(hunk)
                    hunk = []
                elif row != "*** End of File":
                    hunk.append((row[:1] or " ", row[1:]))
                i += 1
            if hunk:
                hunks.append(hunk)
            cursor = 0
            for hunk in hunks:
                old = [t for op, t in hunk if op in " -"]
                new = [t for op, t in hunk if op in " +"]
                at = next((k for k in range(cursor, len(text) - len(old) + 1)
                           if [x.rstrip() for x in text[k:k + len(old)]] == [x.rstrip() for x in old]), None)
                if at is None:
                    raise ValueError("patch context not found")
                text[at:at + len(old)] = new
                cursor = at + len(new)
            if target != path:
                files[path] = None
            files[target] = "\n".join(text) + ("\n" if trailing else "")
        else:
            i += 1
    return files


def pending_files(payload):
    """{resolved path: new text or None} for the edit a hook is about to allow."""
    tool, data = payload.get("tool_name"), payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    if tool == "apply_patch":
        patch = data.get("command") or data.get("patch") or data.get("input")
        if isinstance(patch, list):
            patch = next((part for part in patch if isinstance(part, str) and "*** Begin Patch" in part), None)
        return apply_patch_files(patch, cwd) if isinstance(patch, str) else None
    path = data.get("file_path")
    if not isinstance(path, str):
        return None
    path = _resolve(path, cwd)
    if tool == "Write":
        return {path: data.get("content", "")}
    current = path.read_text("utf-8") if path.is_file() else ""
    edits = data.get("edits") if tool == "MultiEdit" else [data]
    for edit in edits or []:
        old, new = edit.get("old_string", ""), edit.get("new_string", "")
        if old not in current:
            return None  # the tool will fail on its own
        current = current.replace(old, new) if edit.get("replace_all") else current.replace(old, new, 1)
    return {path: current}


def _units(project, files=None):
    """{key: (title, [paragraph dicts], lines, start, main)} for every prose unit of
    every main .tex (a paper may have, say, a conference and a journal version)."""
    units = {}
    for main in L.main_files(project, files):
        relative = main.relative_to(Path(project).resolve()).as_posix()
        lines = L.expand(project, main, files)
        for title, start, end in L.sections(lines):
            units[relative + "\u0000" + L._title_key(title)] = (title, L.paragraphs(lines, start, end), lines, start, relative)
    return units


def _default_main(project):
    """The main file an unbound section resolves to in the workspace, or None when
    the project has several and none is the obvious one."""
    try:
        main = L.find_main(project)
    except L.SourceError:
        return None
    return main and main.relative_to(Path(project).resolve()).as_posix()


def _outline_map(db, project, units):
    """Match prose units to the author's outline exactly as the workspace locates a
    section: a bound section only in its bound main file (by label, else title); an
    unbound one by title in the main file the workspace would pick."""
    sections = outline.state(db, project)["sections"]
    default = _default_main(project)
    mapped, elsewhere = {}, {}
    for section in sections:
        binding = section_review._binding(db, section["id"])
        home = binding.get("main") or default
        for key, (title, _, lines, start, main) in units.items():
            if binding.get("label"):
                matches = binding["label"] in L.labels_near(lines, start)
            else:
                matches = L._title_key(title) == L._title_key(section["title"])
            if not matches:
                continue
            if main == home:
                mapped[key] = section
            else:
                elsewhere.setdefault(key, (section, home))
    return mapped, elsewhere, bool(sections)


def violations(project, before, after_units, db):
    """Whole paragraphs written without the author's intents, and lineage to record.

    A paragraph is identified by where it sits in the source (file and line), so a
    file shared by two main files (a conference and a journal version, say) is
    judged by the section it is bound to, and reported once."""
    mapped, elsewhere, has_outline = _outline_map(db, project, after_units)
    owner = {}
    for key, section in mapped.items():
        for index, item in enumerate(after_units[key][1]):
            owner.setdefault((item["file"], item["line"]), (section, index))
    problems, lineage, cached = [], [], {}

    def candidates_for(section):
        if section["id"] not in cached:
            cached[section["id"]] = section_review.gate_candidates(db, section["id"])
        return cached[section["id"]]

    for key, (title, paragraphs, lines, _, main) in after_units.items():
        old = before.get(key, [])
        if [L.plain(p) for p in old] == [L.plain(p["text"]) for p in paragraphs]:
            continue
        roots = [section_review.lineage_root(db, text) for text in old]
        for index, item in enumerate(paragraphs):
            text = item["text"]
            section, position = owner.get((item["file"], item["line"]), (mapped.get(key), index))
            candidates = (candidates_for(section) if section else []) + roots
            known = {L.plain(c) for c in candidates} | {L.plain(t) for t in old}
            if L.plain(text) in known:
                continue
            base = min(candidates, key=lambda c: L.change(c, text)[0], default="")
            if not L.is_whole_paragraph(base, text):
                lineage.append((text, base))
                continue
            plan = section["paragraphs"][position] if section and position < len(section["paragraphs"]) else None
            if plan and plan["ready"]:
                continue
            where = f"{Path(item['file']).relative_to(project).as_posix()}:{item['line']}"
            if not has_outline:
                reason = "作者还没有写论文大纲"
            elif section is None and key in elsewhere:
                other, home = elsewhere[key]
                reason = (f"作者大纲中的「{other['title']}」对应 {home}，{main} 里的这一节没有作者意图"
                          if home else f"项目有多个主 .tex，作者大纲中的「{other['title']}」还没有绑定主文件")
            elif section is None:
                reason = f"「{title}」不在作者的论文大纲里"
            elif not section["planned"] or plan is None:
                reason = f"作者的「{section['title']}」段落大纲中没有第 {position + 1} 段"
            else:
                reason = f"作者还没有写「{section['title']}」第 {position + 1} 段的逐句意图"
            message = f"{where} 是新写或改写超过一半的整段正文，但{reason}。"
            if message not in problems:
                problems.append(message)
    return problems, lineage


GUIDE = ("Paperroom 只拦截整段代写：小幅修改可以直接进行。请先请作者在写作间完成这一段的大纲和逐句意图"
         "（open_writing_workspace），再按句意写这一段；或只做小幅修改。")


def _plain_before(units):
    return {key: [p["text"] for p in paragraphs] for key, (_, paragraphs, _, _, _) in units.items()}


def _database(project):
    import workspace_server
    return workspace_server.database_path(project)


def _connect(project):
    db = sqlite3.connect(_database(project), timeout=5)
    db.execute("PRAGMA journal_mode=TRUNCATE")  # never delete the journal (see paperroom.connect)
    return db


OUTLINE_GUIDE = ("paper.md 保存作者的三级大纲，不能直接编辑。研究问题和证据请用 update_research_assets 记录，"
                 "章节安排请用 propose_paper_outline 草拟并由作者采用；段落大纲和逐句意图由作者在写作间填写"
                 "（open_writing_workspace）。")


def check_edit(payload):
    files = pending_files(payload) or {}
    for path in files:
        project = find_project(path.parent)
        if path.name == "paper.md" and project is not None and path == project / "paper.md":
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": OUTLINE_GUIDE}}
    files = {p: t for p, t in files.items() if p.suffix.lower() == ".tex"}
    if not files:
        return None
    project = find_project(next(iter(files)).parent)
    if project is None:
        return None
    files = {p: t for p, t in files.items() if p.is_relative_to(project)}
    before = _units(project)
    after = _units(project, files)
    with closing(_connect(project)) as db:
        problems, lineage = violations(project, _plain_before(before), after, db)
        if problems:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": " ".join(problems) + " " + GUIDE}}
        section_review.record_lineage(db, lineage)
    return None


def _snapshot_path(payload):
    folder = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or os.environ.get("PLUGIN_DATA")
                  or Path(tempfile.gettempdir()) / "paperroom-gate")
    folder.mkdir(parents=True, exist_ok=True)
    key = "".join(c for c in str(payload.get("tool_use_id") or payload.get("session_id") or "last") if c.isalnum())
    return folder / f"shell-{key or 'last'}.json"


def before_shell(payload):
    project = find_project(payload.get("cwd") or os.getcwd())
    if project is None:
        return None
    units = _units(project)
    outline_text = (project / "paper.md").read_text("utf-8") if (project / "paper.md").is_file() else ""
    _snapshot_path(payload).write_text(json.dumps({"project": str(project), "units": _plain_before(units),
                                                   "outline": outline_text}))
    return None


def after_shell(payload):
    path = _snapshot_path(payload)
    if not path.is_file():
        return None
    saved = json.loads(path.read_text())
    path.unlink()
    project = Path(saved["project"])
    outline_text = (project / "paper.md").read_text("utf-8") if (project / "paper.md").is_file() else ""
    if outline_text != saved.get("outline", outline_text):
        return {"decision": "block", "reason": "刚才的命令改动了 paper.md。请恢复命令执行前的内容。" + OUTLINE_GUIDE}
    after = _units(project)
    with closing(_connect(project)) as db:
        problems, lineage = violations(project, saved["units"], after, db)
        if problems:
            return {"decision": "block", "reason": "刚才的命令写入了整段正文。" + " ".join(problems) +
                    " 请撤回这些段落的改动，恢复命令执行前的内容。" + GUIDE}
        section_review.record_lineage(db, lineage)
    return None


def handle(payload):
    event, tool = payload.get("hook_event_name"), payload.get("tool_name")
    if event == "PreToolUse" and tool in EDIT_TOOLS:
        return check_edit(payload)
    if tool in SHELL_TOOLS:
        return before_shell(payload) if event == "PreToolUse" else after_shell(payload)
    return None


def localize(result, payload):
    """Reasons and reminders follow the author's language."""
    if not result:
        return result
    project = find_project(payload.get("cwd") or os.getcwd())
    lang = i18n.language(project)
    if lang != "en":
        return result
    exact, _ = i18n.catalog()
    def text(value):
        # Known multi-sentence guidance first, then the remaining sentences one by one.
        for zh in (GUIDE, OUTLINE_GUIDE):
            value = value.replace(zh, " " + exact[zh] + " ")
        pieces = re.split(r"(?<=[。])\s*", value)
        return " ".join(i18n.translate(piece.strip()) for piece in pieces if piece.strip())
    out = json.loads(json.dumps(result))
    specific = out.get("hookSpecificOutput", {})
    for key in ("permissionDecisionReason",):
        if key in specific:
            specific[key] = text(specific[key])
    if "reason" in out:
        out["reason"] = text(out["reason"])
    return out


def main():
    try:
        payload = json.load(sys.stdin)
        result = localize(handle(payload), payload)
    except Exception:  # never stop the AI's work because the gate itself failed
        return
    if result:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
