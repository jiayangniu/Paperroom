"""Paragraph drafts and immutable, author-reviewed LaTeX section editions."""
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import sys
import tempfile

import excerpt
import journal
import latex_source
import outline
import paperroom


@contextmanager
def _transaction(db, write=False):
    # The caller can compose a read with another projection on this connection.
    if db is None or db.in_transaction:
        yield
        return
    with db:
        db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield


def _create_tables(db):
    db.execute("""CREATE TABLE IF NOT EXISTS v2_drafts (
        section TEXT, paragraph TEXT, plan_revision INTEGER, version INTEGER, text TEXT,
        PRIMARY KEY (section, paragraph))""")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_editions (
        section TEXT, revision INTEGER, body TEXT, PRIMARY KEY (section, revision))""")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_pages (
        section TEXT, revision INTEGER, page INTEGER, content BLOB,
        PRIMARY KEY (section, revision, page))""")

    db.execute("""CREATE TABLE IF NOT EXISTS v2_references (
        section TEXT, revision INTEGER, section_title TEXT, title TEXT, created TEXT,
        pages INTEGER, fingerprint TEXT, PRIMARY KEY(section, revision),
        UNIQUE(section,title,fingerprint))""")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_baselines (
        section TEXT PRIMARY KEY, body TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_gate_lineage (
        hash TEXT PRIMARY KEY, base TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_sources (
        section TEXT PRIMARY KEY, main TEXT NOT NULL, label TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_reference_assets (
        section TEXT, revision INTEGER, page INTEGER, content BLOB NOT NULL,
        PRIMARY KEY(section, revision, page))""")


def _has_references(db):
    return db is not None and db.execute("SELECT 1 FROM sqlite_master WHERE name='v2_references'").fetchone()


def _document(section, revision, kind, title, created, pages, has_pdf):
    key = ("ref-" if kind == "reference" else "rev-") + str(revision)
    base = f"/api/sections/{section}/documents/{key}"
    return dict(id=key, kind=kind, title=title, created=created, pages=pages,
                pdf_url=base + "/pdf" if has_pdf else None, page_url=base + "/pages/")


def _exists(db):
    return db is not None and bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='v2_editions'").fetchone())


def _positive(value):
    return type(value) is int and value > 0


def _section(db, project, section_id):
    return next((s for s in outline.state(db, project)["sections"] if s["id"] == section_id), None)


def _contents(db, project, section_id):
    section = _section(db, project, section_id)
    drafts, revisions = {}, []
    if _exists(db):
        for p, plan, version, text in db.execute(
                "SELECT paragraph, plan_revision, version, text FROM v2_drafts WHERE section=?",
                (section_id,)):
            drafts[p] = dict(paragraph=p, plan_revision=plan, version=version, text=text, current=False)
        revisions = [json.loads(body) for body, in db.execute(
            "SELECT body FROM v2_editions WHERE section=? ORDER BY revision", (section_id,))]
    documents = [_document(section_id, r["revision"], "edition", r["title"], r["created"],
                           r["pages"], bool(r.get("pdf_sha256"))) for r in revisions]
    if _has_references(db):
        rows = db.execute("""SELECT revision,title,created,pages FROM v2_references
                             WHERE section=? ORDER BY revision""", (section_id,))
        documents.extend(_document(section_id, rev, "reference", title, created, pages, True)
                         for rev, title, created, pages in rows)
    documents.sort(key=lambda doc: doc["created"])
    if section is None and not documents:
        raise ValueError("找不到该章节。")
    paragraphs = section["paragraphs"] if section else []
    for p in paragraphs:
        if p["id"] in drafts:
            d = drafts[p["id"]]
            d["current"] = p["ready"] and d["plan_revision"] == p["revision"]
    last = revisions[-1] if revisions else None
    same = False
    if section is None:
        phase = "archived"
    elif not section["planned"] or not paragraphs or any(not p["ready"] for p in paragraphs):
        phase = "outlining"
    elif any(not drafts.get(p["id"], {}).get("current") for p in paragraphs):
        phase = "drafting"
    else:
        same = bool(last and last["title"] == section["title"] and last["purpose"] == section["purpose"]
                    and [(p["id"], drafts[p["id"]]["version"]) for p in paragraphs]
                    == [(p["id"], p["version"]) for p in last["paragraphs"]])
        phase = ("reviewed" if last["reviewed"] else "review") if same else "ready"
    # The author can still change their outline while reading a frozen edition.
    # Its required reading is attached to the published version, even if all
    # paragraph plans are now different or the section was removed.
    pending = bool(last and not last["reviewed"])
    if pending:
        phase = "review"
    return section, dict(phase=phase, drafts=drafts, revisions=revisions, documents=documents,
                         current_revision=last["revision"] if pending or same else None,
                         review_outline_changed=pending and not same)


HEADING = re.compile(r"\\(?:section|chapter)\*?\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")


def original_hint(project, title, documents):
    """Before the AI's first write to a section with no saved layout, point at an
    existing chapter of the same name so its original is frozen before edits."""
    if documents or not title:
        return None
    root, wanted, found = Path(project).resolve(), _plain(title).casefold(), []
    def candidates():
        for directory, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(files):
                if name.endswith(".tex") and not name.startswith("."):
                    yield Path(directory, name)

    for index, path in enumerate(candidates()):
        if index >= 400 or len(found) >= 5:
            break
        try:
            target = path.resolve(strict=True)
            if not target.is_relative_to(root) or not target.is_file() or target.stat().st_size > 2_000_000:
                continue
            text = target.read_text("utf-8", errors="replace")
        except (OSError, RuntimeError):
            # This optional hint must not interrupt the author's status or save.
            continue
        code = re.sub(r"(?<!\\)%[^\n]*", "", text)
        if any(_plain(m.group(1)).casefold() == wanted for m in HEADING.finditer(code)):
            found.append(path.relative_to(root).as_posix())
    if not found:
        return None
    return dict(files=found, message=(
        "项目源文件中已有同名章节，但 Paperroom 还没有保存它的改前排版。修改这些文件之前，"
        "请先用本节 ID 调用 workspace_status 自动保存，或调用 import_section_reference（不传 tex/pdf 时自动编译主 .tex 并截取本节页面）。"
        "如果这是全新章节，可忽略。"))


def _binding(db, section):
    if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='v2_sources'").fetchone():
        return {}
    row = db.execute("SELECT main, label FROM v2_sources WHERE section=?", (section,)).fetchone()
    return {"main": row[0], "label": row[1]} if row else {}


def source_section(db, project, plan):
    """The section in the paper's LaTeX, or None for a project without a main .tex."""
    return latex_source.section(project, plan["title"], _binding(db, plan["id"]))


def _paragraph_state(draft, found):
    if found is None:
        return "missing"
    if not draft:
        return "unregistered"
    if _plain(draft["text"]) == _plain(found["text"]):
        return "registered"
    return "rewritten" if latex_source.is_whole_paragraph(draft["text"], found["text"]) else "edited"


def source_report(db, project, plan, drafts):
    """Where each outline paragraph lives in the .tex and whether it matches its registration."""
    try:
        located = source_section(db, project, plan)
    except (ValueError, OSError, UnicodeError) as exc:
        return {"error": str(exc)}
    if located is None:
        return None
    found = located.paragraphs
    items = []
    for index, p in enumerate(plan["paragraphs"]):
        item = found[index] if index < len(found) else None
        items.append(dict(paragraph=p["id"], where=located.where(item) if item else None,
                          state=_paragraph_state(drafts.get(p["id"]), item)))
    report = dict(main=located.main.relative_to(located.project).as_posix(), heading=located.where(),
                  found=len(found), expected=len(plan["paragraphs"]), paragraphs=items)
    if plan["paragraphs"] and len(found) != len(plan["paragraphs"]):
        report["problem"] = (f"源码中本节有 {len(found)} 段，作者大纲有 {len(plan['paragraphs'])} 段。"
                             "请让两者按顺序一一对应：调整源码，或请作者修改段落大纲。")
    return report


def status(db, project, section):
    """Include every published edition, even if a later outline invalidates it."""
    with _transaction(db):
        plan, result = _contents(db, project, section)
        if plan is not None:
            report = source_report(db, project, plan, result["drafts"])
            if report is not None:
                result["source"] = report
        return result


def gate_candidates(db, section):
    """Prose a paragraph may be measured against without the author's intents: the
    frozen original, every registered draft and every published version."""
    texts = []
    if db is None:
        return texts
    tables = {name for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "v2_baselines" in tables:
        row = db.execute("SELECT body FROM v2_baselines WHERE section=?", (section,)).fetchone()
        texts += json.loads(row[0]) if row else []
    if "v2_drafts" in tables:
        texts += [t for t, in db.execute("SELECT text FROM v2_drafts WHERE section=?", (section,))]
    if "v2_editions" in tables:
        for body, in db.execute("SELECT body FROM v2_editions WHERE section=?", (section,)):
            texts += [p["text"] for p in json.loads(body)["paragraphs"]]
    return texts


def lineage_hash(text):
    return _digest(_plain(text).encode("utf-8"))


def lineage_root(db, text):
    """Small AI edits are chained back to the prose they started from, so several
    small steps cannot add up to an unplanned rewrite."""
    if db is None or not db.execute("SELECT 1 FROM sqlite_master WHERE name='v2_gate_lineage'").fetchone():
        return text
    row = db.execute("SELECT base FROM v2_gate_lineage WHERE hash=?", (lineage_hash(text),)).fetchone()
    return row[0] if row else text


def record_lineage(db, pairs):
    if not pairs:
        return
    with _transaction(db, write=True):
        _create_tables(db)
        db.executemany("INSERT OR REPLACE INTO v2_gate_lineage VALUES (?,?)",
                       ((lineage_hash(new), base) for new, base in pairs))


def bind_source(db, project, section, tex, label=None):
    """Point a section at its heading in a chosen main .tex, optionally by \\label."""
    plan = _section(db, project, section)
    if not plan:
        raise ValueError("请先选择论文大纲中的章节。")
    main = _project_file(project, tex, ".tex")
    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise ValueError("请提供本节的 \\label 名称。")
    binding = {"main": main.relative_to(Path(project).resolve()).as_posix(), "label": label and label.strip()}
    latex_source.section(project, plan["title"], binding)
    with _transaction(db, write=True):
        _create_tables(db)
        db.execute("INSERT OR REPLACE INTO v2_sources VALUES (?,?,?)", (section, binding["main"], binding["label"]))
    return status(db, project, section)


def archived_sections(db, live_ids):
    """Sections omitted from paper.md remain available for reading their editions."""
    live = set(live_ids)
    if not _exists(db):
        return []
    latest = db.execute("""SELECT e.section,e.body FROM v2_editions AS e JOIN
        (SELECT section,MAX(revision) AS revision FROM v2_editions GROUP BY section) AS h
        ON e.section=h.section AND e.revision=h.revision ORDER BY e.rowid""")
    archived = {section: json.loads(body)["title"] for section, body in latest if section not in live}
    if _has_references(db):
        for section, title in db.execute("SELECT section,section_title FROM v2_references ORDER BY revision DESC"):
            if section not in live:
                archived.setdefault(section, title)
    return [dict(id=section, title=title) for section, title in archived.items()]


def _source_paragraph(db, project, section, paragraph, text):
    """The .tex is the prose source. Without text, read the paragraph at the same
    position as in the author's outline; with text, it must agree with the source."""
    plan = _section(db, project, section)
    index = next((i for i, p in enumerate(plan["paragraphs"]) if p["id"] == paragraph), None) if plan else None
    try:
        located = source_section(db, project, plan) if index is not None else None
    except latex_source.SourceError:
        if text is None:
            raise
        return text, None
    if located is None:
        if text is None:
            raise ValueError("项目中没有找到 LaTeX 主文件。请先把论文写进 .tex，或在 text 中提供本段正文。")
        return text, None
    found = located.paragraphs
    if index >= len(found):
        if text is not None:
            return text, None
        after = located.where(found[-1]) if found else located.where()
        raise ValueError(f"源码中本节只有 {len(found)} 段。请先把第 {index + 1} 段写进源码（{after} 之后），再登记。")
    item = found[index]
    if text is not None and _plain(text) != _plain(item["text"]):
        raise ValueError(f"正文以 .tex 为准。请把这一段写进 {located.where(item)}，然后不带 text 重新登记。")
    return item["text"], located.where(item)


def save_paragraph_draft(db, project, section, paragraph, plan_revision, text=None, expected_version=0):
    """Register one paragraph only after its author plans have unlocked it."""
    if text is None or isinstance(text, str):
        outline.require_paragraph(db, project, section, paragraph)
        text, where = _source_paragraph(db, project, section, paragraph, text)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请提供这一段的正文。")
    text = text.strip()
    if re.search(r"\n[ \t]*\n|\\(?:par\b|(?:sub)*section\*?\s*\{|documentclass\b|(?:begin|end)\{document\})", text):
        raise ValueError("一次只登记一个自然段。请分别登记每段正文。")
    if not _positive(plan_revision) or type(expected_version) is not int or expected_version < 0:
        raise ValueError("请核对段落大纲版本和草稿版本。")
    with _transaction(db, write=True):
        plan = outline.require_paragraph(db, project, section, paragraph)
        if plan["revision"] != plan_revision:
            raise ValueError("段落思路已更新，请读取作者最新的逐句安排。")
        _, current = _contents(db, project, section)
        previous = current["drafts"].get(paragraph)
        actual = previous["version"] if previous else 0
        if (previous and previous["current"] and previous["text"] == text
                and expected_version in (actual, actual - 1)):
            return current
        if actual != expected_version:
            raise ValueError("段落草稿已改变，请刷新版本后重试。")
        if current["phase"] == "review":
            raise ValueError("请等待作者读完整节并提交本版审阅，再修改段落。")
        _create_tables(db)
        db.execute("""INSERT INTO v2_drafts VALUES (?,?,?,?,?)
            ON CONFLICT (section,paragraph) DO UPDATE SET plan_revision=excluded.plan_revision,
            version=excluded.version,text=excluded.text""",
                   (section, paragraph, plan_revision, actual + 1, text))
        return _contents(db, project, section)[1]


def _snapshot(section, drafts):
    return [dict(id=p["id"], purpose=p["purpose"], sentences=p["sentences"],
                 text=drafts[p["id"]]["text"], plan_revision=p["revision"],
                 version=drafts[p["id"]]["version"]) for p in section["paragraphs"]]


def _tex_title(value):
    escapes = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$",
               "&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_",
               "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(escapes.get(c, c) for c in value)


def _project_file(project, path, suffix):
    root = Path(project).resolve(strict=True)
    resolved = (root / path).resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file() or resolved.suffix.lower() != suffix:
        raise ValueError(f"请选择项目中的 {suffix} 文件。")
    return resolved


def _plain(text):
    return " ".join(text.split())


INCLUDE = re.compile(r"\\(?:input|include|subfile)\s*\{([^{}]+)\}")
COMMENT = re.compile(r"(?<!\\)%")


def _expanded_source(project, path, *, base=None, depth=0, seen=None):
    """Inline \\input/\\include/\\subfile files from the project, as LaTeX resolves them
    from the main file's folder. Multi-file papers keep their section text in these
    files, so both the paragraph check and the frozen source must follow them."""
    root = Path(project).resolve(strict=True)
    base = path.parent if base is None else base
    seen = set() if seen is None else seen
    seen.add(path)
    out = []
    for line in path.read_text("utf-8").splitlines(keepends=True):
        comment = COMMENT.search(line)
        code, rest = (line[:comment.start()], line[comment.start():]) if comment else (line, "")
        def inline(match):
            name = match.group(1).strip()
            for candidate in (base / name, base / (name + ".tex")):
                try:
                    resolved = candidate.resolve(strict=True)
                except OSError:
                    continue
                if (resolved.is_file() and resolved.is_relative_to(root) and resolved.suffix.lower() == ".tex"
                        and resolved not in seen and depth < 20):
                    body = _expanded_source(root, resolved, base=base, depth=depth + 1, seen=seen).decode("utf-8")
                    return body if body.endswith("\n") else body + "\n"
            return match.group(0)
        out.append(INCLUDE.sub(inline, code) + rest)
    return "".join(out).encode("utf-8")


# The desktop distribution includes a Unicode TeX engine. LaTeX's default
# Latin fonts can quietly produce blank Chinese glyphs even with exit code 0.
CJK = re.compile("[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef\U00020000-\U000323af]")
CJK_HELP = "此节含中日韩文字。请使用包含相应字体的论文模板生成 PDF，并一并传入匹配的 tex、pdf 和节选页码。"


def _render_cjk(path):
    font = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/tectonic/tectonic")
    tectonic = shutil.which("tectonic") or (str(bundled) if bundled.is_file() else None)
    xelatex = shutil.which("xelatex")
    if sys.platform != "darwin" or not font.is_file() or not (tectonic or xelatex):
        raise ValueError(CJK_HELP)
    if tectonic:
        args = [tectonic, "--untrusted", "--keep-logs"]
        if os.environ.get("PAPERROOM_TEX_OFFLINE") == "1":
            args.append("--only-cached")
    else:
        args = [xelatex, "-no-shell-escape", "-halt-on-error", "-interaction=nonstopmode"]
    paperroom.run_program([*args, path.name], cwd=path.parent)
    log = path.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
    if "Missing character:" in log:
        raise ValueError(CJK_HELP)
    return paperroom.render_document(path, path.with_suffix(".pdf"), "all")


def _asset_preview(project, title, paragraphs, tex, pdf, pages):
    if (pdf is not None or pages != "all") and tex is None:
        raise ValueError("请提供与 PDF 或节选页码对应的 LaTeX 源文件。")
    if tex is not None:
        source_path = _project_file(project, tex, ".tex")
        pdf_path = _project_file(project, pdf, ".pdf") if pdf is not None else None
        source = _expanded_source(project, source_path)
        # Strip TeX comments before matching so a commented-out draft cannot
        # satisfy the check for the actual text being reviewed.
        visible = _plain(re.sub(r"(?<!\\)%[^\n]*", "", source.decode("utf-8")))
        offset = 0
        for p in paragraphs:
            needle = _plain(re.sub(r"(?<!\\)%[^\n]*", "", p["text"]))
            position = visible.find(needle, offset)
            if not needle or position < 0:
                raise ValueError("节选源文件须依序包含本节已登记的全部段落，请选择含正文的源文件。")
            offset = position + len(needle)
        pdf_hash = hashlib.sha256(pdf_path.read_bytes()).digest() if pdf_path else None
        captured, images = paperroom.render_document(source_path, pdf_path, pages)
        if source != _expanded_source(project, source_path) or (pdf_path and pdf_hash != hashlib.sha256(pdf_path.read_bytes()).digest()):
            raise ValueError("排版期间稿件已修改，请重新发布。")
        excerpt.check(captured, paragraphs)
        return source, captured, images
    text = "\n\n".join(p["text"] for p in paragraphs)
    cjk = bool(CJK.search(title + text))
    fonts = (r'\font\paperroomCJK="Songti SC" at 11pt' "\n" r'\font\paperroomHead="Songti SC" at 16pt'
             "\n" r'\XeTeXlinebreaklocale "zh" \XeTeXlinebreakskip=0pt plus 1pt' "\n") if cjk else ""
    heading = (r"\paperroomHead " if cjk else "") + _tex_title(title)
    if cjk:
        text = r"\paperroomCJK " + text
    source = (r"\documentclass[11pt]{article}" "\n"
              r"\usepackage[paperwidth=176mm,paperheight=244mm,margin=18mm]{geometry}" "\n"
              r"\usepackage[T1]{fontenc}" "\n"
              r"\usepackage[sc]{mathpazo}" "\n"
              + fonts + r"\begin{document}" "\n"
              r"\section*{" + heading + "}\n" + text + "\n" + r"\end{document}" + "\n")
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / "section.tex"
        path.write_text(source, encoding="utf-8")
        captured, images = _render_cjk(path) if cjk else paperroom.render_document(path, None, "all")
        return source.encode(), captured, images


def _digest(content):
    return hashlib.sha256(content).hexdigest()


def _publish_request(project, tex, pdf, pages, minimum):
    """Recognize a retried request while its original author review is still pending."""
    result = dict(minimum=minimum, pages=pages)
    for name, path in (("tex", tex), ("pdf", pdf)):
        if path is not None:
            resolved = _project_file(project, path, "." + name)
            content = _expanded_source(project, resolved) if name == "tex" else resolved.read_bytes()
            result[name] = _digest(content)
    return result


def _reconcile(db, project, section, located):
    """Accept small edits made in the .tex after registration; a paragraph that is
    new or more than half rewritten must be registered again against its intents."""
    with _transaction(db, write=True):
        plan = outline.require_section(db, project, section)
        _, current = _contents(db, project, section)
        found = located.paragraphs
        if len(found) != len(plan["paragraphs"]):
            raise ValueError(f"源码中本节有 {len(found)} 段，作者大纲有 {len(plan['paragraphs'])} 段（{located.where()}）。"
                             "请让两者按顺序一一对应后再发布。")
        for index, (p, item) in enumerate(zip(plan["paragraphs"], found), 1):
            draft = current["drafts"].get(p["id"])
            state = _paragraph_state(draft, item)
            if state == "unregistered":
                raise ValueError(f"第 {index} 段（{located.where(item)}）尚未登记。请核对作者句意后调用 save_paragraph_draft。")
            if state == "rewritten":
                raise ValueError(f"第 {index} 段（{located.where(item)}）登记后改写超过一半。"
                                 "请核对作者的逐句大纲，再用 save_paragraph_draft 重新登记这一段。")
            if state == "edited":
                db.execute("UPDATE v2_drafts SET text=?, version=version+1 WHERE section=? AND paragraph=?",
                           (item["text"], section, p["id"]))


RESPONSE_STATUS = {"changed": "已修改", "kept": "保留原文", "discuss": "有不同意见"}


def _clean_responses(previous, responses):
    """The AI answers each note of the last reviewed version exactly once."""
    notes = previous["notes"] if previous and previous.get("reviewed") else []
    if not notes:
        if responses:
            raise ValueError("上一版没有审阅意见，无需逐条回应。")
        return []
    if not isinstance(responses, list) or not responses:
        raise ValueError(f"请对上一版的 {len(notes)} 条审阅意见逐条回应（responses）："
                         "说明已修改、保留原文或有不同意见，并给出理由。")
    clean, seen = [], set()
    for item in responses:
        if not isinstance(item, dict) or type(item.get("note")) is not int or not 1 <= item["note"] <= len(notes):
            raise ValueError(f"responses 中的 note 应为 1 到 {len(notes)} 的意见序号。")
        if item["note"] in seen:
            raise ValueError(f"第 {item['note']} 条意见回应了不止一次。")
        if item.get("status") not in RESPONSE_STATUS:
            raise ValueError("回应状态应为 changed、kept 或 discuss。")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError("请为每条回应写下具体说明（不超过 2000 字）。")
        seen.add(item["note"])
        clean.append(dict(note=item["note"], status=item["status"], text=text.strip()))
    missing = [str(n) for n in range(1, len(notes) + 1) if n not in seen]
    if missing:
        raise ValueError(f"还没有回应第 {'、'.join(missing)} 条意见。")
    return sorted(clean, key=lambda r: r["note"])


def publish_section(db, project, section, *, tex=None, pdf=None, pages="all", minimum=None,
                    expected_revision=None, responses=None):
    """Render outside the write lock, then publish the exact snapshot checked before rendering.
    Without tex or pdf, the section is read from and rendered with the paper's own .tex."""
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise ValueError("章节版本应为非负整数。")
    with _transaction(db):
        earlier = _contents(db, project, section)[1]["revisions"]
    # A retry while the new version awaits review is measured against the same basis.
    pending = bool(earlier and not earlier[-1].get("reviewed"))
    settled = earlier[:-1] if pending else earlier
    # Later rounds check fewer, more focused points; the first needs a full read.
    minimum = (1 if settled else 3) if minimum is None else minimum
    if not _positive(minimum):
        raise ValueError("最低审阅意见数应为正整数。")
    try:
        answered = _clean_responses(settled[-1] if settled else None, responses)
    except ValueError:
        if not pending:
            raise
        answered = None
    located = None
    if tex is None and pdf is None:
        with _transaction(db):
            plan = outline.require_section(db, project, section)
            located = source_section(db, project, plan)
    if located is not None:
        request = dict(minimum=minimum, pages="section", source=_digest(located.source().encode("utf-8")))
    else:
        request = _publish_request(project, tex, pdf, pages, minimum)
    if answered:
        request["responses"] = _digest(json.dumps(answered, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    with _transaction(db):
        current = _contents(db, project, section)[1]
        latest = current["revisions"][-1] if current["revisions"] else None
        previous_revision = latest["revision"] if latest else 0
        if current["phase"] == "review":
            if (not current["review_outline_changed"] and latest.get("request") == request
                    and expected_revision in (None, previous_revision, previous_revision - 1)):
                return current
            raise ValueError("当前版本仍在等待作者提交整节审阅。")
        if expected_revision is not None and expected_revision != previous_revision:
            raise ValueError("章节版本已改变，请读取最新版本。")
        if current["phase"] not in ("ready", "reviewed"):
            raise ValueError("本节每个段落都需要作者逐句大纲和对应的正文草稿。")
    if located is not None:
        _reconcile(db, project, section, located)
    with _transaction(db):
        plan = outline.require_section(db, project, section)
        drafted = paragraphs = _snapshot(plan, _contents(db, project, section)[1]["drafts"])
    if located is not None:
        # The prose comes from the very source being compiled, and the pages come
        # from markers at the section's start and end (render_section refuses when
        # either is missing). A PDF text match would only misfire on math, \\ref and
        # macros, so it is kept for externally supplied PDFs only.
        captured, images, _ = paperroom.render_section(located)
        # What the author is shown is what was typeset: under a conditional such as
        # \\ifdraft ... \\else ... \\fi only the branch that printed is recorded.
        if len(located.shown) != len(paragraphs):
            raise ValueError("排版期间稿件已修改，请重新发布。")
        paragraphs = [{**p, "text": text} for p, text in zip(paragraphs, located.shown)]
        source = located.source().encode("utf-8")
        fresh_source = source_section(db, project, plan)
        if fresh_source is None or fresh_source.source() != located.source():
            raise ValueError("排版期间稿件已修改，请重新发布。")
    else:
        source, captured, images = _asset_preview(project, plan["title"], paragraphs, tex, pdf, pages)
    if not images:
        raise ValueError("未生成审阅图片。")
    if located is None and {k: v for k, v in request.items() if k != "responses"} != _publish_request(
            project, tex, pdf, pages, minimum):
        raise ValueError("排版期间稿件已修改，请重新发布。")
    source_hash, image_hashes = _digest(source), [_digest(i) for i in images]
    with _transaction(db, write=True):
        fresh_plan = outline.require_section(db, project, section)
        fresh = _contents(db, project, section)[1]
        latest = fresh["revisions"][-1] if fresh["revisions"] else None
        if (fresh["phase"] == "review" and not fresh["review_outline_changed"]
                and latest["revision"] == previous_revision + 1 and latest.get("request") == request
                and latest["paragraphs"] == paragraphs and latest["source_sha256"] == source_hash
                and latest["image_sha256"] == image_hashes):
            return fresh
        if (fresh["phase"] not in ("ready", "reviewed")
                or (latest["revision"] if latest else 0) != previous_revision
                or plan["title"] != fresh_plan["title"] or plan["purpose"] != fresh_plan["purpose"]
                or drafted != _snapshot(fresh_plan, fresh["drafts"])):
            raise ValueError("排版期间作者大纲、段落或章节版本已改变，请重新发布。")
        # Unchanged text is a no-op only when there is nothing to answer. Answers that
        # keep the text (kept/discuss) still form a new version for the author to read.
        if (fresh["phase"] == "reviewed" and latest["source_sha256"] == source_hash
                and latest["image_sha256"] == image_hashes and not answered):
            return fresh
        revision = previous_revision + 1
        previous_order = [p["id"] for p in latest["paragraphs"]] if latest else []
        previous = {p["id"]: p for p in latest["paragraphs"]} if latest else {}
        changed = [p["id"] for index, p in enumerate(paragraphs) if p["id"] not in previous
                   or p["text"] != previous[p["id"]]["text"]
                   or p["plan_revision"] != previous[p["id"]]["plan_revision"]
                   or previous_order.index(p["id"]) != index]
        present = {p["id"] for p in paragraphs}
        removed = [p for p in previous if p not in present]
        edition = dict(revision=revision, pages=len(images), created=journal.utc_now(), reviewed=None,
                       minimum=minimum, request=request, title=plan["title"], purpose=plan["purpose"], paragraphs=paragraphs,
                       changed=changed, removed=removed, notes=[], responses=answered or [], pdf_sha256=_digest(captured), source_sha256=source_hash, image_sha256=image_hashes)
        _create_tables(db)
        db.execute("INSERT INTO v2_editions VALUES (?,?,?)", (section, revision, json.dumps(edition, ensure_ascii=False)))
        db.execute("INSERT INTO v2_pages VALUES (?,?,?,?)", (section, revision, -1, captured))
        db.executemany("INSERT INTO v2_pages VALUES (?,?,?,?)",
                       ((section, revision, page, data) for page, data in enumerate([source, *images])))
        evidence = {key: edition[key] for key in ("title", "purpose", "paragraphs", "minimum",
                                                  "source_sha256", "pdf_sha256", "image_sha256")}
        if edition["responses"]:
            evidence["responses"] = edition["responses"]
        journal.append(db, "section_published", evidence, section=section, revision=revision,
                       recorded_at=edition["created"])
        return _contents(db, project, section)[1]


def _validate_notes(edition, notes, minimum=None):
    minimum = edition["minimum"] if minimum is None else minimum
    if not isinstance(notes, list) or len(notes) < minimum:
        raise ValueError(f"这版至少需要 {minimum} 条审阅意见。")
    paragraphs = {p["id"]: p for p in edition["paragraphs"]}
    seen, result = set(), []
    for original in notes:
        if not isinstance(original, dict) or original.get("kind") not in ("keep", "change"):
            raise ValueError("请为每条批注选择保留或修改。")
        text = original.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("请写出每条批注的具体想法。")
        key = _plain(text).casefold()
        if key in seen:
            raise ValueError("请分别写出各条批注的具体判断。")
        seen.add(key)
        note = dict(kind=original["kind"], text=text.strip())
        paragraph, quote, page = original.get("paragraph"), original.get("quote"), original.get("page")
        if paragraph:
            if not isinstance(paragraph, str) or paragraph not in paragraphs:
                raise ValueError("批注指向的段落不属于当前版本。")
            note["paragraph"] = paragraph
        if quote:
            if not isinstance(quote, str) or not _plain(quote) or not paragraph or _plain(quote) not in _plain(paragraphs[paragraph]["text"]):
                raise ValueError("引用须来自当前版本选中的段落。")
            note["quote"] = quote.strip()
        if page is not None:
            if not _positive(page) or page > edition["pages"]:
                raise ValueError("批注页码不属于当前版本。")
            note["page"] = page
        pin, location = original.get("pin"), original.get("location")
        if pin is not None:
            if not page or not isinstance(pin, dict) or any(
                    type(pin.get(k)) not in (float, int) or not 0 <= pin[k] <= 1
                    for k in ("x", "y")):
                raise ValueError("请在页图内选择批注位置。")
            note["pin"] = {k: pin[k] for k in ("x", "y")}
        if location:
            if not page or not isinstance(location, str) or not location.strip():
                raise ValueError("请注明对应页码及位置。")
            note["location"] = location.strip()
        if not paragraph and not (page and (pin is not None or location)):
            raise ValueError("请把意见关联到具体段落或页图中的位置。")
        result.append(note)
    return result


def submit_review(db, project, section, revision, notes, approve=False):
    """Only the browser author endpoint should call this transition. From the second
    version on, the author may pass a version with fewer notes than the minimum."""
    if type(approve) is not bool:
        raise ValueError("请重新提交审阅。")
    with _transaction(db, write=True):
        _, current = _contents(db, project, section)
        if not _positive(revision) or revision != current["current_revision"]:
            raise ValueError("待审稿件已改变，请打开当前版本。")
        edition = current["revisions"][-1]
        if approve and len(current["revisions"]) < 2:
            raise ValueError("第一版需要逐条写下审阅意见。")
        clean = _validate_notes(edition, notes, 0 if approve else None)
        if edition["reviewed"]:
            if clean == edition["notes"] and bool(edition.get("approved")) == approve:
                return current
            raise ValueError("这版审阅已经提交。")
        edition.update(notes=clean, reviewed=journal.utc_now())
        if approve:
            edition["approved"] = True
        db.execute("UPDATE v2_editions SET body=? WHERE section=? AND revision=?",
                   (json.dumps(edition, ensure_ascii=False), section, revision))
        evidence = dict(notes=clean, source_sha256=edition["source_sha256"],
                        image_sha256=edition["image_sha256"])
        if approve:
            evidence["approved"] = True
        if edition.get("pdf_sha256"):
            evidence["pdf_sha256"] = edition["pdf_sha256"]
        journal.append(db, "section_reviewed", evidence, section=section, revision=revision,
                       recorded_at=edition["reviewed"])
        return _contents(db, project, section)[1]


def page(db, section, revision, number):
    """Return the PNG for the requested review page, including historical editions."""
    if not _positive(revision) or not _positive(number) or not _exists(db):
        return None
    row = db.execute("SELECT content FROM v2_pages WHERE section=? AND revision=? AND page=?",
                     (section, revision, number)).fetchone()
    return row[0] if row else None

def document_asset(db, section, kind, revision, page=None):
    """None requests the PDF. Editions from before PDF persistence only have PNGs."""
    if not _positive(revision) or (page is not None and not _positive(page)):
        return None
    if kind == "ref" and _has_references(db):
        table = "v2_reference_assets"
    elif kind == "rev" and _exists(db):
        table = "v2_pages"
    else:
        return None
    row = db.execute(f"SELECT content FROM {table} WHERE section=? AND revision=? AND page=?",
                     (section, revision, page if page is not None else -1)).fetchone()
    return row[0] if row else None


def import_reference(db, project, section, *, title=None, tex=None, pdf=None, pages="all", upload=None):
    """Freeze an existing typeset section. References never grant draft/review permissions."""
    if not _section(db, project, section):
        raise ValueError("请先选择论文大纲中的章节。")
    if title is not None and (not isinstance(title, str) or len(title) > 180):
        raise ValueError("参考稿名称最多 180 个字符。")
    if upload is not None and (pdf or tex):
        raise ValueError("上传 PDF 和项目文件请分别导入。")
    located = None
    if not (tex or pdf or upload is not None):
        located = source_section(db, project, _section(db, project, section))
        if located is None:
            raise ValueError("请选择原稿 PDF 或可独立编译的项目 TeX 文件。")
        if not located.paragraphs:
            raise ValueError("源码中这一节还没有正文，没有可保存的原稿。")
    tex_path = _project_file(project, tex, ".tex") if tex else None
    pdf_path = _project_file(project, pdf, ".pdf") if pdf else None
    original = upload
    if pdf_path is not None:
        if pdf_path.stat().st_size > paperroom.MAX_DOCUMENT_BYTES:
            raise ValueError("PDF 须不超过 32 MiB。")
        original = pdf_path.read_bytes()
    if located is not None:
        captured, images, found = paperroom.render_section(located)
        main = located.main.relative_to(located.project).as_posix()
        title = (title or "").strip() or f"{main} 第 {found} 页"
    if not (title or "").strip() and (pdf or tex):
        # A frozen chapter usually comes from the whole paper; name its pages too.
        title = (pdf_path or tex_path).name + ("" if pages == "all" else f" 第 {pages} 页")
    title = (title or "").strip() or "原稿"
    if located is not None:
        pass
    elif original is not None:
        if not isinstance(original, bytes) or len(original) > paperroom.MAX_DOCUMENT_BYTES:
            raise ValueError("请提供一个不超过 32 MiB 的 PDF。")
        if b"%PDF-" not in original[:1024]:
            raise ValueError("文件缺少 PDF 标识。")
        # The original may be an actively compiled manuscript. Freeze it before
        # selecting pages so that the downloadable excerpt and PNGs always match.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reference.pdf"
            path.write_bytes(original)
            captured, images = paperroom.render_document(None, path, pages)
    else:
        captured, images = paperroom.render_document(tex_path, None, pages)
    fingerprint = hashlib.sha256()
    for image in images:
        fingerprint.update(hashlib.sha256(image).digest())
    if original is not None:
        fingerprint.update(hashlib.sha256(original).digest())
    with _transaction(db, write=True):
        plan = _section(db, project, section)
        if not plan:
            raise ValueError("该章节在排版期间已归档。")
        _create_tables(db)
        if located is not None:
            db.execute("INSERT OR IGNORE INTO v2_baselines VALUES (?,?)",
                       (section, json.dumps([p["text"] for p in located.paragraphs], ensure_ascii=False)))
        existing = db.execute("SELECT revision FROM v2_references WHERE section=? AND title=? AND fingerprint=?",
                              (section, title, fingerprint.hexdigest())).fetchone()
        if existing:
            revision = existing[0]
        else:
            revision = db.execute("SELECT COALESCE(MAX(revision),0)+1 FROM v2_references WHERE section=?",
                                  (section,)).fetchone()[0]
            db.execute("INSERT INTO v2_references VALUES (?,?,?,?,?,?,?)",
                       (section, revision, plan["title"], title, datetime.now(timezone.utc).isoformat(),
                        len(images), fingerprint.hexdigest()))
            db.execute("INSERT INTO v2_reference_assets VALUES (?,?,?,?)", (section, revision, -1, captured))
            db.executemany("INSERT INTO v2_reference_assets VALUES (?,?,?,?)",
                           ((section, revision, num, image) for num, image in enumerate(images, 1)))
        return {**_contents(db, project, section)[1], "reference_id": f"ref-{revision}"}
