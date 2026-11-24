"""Whole-paper versions: V0 is frozen before the first rewrite, then V1, V2… are saved
only when the author asks in chat. Each version keeps the full typeset PDF, its page
images, the page every outlined section and paragraph starts on, and the author's
review notes with the AI's answers in the next version."""
import hashlib
from pathlib import Path
import json
from datetime import datetime, timezone

import journal
import latex_source as L
import outline
import paperroom
import section_review

LABEL_LIMIT = 80


def create_tables(db):
    db.execute("CREATE TABLE IF NOT EXISTS v2_versions (number INTEGER PRIMARY KEY, body TEXT NOT NULL)")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_version_pages (
        number INTEGER NOT NULL, page INTEGER NOT NULL, content BLOB NOT NULL, PRIMARY KEY(number, page))""")


def _has_table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _now():
    return datetime.now(timezone.utc).isoformat()


def _decode(payload, predecessor):
    body = json.loads(payload)
    # Before cleanup existed every Vn was also its permanent database key.
    body.setdefault("display_number", body["number"])
    if body.get("kind") == "migrated" and predecessor == 0:
        predecessor = None  # a whole-paper V0 can be frozen after section layouts migrated
    body.setdefault("previous_number", predecessor)
    return body


def _bodies(db):
    if db is None or not _has_table(db, "v2_versions"):
        return []
    bodies = []
    for (payload,) in db.execute("SELECT body FROM v2_versions ORDER BY number"):
        bodies.append(_decode(payload, bodies[-1]["number"] if bodies else None))
    return bodies


def latest(db):
    return next((b for b in reversed(_bodies(db)) if not b.get("cleaned_at")), None)


def _whole_paper(db):
    """The latest version compiled from the whole paper (not migrated from a section)."""
    return next((b for b in reversed(_bodies(db))
                 if b.get("kind") in ("original", "version") and not b.get("cleaned_at")), None)


def get(db, number):
    if not _has_table(db, "v2_versions"):
        return None
    row = db.execute("""SELECT body, (SELECT MAX(number) FROM v2_versions WHERE number < ?)
                        FROM v2_versions WHERE number=?""", (number, number)).fetchone()
    return _decode(*row) if row else None


def summary(body):
    """What the page and the AI see of a version; pages are fetched separately."""
    keys = ("number", "kind", "label", "created", "pages", "map", "changed", "notes", "responses",
            "reviewed", "approved", "has_pdf", "compared_with", "built", "display_number",
            "previous_number", "cleaned_at", "last_display_number")
    return {k: body.get(k) for k in keys}


def version_lists(db):
    active, cleaned = [], []
    for body in _bodies(db):
        target = cleaned if body.get("cleaned_at") else active
        target.append(summary(body))
    return {"versions": active, "archived_versions": cleaned}


def listing(db):
    return version_lists(db)["versions"]


def archived(db):
    return version_lists(db)["archived_versions"]


def ensure_migrated(database):
    """Bring section editions from before 0.6.14 into the version list (once, writable),
    and give references migrated by 0.6.14 back their own titles."""
    import sqlite3
    from contextlib import closing
    if not database.is_file():
        return
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        if not (_has_table(db, "v2_editions") or _has_table(db, "v2_references")):
            return
        done = _has_table(db, "v2_versions") and db.execute("SELECT 1 FROM v2_versions LIMIT 1").fetchone()
        if done and not _misnamed(db):
            return
    with closing(paperroom.connect(database)) as db:
        with section_review._transaction(db, write=True):
            create_tables(db)
            migrate(db)
            _rename_migrated(db)


def _misnamed(db):
    return bool(_has_table(db, "v2_references") and _migrated_titles(db))


def _migrated_titles(db):
    """{version number: label} for references 0.6.14 migrated as "<section> · 原稿"."""
    if not _has_table(db, "v2_references"):
        return {}
    refs = {(section, created): f"{section_title} · {title}" for section, section_title, title, created in
            db.execute("SELECT section, section_title, title, created FROM v2_references")}
    fixes = {}
    for body in _bodies(db):
        if body.get("kind") != "migrated" or not str(body.get("label", "")).endswith(" · 原稿"):
            continue
        section = next(iter(body.get("map") or {}), None)
        label = refs.get((section, body.get("created")))
        if label and label != body["label"]:
            fixes[body["number"]] = label
    return fixes


def _rename_migrated(db):
    for number, label in _migrated_titles(db).items():
        body = get(db, number)
        body["label"] = label
        db.execute("UPDATE v2_versions SET body=? WHERE number=?", (json.dumps(body, ensure_ascii=False), number))


# ------------------------------------------------------------------ compiling
def _located_sections(db, project):
    """(main, lines, [(outline section, start, end)]) for the outlined sections found in the paper."""
    state = outline.state(db, project)
    main, lines, found = None, None, []
    for plan in state["sections"]:
        try:
            located = section_review.source_section(db, project, plan)
        except (ValueError, OSError):
            located = None
        if located is None:
            continue
        if main is None:
            main, lines = located.main, located.lines
        elif located.main != main:
            continue
        found.append((plan, located.start, located.end))
    return main, lines, found


def _marked_paper(lines, found):
    """The expanded paper with page markers in every outlined section: each section's
    heading and the end of each paragraph run, namespaced by section position."""
    out = [raw for raw, _, _ in lines]
    inserts = []
    for key, (_, start, end) in enumerate(found):
        heading = L.strip_comments(out[start])
        match = L.HEADING.search(heading)
        if match:
            close = match.end() + len(L._heading_title(heading, match.end())) + 1
        else:  # the abstract environment
            close = L.ABSTRACT_BEGIN.search(heading).end()
        inserts.append((start, close, L.mark(f"paperroom-s{key}-start")))
        for number, item in enumerate(L.paragraphs(lines, start, end)):
            for run, (index, col) in enumerate(item["runs"]):
                inserts.append((index, col, L.mark(f"paperroom-s{key}-par-{number}-{run}")))
    for index, col, text in sorted(inserts, key=lambda i: (i[0], i[1]), reverse=True):
        out[index] = out[index][:col] + text + out[index][col:]
    return "\n".join(out) + "\n"


def _page_map(lines, found, located):
    """{section id: {title, page, paragraphs: {paragraph id: start page}}}. A paragraph starts
    on the page where the one before it ended; the first starts on the heading's page."""
    result, texts = {}, {}
    for key, (plan, start, end) in enumerate(found):
        heading = located.get(f"paperroom-s{key}-start")
        if not heading:
            continue  # excluded from this build, e.g. by \includeonly
        items = L.paragraphs(lines, start, end)
        ends = []
        for number, item in enumerate(items):
            pages = [located.get(f"paperroom-s{key}-par-{number}-{run}") for run in range(len(item["runs"]))]
            pages = [p for p in pages if p]
            ends.append(max(pages) if pages else None)
        ids = [p["id"] for p in plan["paragraphs"]]
        starts, previous = {}, heading
        for number, item in enumerate(items):
            if number < len(ids):
                starts[ids[number]] = previous
            previous = ends[number] or previous
        result[plan["id"]] = {"title": plan["title"], "page": heading, "paragraphs": starts}
        # What the compile printed of each paragraph (conditional branches decide), "" if nothing.
        prefix = f"paperroom-s{key}-par-"
        local = {L.PAR_MARK + name[len(prefix):]: page for name, page in located.items() if name.startswith(prefix)}
        texts[plan["id"]] = [L.printed(item, local, number) or "" for number, item in enumerate(items)]
    return result, texts


def _compile(db, project, pdf=None):
    """Compile the paper with page markers when this computer can. Otherwise use the PDF
    the author's agent already compiled, locating pages by searching its text."""
    main, lines, found = _located_sections(db, project)
    if main is None:
        raise ValueError("没有找到论文的主 .tex 文件或大纲中的章节标题，无法编译整篇版本。")
    if pdf is not None or not paperroom.tex_available():
        return _from_author_pdf(project, main, lines, found, pdf)
    source = _marked_paper(lines, found)
    with paperroom.marked_build(main, source) as (pdf, aux):
        located = L.marks(aux)
        captured, images = paperroom.render_document(None, pdf, "all")
    page_map, texts = _page_map(lines, found, located)
    rel = main.relative_to(L._root(project)).as_posix()
    return dict(pdf=captured, images=images, map=page_map, texts=texts, main=rel, built="paperroom",
                source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
                sources={plan["id"]: (start, end) for plan, start, end in found}, lines=lines, found=found)


def _search_key(text):
    """Text as a PDF's text layer gives it back: no case, spaces, hyphens or LaTeX markup."""
    import re
    import excerpt
    text = re.sub(r"\\[a-zA-Z]+\*?|[{}$~^_\\]", " ", text)
    return excerpt.compact(text).casefold().replace("-", "").replace("\u00ad", "")


def _from_author_pdf(project, main, lines, found, pdf):
    """The agent's own compiled PDF, used as is. Sections and paragraphs are found by
    searching the text layer for their headings and first words, in reading order."""
    import pdf_text
    path = (L._root(project) / pdf).resolve() if pdf else main.with_suffix(".pdf")
    if pdf and not path.is_relative_to(L._root(project)):
        raise ValueError("请使用论文目录内的 PDF。")
    if not path.is_file():
        raise ValueError(f"这台电脑没有 LaTeX 编译器，也没有找到已编译的 {path.name}。"
                         "请先让 AI 编译论文，再保存版本；或安装编译器（brew install tectonic）。")
    sources = {Path(file) for _, file, _ in lines if file}
    newest = max((f.stat().st_mtime for f in sources if f.is_file()), default=0)
    if path.stat().st_mtime < newest:
        raise ValueError(f"{path.name} 比论文源码旧。请先让 AI 重新编译，再保存版本。")
    blob = path.read_bytes()
    captured, images = paperroom.render_document(None, path, "all")
    pages = [_search_key(text) for text in pdf_text.read_pages(blob)]

    def find(key, start):
        if not key:
            return None
        for length in (len(key), 40, 20, 12):
            probe = key[:length]
            if len(probe) < 6:
                continue
            hit = next((n for n in range(start, len(pages)) if probe in pages[n]), None)
            if hit is not None:
                return hit
        return None

    page_map, texts, cursor = {}, {}, 0
    for plan, start, end in found:
        heading = find(_search_key(plan["title"]), cursor)
        if heading is None:
            continue  # not in this PDF, e.g. left out by \\includeonly
        items = L.paragraphs(lines, start, end)
        ids = [p["id"] for p in plan["paragraphs"]]
        starts, here = {}, heading
        for number, item in enumerate(items):
            hit = find(_search_key(item["text"]), here)
            here = hit if hit is not None else here
            if number < len(ids):
                starts[ids[number]] = here + 1
        page_map[plan["id"]] = {"title": plan["title"], "page": heading + 1, "paragraphs": starts}
        texts[plan["id"]] = [item["text"] for item in items]
        cursor = heading
    digest = hashlib.sha256(blob + "".join(raw for raw, _, _ in lines).encode("utf-8")).hexdigest()
    return dict(pdf=captured, images=images, map=page_map, texts=texts, built="author_pdf",
                main=main.relative_to(L._root(project)).as_posix(), source_sha256=digest,
                sources={plan["id"]: (start, end) for plan, start, end in found}, lines=lines, found=found)


def _changes(previous, texts):
    """{section id: [indexes of paragraphs that differ]} against the previous version."""
    before = (previous or {}).get("texts") or {}
    changed = {}
    for sid, items in texts.items():
        old = before.get(sid)
        if old is None:
            changed[sid] = list(range(len(items)))
            continue
        diff = [n for n, text in enumerate(items) if n >= len(old) or old[n] != text]
        if diff or len(old) != len(items):
            changed[sid] = diff
    return changed


def _store(db, number, kind, label, compiled, previous, responses=(), *, display_number=None, previous_number=None):
    images = compiled["images"]
    body = dict(number=number, display_number=number if display_number is None else display_number,
                previous_number=previous_number, kind=kind, label=label, created=_now(), pages=len(images),
                main=compiled["main"], map=compiled["map"], texts=compiled["texts"],
                changed=_changes(previous, compiled["texts"]) if previous else {},
                compared_with=previous["number"] if previous else None,
                notes=[], responses=list(responses), reviewed=None, approved=False,
                has_pdf=compiled["pdf"] is not None, source_sha256=compiled["source_sha256"],
                built=compiled.get("built", "paperroom"),
                pdf_sha256=hashlib.sha256(compiled["pdf"]).hexdigest() if compiled["pdf"] else None)
    db.execute("INSERT INTO v2_versions VALUES (?,?)", (number, json.dumps(body, ensure_ascii=False)))
    if compiled["pdf"] is not None:
        db.execute("INSERT INTO v2_version_pages VALUES (?,?,?)", (number, -1, compiled["pdf"]))
    db.executemany("INSERT INTO v2_version_pages VALUES (?,?,?)",
                   ((number, page, image) for page, image in enumerate(images, 1)))
    return body


def _clean_label(label):
    if label is None:
        return ""
    if not isinstance(label, str) or len(label.strip()) > LABEL_LIMIT or "\n" in label:
        raise ValueError("版本标签请用一行，最多 80 个字符。")
    return label.strip()


# ------------------------------------------------------------------ public actions
def _original_already_started(db):
    # Even a cleaned revision proves the source is past the first rewrite.
    return any(body["kind"] in ("original", "version") for body in _bodies(db))


def _db_file(db):
    try:
        for _, name, filename in db.execute("PRAGMA database_list"):
            if name == "main" and filename:
                return Path(filename)
    except sqlite3.Error:
        pass
    return None


def _auto_seal(db, entry):
    if not entry:
        return None
    db_path = _db_file(db)
    if db_path is None:
        return None
    import timestamps
    return timestamps.try_auto_seal(db_path, entry["seq"], entry["digest"])


def freeze_original(db, project):
    """V0: the paper as it stood before the first rewrite. Only when no version exists yet
    and an outlined section already has prose. Returns the saved summary, or None."""
    with section_review._transaction(db):
        create_tables(db)
        migrate(db)
        if _original_already_started(db):
            return None
    main, lines, found = _located_sections(db, project)
    if main is None or not any(L.paragraphs(lines, start, end) for _, start, end in found):
        return None
    compiled = _compile(db, project)
    entry = None
    with section_review._transaction(db, write=True):
        create_tables(db)
        if _original_already_started(db):
            return None
        section_review._create_tables(db)
        for plan, start, end in compiled["found"]:
            texts = [p["text"] for p in L.paragraphs(compiled["lines"], start, end)]
            if texts:
                db.execute("INSERT OR IGNORE INTO v2_baselines VALUES (?,?)",
                           (plan["id"], json.dumps(texts, ensure_ascii=False)))
        body = _store(db, 0, "original", "原稿", compiled, None)
        entry = journal.append(db, "version_saved", {"number": 0, "kind": "original", "pages": body["pages"],
                                                     "pdf_sha256": body["pdf_sha256"]}, revision=0)
    result = summary(body)
    seal = _auto_seal(db, entry)
    if seal is not None:
        result["seal"] = seal
    return result


def save(db, project, *, label=None, expected=None, responses=None, pdf=None, require_expected=False):
    """Compile the whole paper and keep it as the next version, answering every note the
    author left on the latest reviewed version."""
    label = _clean_label(label)
    with section_review._transaction(db):
        create_tables(db)
        migrate(db)
        previous = latest(db)
        if previous is not None and require_expected and expected is None:
            raise ValueError("请先读取 workspace_status，再用最新版本的稳定编号 expected_version 保存。")
    compiled = _compile(db, project, pdf)
    entry = None
    with section_review._transaction(db, write=True):
        create_tables(db)
        if compiled.get("lines") and L.expand(project, L._root(project) / compiled["main"]) != compiled["lines"]:
            raise ValueError("生成排版时论文源码已改变。请重新读取正文，确认修改后再保存版本。")
        if latest(db) != previous:
            raise ValueError("保存期间有了新的版本，请重新读取 workspace_status 后再试。")
        if (previous and previous.get("kind") == "version" and not previous.get("reviewed")
                and previous.get("source_sha256") == compiled["source_sha256"]
                and previous.get("label") == label
                and (expected is None or expected in (previous["number"], previous["previous_number"]))):
            return summary(previous)  # repeat the result of a save, including after a gap in stable IDs
        if expected is not None and (previous or {}).get("number") != expected:
            current = "还没有版本" if previous is None else f"最新是 V{previous['display_number']}"
            raise ValueError(f"版本已更新（{current}），请重新读取 workspace_status 后再保存。")
        answers = section_review._clean_responses(previous, responses)
        number = db.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM v2_versions").fetchone()[0]
        display_number = previous["display_number"] + 1 if previous else 1
        body = _store(db, number, "version", label, compiled, _whole_paper(db), answers,
                      display_number=display_number, previous_number=previous["number"] if previous else None)
        entry = journal.append(db, "version_saved", {"number": number, "display_number": display_number,
                                                     "label": label, "pages": body["pages"],
                                                     "pdf_sha256": body["pdf_sha256"], "responses": answers},
                               revision=number)
    result = summary(body)
    seal = _auto_seal(db, entry)
    if seal is not None:
        result["seal"] = seal
    return result


def cleanup(db, numbers, expected_numbers, expected_notes):
    """Delete selected version-owned blobs and renumber visible revisions in one transaction.

    numbers and expected_numbers contain permanent IDs. expected_notes holds the per-version
    note counts shown before confirmation. Historical summaries and IDs survive cleanup.
    """
    if (not isinstance(numbers, list) or not numbers or any(type(n) is not int or n <= 0 for n in numbers)
            or len(set(numbers)) != len(numbers)):
        raise ValueError("请选择要清理的修订稿。原稿 V0 始终保留。")
    if (not isinstance(expected_numbers, list) or not isinstance(expected_notes, list)
            or len(expected_numbers) != len(expected_notes)
            or any(type(n) is not int or n < 0 for n in expected_numbers + expected_notes)
            or len(set(expected_numbers)) != len(expected_numbers) or not set(numbers).issubset(expected_numbers)):
        raise ValueError("版本清单或批注已更新，请重新预览后再清理。")
    selected = set(numbers)
    with section_review._transaction(db, write=True):
        bodies = _bodies(db)
        if selected.issubset(b["number"] for b in bodies if b.get("cleaned_at")):
            return version_lists(db)  # replay after a committed request: nothing more to delete
        active = [b for b in bodies if not b.get("cleaned_at")]
        if ([b["number"] for b in active] != expected_numbers
                or [len(b.get("notes") or []) for b in active] != expected_notes):
            raise ValueError("版本清单或批注已更新，请重新预览后再清理。")
        when = _now()
        next_display = 1
        for body in active:
            number = body["number"]
            if number == 0:
                continue
            if number in selected:
                body.update(cleaned_at=when, last_display_number=body["display_number"],
                            display_number=None, has_pdf=False)
                db.execute("DELETE FROM v2_version_pages WHERE number=?", (number,))
            else:
                display = next_display
                next_display += 1
                if body["display_number"] == display:
                    continue
                body["display_number"] = display
            db.execute("UPDATE v2_versions SET body=? WHERE number=?", (json.dumps(body, ensure_ascii=False), number))
        journal.append(db, "versions_cleaned", {"removed": numbers, "order_before": expected_numbers},
                       recorded_at=when)
        return version_lists(db)


def submit_review(db, number, notes, approve=False):
    """The author's notes on the latest version. Answered by the AI in the next version."""
    with section_review._transaction(db, write=True):
        create_tables(db)
        body = latest(db)
        if body is None or body["number"] != number:
            raise ValueError("只能审阅最新的版本。请刷新后再提交。")
        if body.get("reviewed"):
            if body.get("notes") == notes and bool(body.get("approved")) == bool(approve):
                return summary(body)
            raise ValueError("这一版已经提交过审阅意见。")
        clean = _validate_notes(body, notes, approve)
        body.update(notes=clean, reviewed=_now(), approved=bool(approve))
        db.execute("UPDATE v2_versions SET body=? WHERE number=?", (json.dumps(body, ensure_ascii=False), number))
        journal.append(db, "version_reviewed", {"number": number, "display_number": body.get("display_number"),
                                                "notes": clean, "approved": bool(approve)},
                       revision=number)
        return summary(body)


def _validate_notes(body, notes, approve):
    if not isinstance(notes, list) or len(notes) > 200:
        raise ValueError("审阅意见格式不正确。")
    if approve and notes:
        raise ValueError("通过本版时请不要附带新意见。")
    if not approve and not notes:
        raise ValueError("请至少写一条意见，或选择本版通过。")
    clean, texts = [], set()
    sections = body.get("map") or {}
    for note in notes:
        if not isinstance(note, dict):
            raise ValueError("审阅意见格式不正确。")
        kind, text = note.get("kind"), note.get("text")
        if kind not in ("keep", "change"):
            raise ValueError("请为每条意见选择保留或修改。")
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("请写下保留或修改的理由。")
        if text.strip() in texts:
            raise ValueError("有两条意见内容相同。")
        texts.add(text.strip())
        page = note.get("page")
        if type(page) is not int or not 1 <= page <= body["pages"]:
            raise ValueError("请在页面上标出意见的位置。")
        item = dict(kind=kind, text=text.strip(), page=page)
        pin = note.get("pin")
        if pin is not None:
            if (not isinstance(pin, dict) or set(pin) != {"x", "y"}
                    or not all(isinstance(pin[k], (int, float)) and 0 <= pin[k] <= 1 for k in "xy")):
                raise ValueError("页面标记位置不正确。")
            item["pin"] = {"x": float(pin["x"]), "y": float(pin["y"])}
        section = note.get("section")
        if section:
            if section not in sections:
                raise ValueError("意见关联的章节不在这一版中。")
            item["section"] = section
            paragraph = note.get("paragraph")
            if paragraph:
                if paragraph not in sections[section]["paragraphs"]:
                    raise ValueError("意见关联的段落不在这一版中。")
                item["paragraph"] = paragraph
        quote = note.get("quote")
        if quote:
            if not isinstance(quote, str) or len(quote) > 1000:
                raise ValueError("原句节选过长。")
            item["quote"] = quote.strip()
        clean.append(item)
    return clean


def page(db, number, page_number):
    if not _has_table(db, "v2_version_pages"):
        return None
    row = db.execute("SELECT content FROM v2_version_pages WHERE number=? AND page=?",
                     (number, page_number)).fetchone()
    return row[0] if row else None


# ------------------------------------------------------------------ migration
def migrate(db):
    """Section editions and references published before 0.6.14 become versions that
    contain only their section's pages, in the order they were made."""
    if not _has_table(db, "v2_versions"):
        return
    if db.execute("SELECT 1 FROM v2_versions LIMIT 1").fetchone():
        return
    if not (_has_table(db, "v2_editions") or _has_table(db, "v2_references")):
        return
    items = []
    if _has_table(db, "v2_references"):
        for section, revision, section_title, title, created, pages, _ in db.execute(
                "SELECT section, revision, section_title, title, created, pages, fingerprint FROM v2_references"):
            items.append((created, "reference", section, revision, f"{section_title} · {title}", pages, None))
    if _has_table(db, "v2_editions"):
        for section, revision, body in db.execute("SELECT section, revision, body FROM v2_editions"):
            edition = json.loads(body)
            items.append((edition.get("created") or "", "edition", section, revision,
                          f"{edition.get('title', '')} · 第 {revision} 版", edition.get("pages", 0), edition))
    if not items:
        return
    in_tx = db.in_transaction
    if not in_tx:
        db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute("SELECT 1 FROM v2_versions LIMIT 1").fetchone():
            return
        for number, (created, kind, section, revision, label, pages, edition) in enumerate(sorted(items, key=lambda i: i[0]), 1):
            table = "v2_reference_assets" if kind == "reference" else "v2_pages"
            where = "section=? AND revision=?"
            rows = db.execute(f"SELECT page, content FROM {table} WHERE {where} AND page<>0", (section, revision)).fetchall()
            title = label.split(" · ")[0]
            body = dict(number=number, kind="migrated", label=label, created=created, pages=pages, main=None,
                        map={section: {"title": title, "page": 1, "paragraphs": {}}}, texts={}, changed={},
                        notes=(edition or {}).get("notes") or [], responses=(edition or {}).get("responses") or [],
                        reviewed=(edition or {}).get("reviewed"), approved=bool((edition or {}).get("approved")),
                        has_pdf=any(p == -1 for p, _ in rows), pdf_sha256=(edition or {}).get("pdf_sha256"))
            db.execute("INSERT INTO v2_versions VALUES (?,?)", (number, json.dumps(body, ensure_ascii=False)))
            db.executemany("INSERT INTO v2_version_pages VALUES (?,?,?)", ((number, p, c) for p, c in rows))
        if not in_tx:
            db.execute("COMMIT")
    except Exception:
        if not in_tx:
            db.execute("ROLLBACK")
        raise
