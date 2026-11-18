"""Author-owned, human-editable three-level outline kept in the manuscript's paper.md."""

import hashlib
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

BEGIN = "<!-- paperroom:outline:begin -->"
END = "<!-- paperroom:outline:end -->"
HEADER = re.compile(r"<!-- paperroom:v2 (\d+) ([0-9a-f]{64}) -->")
ID = r"[0-9a-f]{12}"
STAMP = r"(?:-|[0-9a-f]{64})"
SECTION = re.compile(rf"<!-- paperroom:section ({ID}) ({STAMP}) -->")
PARA = re.compile(rf"<!-- paperroom:paragraph ({ID}) (\d+) ({STAMP}) -->")
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


def _public(doc):
    sections = []
    for s in doc["sections"]:
        planned = bool(doc["question"] and doc["evidence"] and s["paragraphs"]) and s[
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
                planned=planned,
                paragraphs=paragraphs,
            )
        )
    return dict(
        version=doc["version"],
        question=doc["question"],
        evidence=doc["evidence"],
        sections=sections,
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
            f'<!-- paperroom:section {section["id"]} {section["plan"]} -->',
            "### " + section["title"],
            *_quote(section["purpose"]),
        ]
        for index, p in enumerate(section["paragraphs"], 1):
            lines += [
                "",
                f'<!-- paperroom:paragraph {p["id"]} {p["revision"]} {p["approval"]} -->',
                f"#### Paragraph {index}",
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
        )
        sections.append(s)
        while current and PARA.fullmatch(current):
            meta = take(PARA)
            take(re.compile(r"#### Paragraph [1-9]\d*"))
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


def _load(path):
    if path.is_symlink():
        raise ValueError("paper.md 是符号链接。请在项目根目录使用普通 Markdown 文件。")
    raw = path.read_bytes() if path.exists() else None
    source = raw.decode("utf-8") if raw is not None else ""
    markers = list(
        re.finditer(r"(?m)^" + re.escape(BEGIN) + r"\r?$|^" + re.escape(END) + r"\r?$", source)
    )
    if not markers:
        if re.search(r"(?m)^<!-- paperroom:(?:v2|section|paragraph) ", source):
            raise ValueError(MALFORMED)
        empty = dict(serial=0, version=0, question="", evidence="", sections=[])
        separator = "\n\n" if source and not source.endswith("\n") else "\n" if source else ""
        return raw, source + separator, "\n", empty
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
    return raw, source[: start.start()], source[end.end() :], doc


def state(db, project):
    """Read-only, including when no Paperroom project has been started."""
    return _public(_load(Path(project) / "paper.md")[3])


def _change(db, project, version, mutate):
    path = Path(project) / "paper.md"
    # The shared DB lock serializes multiple agents with browsers and review publishing.
    # Markdown is the only source of truth for outlines; one atomic rename publishes everything.
    with db:
        db.execute("BEGIN IMMEDIATE")
        original, before, after, doc = _load(path)
        if type(version) is not int or version != doc["version"]:
            raise ValueError("大纲已更新，请重新载入后提交。")
        mutate(doc)
        body = _body(doc)
        serial = doc["serial"] + 1
        block = f"{BEGIN}\n<!-- paperroom:v2 {serial} {_digest(body)} -->\n{body}{END}"
        data = (before + block + after).encode("utf-8")
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".paperroom-", delete=False
            ) as tmp:
                temp_name = tmp.name
                if original is not None:
                    os.fchmod(tmp.fileno(), path.stat().st_mode & 0o777)
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
            if path.is_symlink() or (path.read_bytes() if path.exists() else None) != original:
                raise ValueError("paper.md 已由其他编辑器修改，请重新载入。")
            os.replace(temp_name, path)
            temp_name = None
        finally:
            if temp_name is not None:
                os.unlink(temp_name)
        doc["version"] = serial
    return _public(doc)


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
                item.update(title="", plan="-", paragraphs=[])
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


def submit(db, project, version, level, items, section=None, paragraph=None):
    """Browser-only author action. Items contain stable IDs for retained entries."""
    if not isinstance(items, list) or not items:
        raise ValueError("请填写至少一个大纲条目。")

    def change(doc):
        if not doc["question"] or not doc["evidence"]:
            raise ValueError("请先提供 research question 与已有实验或证据概述。")
        if level == "paper":
            doc["sections"] = _ordered_items(doc["sections"], items, level)
            return
        s = _item(doc["sections"], section, "章节")
        if level == "section":
            s["paragraphs"] = _ordered_items(s["paragraphs"], items, level)
            s["plan"] = _section_stamp(s)
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
        else:
            raise ValueError("未知的大纲层级。")

    return _change(db, project, version, change)


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
