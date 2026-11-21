"""Whole-paper versions: V0 is frozen before the first rewrite, then V1, V2… are saved
only when the author asks in chat. Each version keeps the full typeset PDF, its page
images, the page every outlined section and paragraph starts on, and the author's
review notes with the AI's answers in the next version."""
import hashlib
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


def _bodies(db):
    if not _has_table(db, "v2_versions"):
        return []
    return [json.loads(body) for (body,) in db.execute("SELECT body FROM v2_versions ORDER BY number")]


def latest(db):
    bodies = _bodies(db)
    return bodies[-1] if bodies else None


def get(db, number):
    if not _has_table(db, "v2_versions"):
        return None
    row = db.execute("SELECT body FROM v2_versions WHERE number=?", (number,)).fetchone()
    return json.loads(row[0]) if row else None


def summary(body):
    """What the page and the AI see of a version; pages are fetched separately."""
    keys = ("number", "kind", "label", "created", "pages", "map", "changed", "notes", "responses",
            "reviewed", "approved", "has_pdf")
    return {k: body.get(k) for k in keys}


def listing(db):
    return [summary(body) for body in _bodies(db)] if db is not None else []


def ensure_migrated(database):
    """Bring section editions from before 0.6.14 into the version list (once, writable)."""
    import sqlite3
    from contextlib import closing
    if not database.is_file():
        return
    with closing(paperroom.connect(database)) as db:
        if not (_has_table(db, "v2_editions") or _has_table(db, "v2_references")):
            return
        if _has_table(db, "v2_versions") and db.execute("SELECT 1 FROM v2_versions LIMIT 1").fetchone():
            return
        with section_review._transaction(db, write=True):
            create_tables(db)
            migrate(db)


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


def _compile(db, project):
    main, lines, found = _located_sections(db, project)
    if main is None:
        raise ValueError("没有找到论文的主 .tex 文件或大纲中的章节标题，无法编译整篇版本。")
    source = _marked_paper(lines, found)
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as folder:
        farm, out = Path(folder) / "paper", Path(folder) / "out"
        farm.mkdir(); out.mkdir()
        for entry in main.parent.iterdir():
            if not entry.name.startswith("."):
                (farm / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
        marked = farm / (".paperroom-" + main.stem + ".tex")
        marked.write_text(source, encoding="utf-8")
        pdf = paperroom.compile_tex(marked, out, main.parent)
        aux = out / (marked.stem + ".aux")
        located = L.marks(aux.read_text("utf-8", errors="replace") if aux.is_file() else "")
        captured, images = paperroom.render_document(None, pdf, "all")
    page_map, texts = _page_map(lines, found, located)
    rel = main.relative_to(L._root(project)).as_posix()
    return dict(pdf=captured, images=images, map=page_map, texts=texts, main=rel,
                source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
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


def _store(db, number, kind, label, compiled, previous, responses=()):
    images = compiled["images"]
    body = dict(number=number, kind=kind, label=label, created=_now(), pages=len(images),
                main=compiled["main"], map=compiled["map"], texts=compiled["texts"],
                changed=_changes(previous, compiled["texts"]) if previous else {},
                notes=[], responses=list(responses), reviewed=None, approved=False,
                has_pdf=compiled["pdf"] is not None, source_sha256=compiled["source_sha256"],
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
def freeze_original(db, project):
    """V0: the paper as it stood before the first rewrite. Only when no version exists yet
    and an outlined section already has prose. Returns the saved summary, or None."""
    with section_review._transaction(db):
        create_tables(db)
        migrate(db)
        if latest(db) is not None:
            return None
    main, lines, found = _located_sections(db, project)
    if main is None or not any(L.paragraphs(lines, start, end) for _, start, end in found):
        return None
    compiled = _compile(db, project)
    with section_review._transaction(db, write=True):
        create_tables(db)
        if latest(db) is not None:
            return None
        section_review._create_tables(db)
        for plan, start, end in compiled["found"]:
            texts = [p["text"] for p in L.paragraphs(compiled["lines"], start, end)]
            if texts:
                db.execute("INSERT OR IGNORE INTO v2_baselines VALUES (?,?)",
                           (plan["id"], json.dumps(texts, ensure_ascii=False)))
        body = _store(db, 0, "original", "原稿", compiled, None)
        journal.append(db, "version_saved", {"number": 0, "kind": "original", "pages": body["pages"],
                                             "pdf_sha256": body["pdf_sha256"]}, revision=0)
    return summary(body)


def save(db, project, *, label=None, expected=None, responses=None):
    """Compile the whole paper and keep it as the next version, answering every note the
    author left on the latest reviewed version."""
    label = _clean_label(label)
    with section_review._transaction(db):
        create_tables(db)
        migrate(db)
        previous = latest(db)
    compiled = _compile(db, project)
    if (previous and previous.get("kind") == "version" and not previous.get("reviewed")
            and previous.get("source_sha256") == compiled["source_sha256"]
            and previous.get("label") == label
            and (expected is None or expected in (previous["number"], previous["number"] - 1))):
        return summary(previous)  # a retried save of the same text keeps the version it made
    if expected is not None and (previous or {}).get("number") != expected:
        current = "还没有版本" if previous is None else f"最新是 V{previous['number']}"
        raise ValueError(f"版本已更新（{current}），请重新读取 workspace_status 后再保存。")
    answers = section_review._clean_responses(previous, responses)
    with section_review._transaction(db, write=True):
        create_tables(db)
        if latest(db) != previous:
            raise ValueError("保存期间有了新的版本，请重新读取 workspace_status 后再试。")
        number = 1 if previous is None else previous["number"] + 1
        body = _store(db, number, "version", label, compiled, previous, answers)
        journal.append(db, "version_saved", {"number": number, "label": label, "pages": body["pages"],
                                             "pdf_sha256": body["pdf_sha256"], "responses": answers},
                       revision=number)
    return summary(body)


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
        journal.append(db, "version_reviewed", {"number": number, "notes": clean, "approved": bool(approve)},
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
            items.append((created, "reference", section, revision, f"{section_title} · 原稿", pages, None))
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
