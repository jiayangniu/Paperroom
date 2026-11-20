"""Author-led, human-editable three-level outline kept in the manuscript's paper.md.

The paper level (sections and their roles) may be drafted by the AI after talking
with the author; each section carries the stamp of the author's adoption, and a
section's paragraph plan opens only once the author has adopted it as it stands.
Paragraph plans and sentence intents are written by the author. The AI may leave a
reference for a section's paragraph plan (a hint), stored beside the outline.
"""

import hashlib
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

import journal

BEGIN = "<!-- paperroom:outline:begin -->"
END = "<!-- paperroom:outline:end -->"
HEADER = re.compile(r"<!-- paperroom:v2 (\d+) ([0-9a-f]{64}) -->")
ID = r"[0-9a-f]{12}"
STAMP = r"(?:-|[0-9a-f]{64})"
# The third stamp is the author's adoption of the section's title and role; files
# written before 0.6.2 lack it and count as adopted (the author wrote them).
SECTION = re.compile(rf"<!-- paperroom:section ({ID}) ({STAMP})(?: ({STAMP}))? -->")
PARA = re.compile(rf"<!-- paperroom:paragraph ({ID}) (\d+) ({STAMP}) -->")
SUBHEADING = "<!-- paperroom:subheading -->"
QUESTION = "## Research question"
EVIDENCE = "## Experimental evidence"
OUTLINE = "## Paper outline"
MALFORMED = (
    "paper.md 的 Paperroom 大纲格式有改动。请保留原文并复原大纲中的标题、编号及 "
    "paperroom 注释；可直接编辑引用行和编号后的句意。"
)


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stamp(*values):
    return _digest(json.dumps(values, ensure_ascii=False, separators=(",", ":")))


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"请填写{label}。")
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _section_stamp(section):
    return _stamp(section["id"], section["title"], section["purpose"])


def _paragraph_stamp(section, paragraph):
    return _stamp(
        _section_stamp(section), paragraph["id"], paragraph["purpose"], paragraph["sentences"]
    )


def adopted(section):
    return section["adopt"] == _section_stamp(section)


def _public(doc, hints=None):
    sections = []
    for s in doc["sections"]:
        planned = bool(doc["question"] and doc["evidence"] and s["paragraphs"]) and adopted(s) and s[
            "plan"
        ] == _section_stamp(s)
        paragraphs = [
            dict(
                id=p["id"],
                purpose=p["purpose"],
                revision=p["revision"],
                sentences=p["sentences"],
                ready=planned and bool(p["sentences"]) and p["approval"] == _paragraph_stamp(s, p),
            )
            for p in s["paragraphs"]
        ]
        sections.append(
            dict(
                id=s["id"],
                title=s["title"],
                purpose=s["purpose"],
                adopted=adopted(s),
                planned=planned,
                paragraphs=paragraphs,
                subheadings=s.get("subheadings", []),
                **({"hint": hints[s["id"]]} if hints and s["id"] in hints else {}),
            )
        )
    return dict(
        version=doc["version"],
        question=doc["question"],
        evidence=doc["evidence"],
        sections=sections,
        **({"hint": hints[""]} if hints and "" in hints else {}),
    )


def _quote(value):
    return ["> " + row for row in value.split("\n")]


def _body(doc):
    lines = [
        QUESTION,
        *_quote(doc["question"]),
        "",
        EVIDENCE,
        *_quote(doc["evidence"]),
        "",
        OUTLINE,
    ]
    for section in doc["sections"]:
        lines += [
            "",
            f'<!-- paperroom:section {section["id"]} {section["plan"]} {section["adopt"]} -->',
            "### " + section["title"],
            *_quote(section["purpose"]),
        ]
        headings = iter(section.get("subheadings", []))
        next_heading = next(headings, None)
        depth = "####"
        for index in range(len(section["paragraphs"]) + 1):
            while next_heading and next_heading["before"] == index:
                lines.extend(["", SUBHEADING, "#### " + next_heading["title"]])
                next_heading = next(headings, None)
                depth = "#####"
            if index == len(section["paragraphs"]):
                break
            p = section["paragraphs"][index]
            lines += [
                "",
                f'<!-- paperroom:paragraph {p["id"]} {p["revision"]} {p["approval"]} -->',
                f"{depth} Paragraph {index + 1}",
                *_quote(p["purpose"]),
            ]
            for n, sentence in enumerate(p["sentences"], 1):
                first, *rest = sentence.split("\n")
                lines.append(f"{n}. {first}")
                lines.extend("   " + row for row in rest)
    return "\n".join(lines) + "\n"


def _parse_body(body):
    # Blank separators are optional. Blank lines inside author text keep their > or indentation.
    lines = iter(line for line in body.split("\n") if line != "")
    current = next(lines, None)

    def take(pattern):
        nonlocal current
        match = pattern.fullmatch(current or "")
        if not match:
            raise ValueError(MALFORMED)
        current = next(lines, None)
        return match

    def heading(text):
        take(re.compile(re.escape(text)))

    def quote():
        values = []
        while current is not None and (current == ">" or current.startswith("> ")):
            values.append(take(re.compile(r"> ?(.*)"))[1])
        if not values:
            raise ValueError(MALFORMED)
        return "\n".join(values).strip()

    def identifier(value):
        if value in ids:
            raise ValueError(MALFORMED)
        ids.add(value)
        return value

    ids = set()
    heading(QUESTION)
    question = quote()
    heading(EVIDENCE)
    evidence = quote()
    heading(OUTLINE)
    sections = []
    while current is not None:
        meta = take(SECTION)
        title = _text(take(re.compile(r"### (.+)"))[1], "章节名称")
        s = dict(
            id=identifier(meta[1]),
            plan=meta[2],
            title=title,
            purpose=_text(quote(), "章节作用"),
            paragraphs=[],
            subheadings=[],
        )
        s["adopt"] = meta[3] or _section_stamp(s)
        sections.append(s)
        while current and (current == SUBHEADING or PARA.fullmatch(current)):
            if current == SUBHEADING:
                heading(SUBHEADING)
                title = _text(take(re.compile(r"#### (.+)"))[1], "小标题")
                s["subheadings"].append(dict(before=len(s["paragraphs"]), title=title))
                continue
            meta = take(PARA)
            take(re.compile(r"#{4,5} Paragraph [1-9]\d*"))
            p = dict(
                id=identifier(meta[1]),
                revision=int(meta[2]),
                approval=meta[3],
                purpose=_text(quote(), "段落作用"),
                sentences=[],
            )
            s["paragraphs"].append(p)
            while current and re.match(r"\d+\. ", current):
                parts = [take(re.compile(r"[1-9]\d*\. (.+)"))[1]]
                while current is not None and current.startswith("   "):
                    parts.append(take(re.compile(r"   (.*)"))[1])
                p["sentences"].append(_text("\n".join(parts), "句意"))
    return dict(question=question, evidence=evidence, sections=sections)


def _raw(path):
    if path.is_symlink():
        raise ValueError("paper.md 是符号链接。请在项目根目录使用普通 Markdown 文件。")
    return path.read_bytes() if path.exists() else None


def _parse(raw):
    source = raw.decode("utf-8") if raw is not None else ""
    markers = list(
        re.finditer(r"(?m)^" + re.escape(BEGIN) + r"\r?$|^" + re.escape(END) + r"\r?$", source)
    )
    if not markers:
        if re.search(r"(?m)^<!-- paperroom:(?:v2|section|paragraph) ", source):
            raise ValueError(MALFORMED)
        empty = dict(serial=0, version=0, question="", evidence="", sections=[])
        separator = "\n\n" if source and not source.endswith("\n") else "\n" if source else ""
        return source + separator, "\n", empty
    if (
        len(markers) != 2
        or markers[0][0].rstrip("\r") != BEGIN
        or markers[1][0].rstrip("\r") != END
    ):
        raise ValueError(MALFORMED)
    start, end = markers
    middle = source[start.end() : end.start()].replace("\r\n", "\n").removeprefix("\n")
    header, _, body = middle.partition("\n")
    match = HEADER.fullmatch(header)
    if not match:
        raise ValueError(MALFORMED)
    doc = _parse_body(body)
    serial = int(match[1])
    actual = _digest(body)
    # External Markdown edits participate in compare-and-swap even without bumping the header.
    version = serial if actual == match[2] else 2**48 + int(actual[:12], 16)
    doc.update(serial=serial, version=version)
    return source[: start.start()], source[end.end() :], doc


def _file_digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _pending(db):
    # Read-only discovery preserves projects predating the timestamp journal.
    if db is None or not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_outline_pending'"
    ).fetchone():
        return None
    return db.execute("SELECT original_hash, content FROM v2_outline_pending WHERE id=1").fetchone()


def _hints(db):
    if db is None or not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_section_hints'"
    ).fetchone():
        return {}
    return {section: dict(text=text, created=created)
            for section, text, created in db.execute("SELECT section, text, created FROM v2_section_hints")}


def state(db, project):
    """Read-only, including if a process stopped just after accepting an outline."""
    pending = _pending(db)
    raw = _raw(Path(project) / "paper.md")
    if pending and pending[0] == _file_digest(raw):
        raw = pending[1]
    return _public(_parse(raw)[2], _hints(db))


def _replace(path, original, data):
    tmp = tempfile.NamedTemporaryFile(dir=path.parent, prefix=".paperroom-", delete=False)
    temp = Path(tmp.name)
    try:
        with tmp:
            if original is not None:
                os.chmod(temp, path.stat().st_mode & 0o777)
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
        if _raw(path) != original:
            raise ValueError("paper.md 已由其他编辑器修改，请重新载入。")
        os.replace(temp, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def _flush_pending(db, path):
    pending = _pending(db)
    if pending:
        raw = _raw(path)
        if pending[0] == _file_digest(raw):
            _replace(path, raw, pending[1])
        # A completed rename or a subsequent external edit already owns paper.md.
        db.execute("DELETE FROM v2_outline_pending WHERE id=1")


def _change(db, project, version, mutate):
    path = Path(project) / "paper.md"
    with db:
        db.execute("BEGIN IMMEDIATE")
        _flush_pending(db, path)
        original = _raw(path)
        before, after, doc = _parse(original)
        if type(version) is not int or version != doc["version"]:
            raise ValueError("大纲已更新，请重新载入后提交。")
        submission = mutate(doc)
        body = _body(doc)
        serial = doc["serial"] + 1
        block = f"{BEGIN}\n<!-- paperroom:v2 {serial} {_digest(body)} -->\n{body}{END}"
        data = (before + block + after).encode("utf-8")
        if submission is None:
            _replace(path, original, data)
        else:
            # Commit accepted content and its event together. The file rename may be
            # replayed after process death without recapturing the time or the event.
            if _raw(path) != original:
                raise ValueError("paper.md 已由其他编辑器修改，请重新载入。")
            db.execute("""CREATE TABLE IF NOT EXISTS v2_outline_pending (
                id INTEGER PRIMARY KEY CHECK(id=1), original_hash TEXT, content BLOB NOT NULL)""")
            db.execute("INSERT INTO v2_outline_pending VALUES (1,?,?)", (_file_digest(original), data))
            journal.append(db, **submission, revision=serial)
        doc["version"] = serial
    if submission is not None:
        with db:
            db.execute("BEGIN IMMEDIATE")
            _flush_pending(db, path)
    return _public(doc, _hints(db))


def _item(items, key, label):
    for item in items:
        if item["id"] == key:
            return item
    raise ValueError(f"找不到指定的{label}，请重新载入。")


def _invalidate_paragraph(p):
    p["approval"] = "-"
    p["revision"] += 1


def _invalidate_section(section):
    section["plan"] = "-"
    for p in section["paragraphs"]:
        _invalidate_paragraph(p)


def update_assets(db, project, version, question, evidence, affected_sections=None):
    """Save author-provided assets; a new result need not invalidate unrelated writing."""

    def change(doc):
        if not isinstance(question, str) or not isinstance(evidence, str):
            raise ValueError("研究问题和证据概述必须是文字。")
        doc["question"] = question.replace("\r\n", "\n").replace("\r", "\n").strip()
        doc["evidence"] = evidence.replace("\r\n", "\n").replace("\r", "\n").strip()
        if affected_sections is not None:
            if not isinstance(affected_sections, list) or not all(
                isinstance(i, str) for i in affected_sections
            ):
                raise ValueError("请用章节 ID 列出需要复核的章节。")
            for key in dict.fromkeys(affected_sections):
                _invalidate_section(_item(doc["sections"], key, "章节"))

    return _change(db, project, version, change)


def _ordered_items(previous, items, level):
    """Existing IDs survive reordering. A changed purpose only reopens its own content."""
    used = set()
    output = []
    for entry in items:
        if not isinstance(entry, dict):
            raise ValueError("请填写大纲条目。")
        purpose = _text(entry.get("purpose"), "作用")
        key = entry.get("id")
        if key is not None:
            item = _item(previous, key, "现有条目")
        else:
            item = dict(id=secrets.token_hex(6), purpose=purpose)
            if level == "paper":
                item.update(title="", plan="-", adopt="-", paragraphs=[])
            else:
                item.update(revision=0, approval="-", sentences=[])
        if item["id"] in used:
            raise ValueError("大纲中含重复条目。")
        used.add(item["id"])
        if level == "paper":
            title = _text(entry.get("title"), "章节名称")
            if "\n" in title:
                raise ValueError("章节名称请使用一行。")
            if item["title"] != title or item["purpose"] != purpose:
                _invalidate_section(item)
            item["title"] = title
        elif item["purpose"] != purpose:
            _invalidate_paragraph(item)
        item["purpose"] = purpose
        output.append(item)
    return output


def _polish_text(current, before, value, label):
    if current != before:
        raise ValueError("大纲已更新，请重新载入后提交。")
    revised = _text(value, label)
    if revised == current:
        raise ValueError("润色建议与原文相同。")
    return revised


def _polish_entries(changes, fields):
    if not isinstance(changes, list) or not changes:
        raise ValueError("请填写至少一个大纲条目。")
    for entry in changes:
        if not isinstance(entry, dict) or set(entry) != fields:
            raise ValueError("请填写大纲条目。")
        yield entry


def _polished_paragraph(section, paragraph, had_approval):
    paragraph["revision"] += 1
    paragraph["approval"] = _paragraph_stamp(section, paragraph) if had_approval else "-"


def apply_paper_polish(db, project, version, changes):
    """Revise existing adopted section fields, retaining all subordinate text and IDs."""
    def apply(doc):
        seen = set()
        edited = {}
        applied = []
        for change in _polish_entries(changes, {"section", "field", "before", "after"}):
            section = _item(doc["sections"], change["section"], "章节")
            sid, field = section["id"], change["field"]
            if field not in ("title", "purpose"):
                raise ValueError("请填写大纲条目。")
            if (sid, field) in seen:
                raise ValueError("大纲中含重复条目。")
            if sid not in edited:
                if not adopted(section):
                    raise ValueError("请先在整篇大纲中采用这一节的章节安排。")
                had_plan = section["plan"] == _section_stamp(section)
                approved = {p["id"] for p in section["paragraphs"]
                            if p["approval"] == _paragraph_stamp(section, p)}
                edited[sid] = (section, had_plan, approved)
            revised = _polish_text(section[field], change["before"], change["after"],
                                   "章节名称" if field == "title" else "章节作用")
            if field == "title" and "\n" in revised:
                raise ValueError("章节名称请使用一行。")
            applied.append(dict(section=sid, field=field, before=section[field], after=revised))
            section[field] = revised
            seen.add((sid, field))
        for section, had_plan, approved in edited.values():
            section["adopt"] = _section_stamp(section)
            section["plan"] = section["adopt"] if had_plan else "-"
            for p in section["paragraphs"]:
                _polished_paragraph(section, p, p["id"] in approved)
        return dict(kind="paper_polish_adopted", payload=dict(changes=applied))

    return _change(db, project, version, apply)


def apply_paragraph_polish(db, project, version, section, paragraph, changes):
    """Polish saved sentence intents without granting new permission to draft."""
    def apply(doc):
        current = _item(doc["sections"], section, "章节")
        p = _item(current["paragraphs"], paragraph, "段落")
        had_approval = p["approval"] == _paragraph_stamp(current, p)
        applied = []
        seen = set()
        for change in _polish_entries(changes, {"sentence", "before", "after"}):
            number = change["sentence"]
            if type(number) is not int or not 1 <= number <= len(p["sentences"]):
                raise ValueError("请选择本段已有的句意。")
            if number in seen:
                raise ValueError("大纲中含重复条目。")
            old = p["sentences"][number - 1]
            revised = _polish_text(old, change["before"], change["after"], "每句要表达的内容")
            p["sentences"][number - 1] = revised
            applied.append(dict(sentence=number, before=old, after=revised))
            seen.add(number)
        _polished_paragraph(current, p, had_approval)
        return dict(kind="paragraph_polish_adopted", section=section, paragraph=paragraph,
                    payload=dict(changes=applied, plan_revision=p["revision"]))

    return _change(db, project, version, apply)


def apply_section_polish(db, project, version, section, changes):
    """Revise existing paragraph roles and subheadings selected in chat."""
    if not isinstance(changes, list) or not changes:
        raise ValueError("请提供现有段落的润色建议。")

    def apply(doc):
        current = _item(doc["sections"], section, "章节")
        paragraphs = {p["id"]: p for p in current["paragraphs"]}
        headings = dict(enumerate(current.get("subheadings", []), start=1))
        applied = []
        for change in changes:
            if isinstance(change, dict) and set(change) == {"subheading", "before", "title"}:
                number = change["subheading"]
                if type(number) is not int or number not in headings:
                    raise ValueError("找不到指定的小标题，请重新载入。")
                heading = headings.pop(number)
                title = _polish_text(heading["title"], change["before"], change["title"], "小标题")
                if "\n" in title:
                    raise ValueError("小标题请使用一行。")
                applied.append(dict(subheading=number, before=heading["title"], title=title))
                heading["title"] = title
                continue
            if not isinstance(change, dict) or set(change) != {"paragraph", "before", "purpose"}:
                raise ValueError("请提供现有段落的润色建议。")
            pid = change["paragraph"]
            if not isinstance(pid, str) or pid not in paragraphs:
                raise ValueError("润色建议包含未知或重复的段落。")
            paragraph = paragraphs.pop(pid)
            purpose = _polish_text(paragraph["purpose"], change["before"], change["purpose"], "段落作用")
            applied.append(dict(paragraph=pid, before=paragraph["purpose"], purpose=purpose))
            had_approval = paragraph["approval"] == _paragraph_stamp(current, paragraph)
            paragraph["purpose"] = purpose
            _polished_paragraph(current, paragraph, had_approval)
        return dict(kind="section_polish_adopted", section=section, payload=dict(changes=applied))

    return _change(db, project, version, apply)


def submit(db, project, version, level, items, section=None, paragraph=None):
    """Browser-only author action. Items contain stable IDs for retained entries."""
    if not isinstance(items, list) or (not items and level != "section"):
        raise ValueError("请填写至少一个大纲条目。")

    def change(doc):
        if not doc["question"] or not doc["evidence"]:
            raise ValueError("请先提供 research question 与已有实验或证据概述。")
        if level == "paper":
            doc["sections"] = _ordered_items(doc["sections"], items, level)
            for item in doc["sections"]:  # written or edited by the author: adopted as written
                item["adopt"] = _section_stamp(item)
            evidence = dict(question=doc["question"], evidence=doc["evidence"], sections=[
                {k: item[k] for k in ("id", "title", "purpose")} for item in doc["sections"]
            ])
            return dict(kind="paper_outline", payload=evidence)
        s = _item(doc["sections"], section, "章节")
        if not adopted(s):
            raise ValueError("请先在整篇大纲中采用这一节的章节安排。")
        if level == "section":
            if not items and not (s["paragraphs"] or s.get("subheadings")):
                raise ValueError("请填写至少一个大纲条目。")
            paragraphs, subheadings = [], []
            for entry in items:
                if isinstance(entry, dict) and entry.get("type") == "heading":
                    title = _text(entry.get("title"), "小标题")
                    if "\n" in title:
                        raise ValueError("小标题请使用一行。")
                    subheadings.append(dict(before=len(paragraphs), title=title))
                else:
                    paragraphs.append(entry)
            s["subheadings"] = subheadings
            s["paragraphs"] = _ordered_items(s["paragraphs"], paragraphs, level)
            s["plan"] = _section_stamp(s) if paragraphs else "-"
            evidence = dict(title=s["title"], purpose=s["purpose"], paragraphs=[
                {k: item[k] for k in ("id", "purpose")} for item in s["paragraphs"]
            ])
            if subheadings:
                evidence["subheadings"] = subheadings
            return dict(kind="section_outline", section=section, payload=evidence)
        elif level == "paragraph":
            if s["plan"] != _section_stamp(s):
                raise ValueError("请先复核这一节的段落大纲。")
            p = _item(s["paragraphs"], paragraph, "段落")
            sentences = [_text(line, "每句要表达的内容") for line in items]
            stamp_before = p["approval"]
            p["sentences"] = sentences
            p["approval"] = _paragraph_stamp(s, p)
            if stamp_before != p["approval"]:
                p["revision"] += 1
            evidence = dict(section_title=s["title"], section_purpose=s["purpose"],
                            purpose=p["purpose"], sentences=sentences, plan_revision=p["revision"])
            return dict(kind="paragraph_outline", section=section, paragraph=paragraph, payload=evidence)
        else:
            raise ValueError("未知的大纲层级。")

    return _change(db, project, version, change)


def _outline_payload(doc):
    return dict(question=doc["question"], evidence=doc["evidence"], sections=[
        {k: item[k] for k in ("id", "title", "purpose")} for item in doc["sections"]])


def propose(db, project, version, items, reopen=None):
    """The AI drafts the paper level after talking with the author. New or changed
    sections wait for the author's adoption; unchanged ones keep it. A section the
    author has already planned is removed or changed only when listed in reopen,
    i.e. when the author agreed to reconsider it."""
    if not isinstance(items, list) or not items:
        raise ValueError("请提供至少一个章节。")
    if reopen is not None and (not isinstance(reopen, list) or not all(isinstance(i, str) for i in reopen)):
        raise ValueError("reopen 应为章节 ID 列表。")
    allowed = set(reopen or [])

    def change(doc):
        if not doc["question"] or not doc["evidence"]:
            raise ValueError("请先提供 research question 与已有实验或证据概述。")
        before = {s["id"]: (s["title"], s["purpose"], bool(s["paragraphs"] or s.get("subheadings"))) for s in doc["sections"]}
        sections = _ordered_items(doc["sections"], items, "paper")
        kept = {s["id"] for s in sections}
        for key, (title, purpose, planned) in before.items():
            if planned and key not in allowed and (
                    key not in kept or next((s["title"], s["purpose"]) for s in sections if s["id"] == key) != (title, purpose)):
                raise ValueError(f"「{title}」已有作者写的段落大纲。删除或改动这一节会让作者重新确认段落和句意，"
                                 "请先征得作者同意，再把它的 ID 放进 reopen。")
        doc["sections"] = sections
        return dict(kind="paper_outline_proposed", payload=_outline_payload(doc))

    return _change(db, project, version, change)


def adopt(db, project, version):
    """The author adopts the paper outline as it stands (the one click that opens
    each section's paragraph plan)."""
    def change(doc):
        waiting = [s for s in doc["sections"] if not adopted(s)]
        if not waiting:
            raise ValueError("没有待采用的章节。")
        for s in doc["sections"]:
            s["adopt"] = _section_stamp(s)
        return dict(kind="paper_outline_adopted", payload=_outline_payload(doc))

    return _change(db, project, version, change)


def reference_text(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("请提供不超过 4000 字的参考。")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def set_hint(db, project, section, text):
    """Save a sidebar reference; None addresses the whole paper."""
    text = reference_text(text)
    with db:
        db.execute("BEGIN IMMEDIATE")
        title = None
        if section is not None:
            title = _item(state(db, project)["sections"], section, "章节")["title"]
        db.execute("""CREATE TABLE IF NOT EXISTS v2_section_hints (
            section TEXT PRIMARY KEY, text TEXT NOT NULL, created TEXT NOT NULL)""")
        # The empty key is reserved for the paper. All section IDs are nonempty.
        key = "" if section is None else section
        prior = db.execute("SELECT text FROM v2_section_hints WHERE section=?", (key,)).fetchone()
        if not prior or prior[0] != text:
            created = journal.utc_now()
            db.execute("INSERT OR REPLACE INTO v2_section_hints VALUES (?,?,?)", (key, text, created))
            if section is None:
                journal.append(db, "paper_hint", dict(text=text), recorded_at=created)
            else:
                journal.append(db, "section_hint", dict(title=title, text=text), section=section, recorded_at=created)
    return state(db, project)


def require_paragraph(db, project, section, paragraph):
    s = _item(state(db, project)["sections"], section, "章节")
    p = _item(s["paragraphs"], paragraph, "段落")
    if not p["ready"]:
        raise ValueError("这段的逐句意图尚待作者填写或复核。")
    return p


def require_section(db, project, section):
    s = _item(state(db, project)["sections"], section, "章节")
    if not s["planned"] or not all(p["ready"] for p in s["paragraphs"]):
        raise ValueError("本节有段落尚待作者填写或复核逐句意图。")
    return s
