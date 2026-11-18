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


def status(db, project, section):
    """Include every published edition, even if a later outline invalidates it."""
    with _transaction(db):
        return _contents(db, project, section)[1]


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


def save_paragraph_draft(db, project, section, paragraph, plan_revision, text, expected_version=0):
    """Save one paragraph only after its author plans have unlocked it."""
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
        source = source_path.read_bytes()
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
        if source != source_path.read_bytes() or (pdf_path and pdf_hash != hashlib.sha256(pdf_path.read_bytes()).digest()):
            raise ValueError("排版期间稿件已修改，请重新发布。")
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
            result[name] = _digest(resolved.read_bytes())
    return result


def publish_section(db, project, section, *, tex=None, pdf=None, pages="all", minimum=3,
                    expected_revision=None):
    """Render outside the write lock, then publish the exact snapshot checked before rendering."""
    if not _positive(minimum):
        raise ValueError("最低审阅意见数应为正整数。")
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
        raise ValueError("章节版本应为非负整数。")
    request = _publish_request(project, tex, pdf, pages, minimum)
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
        plan = outline.require_section(db, project, section)
        paragraphs = _snapshot(plan, current["drafts"])
    source, captured, images = _asset_preview(project, plan["title"], paragraphs, tex, pdf, pages)
    if not images:
        raise ValueError("未生成审阅图片。")
    if request != _publish_request(project, tex, pdf, pages, minimum):
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
                or paragraphs != _snapshot(fresh_plan, fresh["drafts"])):
            raise ValueError("排版期间作者大纲、段落或章节版本已改变，请重新发布。")
        if (fresh["phase"] == "reviewed" and latest["source_sha256"] == source_hash
                and latest["image_sha256"] == image_hashes):
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
        edition = dict(revision=revision, pages=len(images), created=datetime.now(timezone.utc).isoformat(), reviewed=None,
                       minimum=minimum, request=request, title=plan["title"], purpose=plan["purpose"], paragraphs=paragraphs,
                       changed=changed, removed=removed, notes=[], pdf_sha256=_digest(captured), source_sha256=source_hash, image_sha256=image_hashes)
        _create_tables(db)
        db.execute("INSERT INTO v2_editions VALUES (?,?,?)", (section, revision, json.dumps(edition, ensure_ascii=False)))
        db.execute("INSERT INTO v2_pages VALUES (?,?,?,?)", (section, revision, -1, captured))
        db.executemany("INSERT INTO v2_pages VALUES (?,?,?,?)",
                       ((section, revision, page, data) for page, data in enumerate([source, *images])))
        return _contents(db, project, section)[1]


def _validate_notes(edition, notes):
    if not isinstance(notes, list) or len(notes) < edition["minimum"]:
        raise ValueError(f"这版至少需要 {edition['minimum']} 条审阅意见。")
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


def submit_review(db, project, section, revision, notes):
    """Only the browser author endpoint should call this transition."""
    with _transaction(db, write=True):
        _, current = _contents(db, project, section)
        if not _positive(revision) or revision != current["current_revision"]:
            raise ValueError("待审稿件已改变，请打开当前版本。")
        edition = current["revisions"][-1]
        clean = _validate_notes(edition, notes)
        if edition["reviewed"]:
            if clean == edition["notes"]:
                return current
            raise ValueError("这版审阅已经提交。")
        edition.update(notes=clean, reviewed=paperroom.now())
        db.execute("UPDATE v2_editions SET body=? WHERE section=? AND revision=?",
                   (json.dumps(edition, ensure_ascii=False), section, revision))
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
    if not (tex or pdf or upload is not None):
        raise ValueError("请选择原稿 PDF 或可独立编译的项目 TeX 文件。")
    tex_path = _project_file(project, tex, ".tex") if tex else None
    pdf_path = _project_file(project, pdf, ".pdf") if pdf else None
    original = upload
    if pdf_path is not None:
        if pdf_path.stat().st_size > paperroom.MAX_DOCUMENT_BYTES:
            raise ValueError("PDF 须不超过 32 MiB。")
        original = pdf_path.read_bytes()
    title = (title or "").strip() or ((pdf_path or tex_path).name if pdf or tex else "原稿")
    if original is not None:
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
