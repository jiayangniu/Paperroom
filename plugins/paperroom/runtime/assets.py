"""Figures, tables and data the author may want beside the outline or the review.

Floats come from the paper's own LaTeX (following input files). The AI writes them
and calls publish_floats; Paperroom compiles the whole paper once with an invisible
marker inside each float and keeps the pages where they actually landed, so the
author sees the real layout. The author can confirm a float or leave instructions
for the AI here; neither gates any drafting. Unused images and CSV data are shown
from the project folder. The paper's files are never written.
"""
import json
import csv
from datetime import datetime, timezone
import hashlib
import io
import os
import re
import tempfile
from pathlib import Path

import latex_source as L
import paperroom

FLOATS = {"figure": "figure", "figure*": "figure", "wrapfigure": "figure", "sidewaysfigure": "figure",
          "table": "table", "table*": "table", "wraptable": "table", "sidewaystable": "table"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
GRAPHIC_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".eps")
FIGURE_FOLDERS = re.compile(r"(^|/)(fig|figs|figure|figures|img|imgs|image|images|plot|plots|graphics)(/|$)", re.I)
DATA_TYPES = {".csv": ",", ".tsv": "\t"}
MAX_FILES = 300


def _id(*parts):
    return hashlib.sha256("\x00".join(map(str, parts)).encode("utf-8")).hexdigest()[:16]


def _braced(text, start):
    """Content of the brace group opening at text[start] == '{'."""
    depth, out = 0, []
    for char in text[start:]:
        if char == "{":
            depth += 1
            if depth == 1:
                continue
        elif char == "}":
            depth -= 1
            if depth == 0:
                return "".join(out)
        out.append(char)
    return "".join(out)


def _command(text, name):
    match = re.search(r"\\" + name + r"\*?\s*(?:\[[^\]]*\])?\s*\{", text)
    return _braced(text, match.end() - 1) if match else None


def _macros(lines):
    """Argument-free \\newcommand definitions from the preamble, e.g. a method name."""
    found = {}
    for raw, _, _ in lines:
        code = L.strip_comments(raw)
        if re.search(r"\\begin\s*\{document\}", code):
            break
        for match in re.finditer(r"\\(?:re)?newcommand\*?\s*\{?\\([A-Za-z]+)\}?\s*\{", code):
            found[match.group(1)] = _braced(code, match.end() - 1)
    return found


def plain_caption(tex, macros=None):
    """Readable caption text: keep the words, drop formatting and references."""
    for name, body in (macros or {}).items():
        tex = re.sub(r"\\" + name + r"(?![A-Za-z])(\{\})?", lambda _: body, tex or "")
    text = re.sub(r"\\(?:cite[pt]?|citep|citet|autocite|parencite)\*?(?:\[[^\]]*\])*\{[^{}]*\}", "[引用]", tex or "")
    text = re.sub(r"\\(?:ref|eqref|autoref|cref|Cref)\{([^{}]*)\}", r"[\1]", text)
    text = re.sub(r"\\label\{[^{}]*\}", "", text)
    text = re.sub(r"\\[a-zA-Z]+\*?\s*(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
    text = text.replace("~", " ").replace("{", "").replace("}", "")
    return " ".join(text.split())


def _graphic_dirs(lines, base):
    dirs = [base]
    for raw, _, _ in lines:
        code = L.strip_comments(raw)
        match = re.search(r"\\graphicspath\s*\{", code)
        if match:
            group = _braced(code, match.end() - 1)
            dirs += [base / d for d in re.findall(r"\{([^{}]*)\}", group)]
    return dirs


_HASHES = {}


def _stamp(path):
    """Cache key for a file's contents. The inode and change time catch a file
    replaced under the same name, size and modification time."""
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino, stat.st_ctime_ns)


def _file_hash(path):
    key = _stamp(path)
    if key not in _HASHES:
        _HASHES[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return _HASHES[key]


def _resolve_graphic(name, dirs, root):
    name = name.strip()
    for folder in dirs:
        for candidate in [folder / name] + [folder / (name + ext) for ext in GRAPHIC_EXTS]:
            try:
                path = candidate.resolve(strict=True)
            except OSError:
                continue
            if path.is_file() and path.is_relative_to(root):
                return path
    return None


def _aux_numbers(main):
    """Label numbers from the paper's own last build, if present."""
    aux = main.with_suffix(".aux")
    numbers = {}
    if aux.is_file():
        text = aux.read_text("utf-8", errors="replace")
        for label, number in re.findall(r"\\newlabel\{([^{}]+)\}\{\{([^{}]*)\}", text):
            numbers[label] = number
    return numbers


def _inside(path, root):
    """The file's real location if it is inside the project, else None (links that
    lead outside, e.g. to the author's other files, are never read)."""
    try:
        target = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return target if target.is_relative_to(root) and target.is_file() else None


def _walk(root):
    count = 0
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.startswith("."):
                continue
            count += 1
            if count > 5000:
                return
            path = Path(directory, name)
            if _inside(path, root) is not None:
                yield path


def _preview_csv(path, delimiter):
    """First rows of a data file. A problem in one file (an oversized field, bad
    encoding) yields the rows read so far and a note, never an error for the page."""
    rows, total, problem = [], 0, None
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
            for row in csv.reader(stream, delimiter=delimiter):
                total += 1
                if len(rows) < 6:
                    rows.append([cell[:40] for cell in row[:8]])
                if total > 100000:
                    break
    except (csv.Error, OSError, UnicodeError, ValueError, MemoryError) as exc:
        problem = "这个文件的部分内容无法预览，已显示读到的行。" + ("（单个字段过长）" if "field larger" in str(exc) else "")
        return rows, None, problem
    return rows, total, problem


def index(project):
    """{figures, tables, images, data, main} for the project. Never raises on content."""
    root = Path(project).resolve()
    result = dict(main=None, figures=[], tables=[], images=[], data=[], problem=None)
    used = set()
    try:
        main = L.find_main(root)
    except L.SourceError as exc:
        main, result["problem"] = None, str(exc)
    if main is not None:
        result["main"] = main.relative_to(root).as_posix()
        try:
            lines = L.expand(root, main)
        except L.SourceError as exc:
            lines, result["problem"] = [], str(exc)
        dirs = _graphic_dirs(lines, main.parent)
        numbers = _aux_numbers(main)
        macros = _macros(lines)
        units = L.sections(lines)
        counters = {"figure": 0, "table": 0}
        index_line = 0
        while index_line < len(lines):
            code = L.strip_comments(lines[index_line][0])
            match = re.search(r"\\begin\s*\{([^{}]+)\}", code)
            kind = FLOATS.get(match.group(1).strip()) if match else None
            if not kind:
                index_line += 1
                continue
            env, start = match.group(1).strip(), index_line
            body = []
            while index_line < len(lines):
                body.append(L.strip_comments(lines[index_line][0]))
                if re.search(r"\\end\s*\{" + re.escape(env) + r"\}", body[-1]):
                    break
                index_line += 1
            index_line += 1
            block = "\n".join(body)
            counters[kind] += 1
            label = _command(block, "label")
            caption = _command(block, "caption")
            graphics, contents = [], []
            for g in re.finditer(r"\\includegraphics\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^{}]+)\}", block):
                path = _resolve_graphic(g.group(1), dirs, root)
                if path is not None:
                    used.add(path)
                    graphics.append(path.relative_to(root).as_posix())
                    contents.append(_file_hash(path))
            _, file, line = lines[start]
            section = next((title for title, s, e in units if s <= start < e), None)
            item = dict(id=_id(kind, Path(file).relative_to(root).as_posix(), line), kind=kind, label=label,
                        key=label or f"{kind}-{counters[kind]}", span=(start, index_line - 1),
                        # The float's LaTeX and the bytes of every image it shows: replacing
                        # an image under the same name changes the float.
                        digest="v2:" + hashlib.sha256((L.plain(block) + "\x00" + "\x00".join(contents)).encode("utf-8")).hexdigest()[:24],
                        legacy_digest=hashlib.sha256(L.plain(block).encode("utf-8")).hexdigest()[:16],
                        number=numbers.get(label) or str(counters[kind]), numbered_by="aux" if label in numbers else "order",
                        caption=plain_caption(caption, macros), section=section, graphics=graphics,
                        where=f"{Path(file).relative_to(root).as_posix()}:{line}", source=block[:6000])
            item["preview"] = bool(graphics)
            result["figures" if kind == "figure" else "tables"].append(item)
    for path in _walk(root):
        relative = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        if suffix in IMAGE_TYPES or (suffix == ".pdf" and FIGURE_FOLDERS.search(relative)):
            if path.resolve() not in used and len(result["images"]) < MAX_FILES:
                result["images"].append(dict(id=_id("image", relative), kind="image", where=relative,
                                             preview=suffix in IMAGE_TYPES or suffix == ".pdf"))
        elif suffix in DATA_TYPES and len(result["data"]) < MAX_FILES:
            rows, total, problem = _preview_csv(path, DATA_TYPES[suffix])
            result["data"].append(dict(id=_id("data", relative), kind="data", where=relative, rows=rows, total=total,
                                       problem=problem))
    result["_lines"] = lines if main is not None else []
    result["_main"] = main
    return result


def public(data):
    """The index without internal fields, for the browser and the AI."""
    out = {k: v for k, v in data.items() if not k.startswith("_")}
    for group in ("figures", "tables"):
        out[group] = [{k: v for k, v in item.items() if k not in ("span", "legacy_digest")} for item in data[group]]
    return out


def _find(project, item_id):
    data = index(project)
    for group in ("figures", "tables", "images"):
        for item in data[group]:
            if item["id"] == item_id:
                return item
    return None


def _rasterize(pdf):
    images = paperroom.render(None, pdf, "1")
    return images[0]


_CACHE = {}


def preview(project, item_id):
    """(mime, bytes) for a figure, table or unused image, or None."""
    root = Path(project).resolve()
    item = _find(root, item_id)
    if item is None:
        return None
    if item["kind"] == "table":
        return None
    target = _inside(root / (item["graphics"][0] if item["kind"] == "figure" else item["where"]), root)
    if target is None:
        return None
    key = _stamp(target)
    if key not in _CACHE:
        suffix = target.suffix.lower()
        if suffix in IMAGE_TYPES:
            _CACHE[key] = (IMAGE_TYPES[suffix], target.read_bytes())
        elif suffix == ".pdf":
            _CACHE[key] = ("image/png", _rasterize(target))
        else:
            return None
    return _CACHE[key]


FLOAT_MARK = "paperroom-float-"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tables(db):
    db.execute("CREATE TABLE IF NOT EXISTS v2_float_builds (build INTEGER PRIMARY KEY, body TEXT NOT NULL)")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_float_pages (
        build INTEGER, page INTEGER, content BLOB NOT NULL, PRIMARY KEY (build, page))""")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_float_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, target TEXT NOT NULL, label TEXT, text TEXT NOT NULL,
        created TEXT NOT NULL, build INTEGER, status TEXT NOT NULL, response TEXT, answered_build INTEGER)""")
    db.execute("""CREATE TABLE IF NOT EXISTS v2_float_confirmations (
        target TEXT PRIMARY KEY, digest TEXT NOT NULL, build INTEGER, created TEXT NOT NULL)""")


def _has(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone())


def _source_digest(data):
    """The LaTeX and every float's images: either changing means the build is stale."""
    images = "\n".join(item["digest"] for item in data["figures"] + data["tables"])
    return hashlib.sha256(("\n".join(raw for raw, _, _ in data["_lines"]) + "\n" + images).encode("utf-8")).hexdigest()


def build(db, project, origin):
    """Compile the paper once with a marker in each float and keep their pages."""
    root = Path(project).resolve()
    data = index(root)
    if data["_main"] is None:
        raise ValueError(data["problem"] or "项目中没有找到 LaTeX 主文件。")
    floats = data["figures"] + data["tables"]
    if not floats:
        raise ValueError("论文源码中还没有 figure 或 table 环境。")
    lines = [raw for raw, _, _ in data["_lines"]]
    for number, item in enumerate(floats):
        last = item["span"][1]
        # Inside the float, just before its own (the line's last) \end: the write runs
        # when the float is shipped out, so it records the page the float landed on.
        at = max(m.start() for m in re.finditer(r"\\end\s*\{", lines[last]))
        lines[last] = lines[last][:at] + L.mark(FLOAT_MARK + str(number)) + lines[last][at:]
    digest = _source_digest(data)
    names = [FLOAT_MARK + str(n) for n in range(len(floats))]
    captured, images, pages, located = paperroom.render_marked(
        data["_main"], "\n".join(lines) + "\n", lambda found: sorted({found[n] for n in names if n in found}))
    if not images:
        raise ValueError("编译完成，但没有找到图表所在的页面。")
    records = []
    for number, item in enumerate(floats):
        physical = located.get(names[number])
        records.append({**{k: v for k, v in item.items() if k not in ("span", "source", "legacy_digest")},
                        "physical": physical, "page": pages.index(physical) + 1 if physical in pages else None})
    with db:
        db.execute("BEGIN IMMEDIATE")
        _tables(db)
        number = db.execute("SELECT COALESCE(MAX(build),0)+1 FROM v2_float_builds").fetchone()[0]
        body = dict(build=number, created=_now(), origin=origin, digest=digest, pages=pages, floats=records,
                    main=data["main"])
        db.execute("INSERT INTO v2_float_builds VALUES (?,?)", (number, json.dumps(body, ensure_ascii=False)))
        db.execute("INSERT INTO v2_float_pages VALUES (?,?,?)", (number, -1, captured))
        db.executemany("INSERT INTO v2_float_pages VALUES (?,?,?)",
                       ((number, index + 1, image) for index, image in enumerate(images)))
    return state(db, root)


def build_asset(db, number, page=None):
    if db is None or not _has(db, "v2_float_pages"):
        return None
    row = db.execute("SELECT content FROM v2_float_pages WHERE build=? AND page=?",
                     (number, -1 if page is None else page)).fetchone()
    return row[0] if row else None


def state(db, project, data=None):
    """Latest float build, whether the source changed since, and the author's notes."""
    root = Path(project).resolve()
    data = data or index(root)
    latest = None
    notes, confirmed = [], {}
    if db is not None and _has(db, "v2_float_builds"):
        row = db.execute("SELECT body FROM v2_float_builds ORDER BY build DESC LIMIT 1").fetchone()
        latest = json.loads(row[0]) if row else None
    if db is not None and _has(db, "v2_float_notes"):
        notes = [dict(id=i, target=t, label=l, text=x, created=c, build=b, status=st, response=r, answered_build=a)
                 for i, t, l, x, c, b, st, r, a in db.execute(
                     "SELECT id,target,label,text,created,build,status,response,answered_build FROM v2_float_notes ORDER BY id")]
    if db is not None and _has(db, "v2_float_confirmations"):
        current = {item["key"]: item for item in data["figures"] + data["tables"]}
        for target, digest, number, created in db.execute("SELECT target,digest,build,created FROM v2_float_confirmations"):
            item = current.get(target)
            if item is None:
                changed = True
            elif digest.startswith("v2:"):
                changed = item["digest"] != digest
            else:
                # Older confirmations did not record image contents: a float with
                # images cannot be shown as unchanged, so it asks to be confirmed again.
                changed = bool(item["graphics"]) or item["legacy_digest"] != digest
            confirmed[target] = dict(build=number, created=created, changed=changed)
    if latest is not None and data["_lines"]:
        latest["stale"] = latest["digest"] != _source_digest(data)
    return dict(build=latest, notes=notes, confirmed=confirmed)


def _target_label(data, target):
    if target == "new":
        return "新图表"
    item = next((i for i in data["figures"] + data["tables"] if i["key"] == target), None)
    if item is None:
        raise ValueError("找不到这个图表，请刷新后重试。")
    return ("图 " if item["kind"] == "figure" else "表 ") + item["number"] + (f" · {item['label']}" if item["label"] else "")


def add_note(db, project, target, text):
    """An author instruction for the AI about one float, or about a new one."""
    if not isinstance(target, str) or not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("请写下给 AI 的图表调整说明（不超过 4000 字）。")
    data = index(project)
    label = _target_label(data, target)
    with db:
        db.execute("BEGIN IMMEDIATE")
        _tables(db)
        latest = db.execute("SELECT MAX(build) FROM v2_float_builds").fetchone()[0]
        db.execute("INSERT INTO v2_float_notes (target,label,text,created,build,status) VALUES (?,?,?,?,?,'open')",
                   (target, label, text.strip(), _now(), latest))
    return state(db, project, data)


def withdraw(db, project, note):
    with db:
        db.execute("BEGIN IMMEDIATE")
        _tables(db)
        changed = db.execute("UPDATE v2_float_notes SET status='withdrawn' WHERE id=? AND status='open'", (note,)).rowcount
    if not changed:
        raise ValueError("这条指令已处理或已撤回。")
    return state(db, project)


def confirm(db, project, target, value, build=None, digest=None):
    """The author's own mark that a float is settled. It never gates drafting.

    A confirmation records what the author was looking at: the float as placed in
    the compiled build shown on the card (build), or, before any build, the file
    preview loaded with the card (digest). A newer file on disk is never confirmed
    in its place; it shows as changed after the confirmation."""
    if type(value) is not bool:
        raise ValueError("请重新确认。")
    data = index(project)
    item = next((i for i in data["figures"] + data["tables"] if i["key"] == target), None)
    if item is None:
        raise ValueError("找不到这个图表，请刷新后重试。")
    with db:
        db.execute("BEGIN IMMEDIATE")
        _tables(db)
        if value:
            if not isinstance(digest, str) or not digest or (build is not None and type(build) is not int):
                raise ValueError("请刷新页面，看过图表后再确认。")
            if build is not None:
                row = db.execute("SELECT body FROM v2_float_builds WHERE build=?", (build,)).fetchone()
                placed = next((f for f in json.loads(row[0])["floats"] if f["key"] == target), None) if row else None
                if placed is None or placed.get("digest") != digest:
                    raise ValueError("这张图表的编译版本已变化，请刷新后再确认。")
            db.execute("INSERT OR REPLACE INTO v2_float_confirmations VALUES (?,?,?,?)",
                       (target, digest, build, _now()))
        else:
            db.execute("DELETE FROM v2_float_confirmations WHERE target=?", (target,))
    return state(db, project, data)


def check_responses(db, responses):
    """The AI answers open instructions by id; validated before compiling."""
    if not responses:
        return []
    open_ids = set()
    if _has(db, "v2_float_notes"):
        open_ids = {i for i, in db.execute("SELECT id FROM v2_float_notes WHERE status='open'")}
    clean, seen = [], set()
    for item in responses:
        if not isinstance(item, dict) or type(item.get("request")) is not int or item["request"] not in open_ids:
            raise ValueError("responses 中的 request 应为尚未处理的图表指令编号。")
        if item["request"] in seen:
            raise ValueError(f"第 {item['request']} 条图表指令回应了不止一次。")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            raise ValueError("请为每条图表指令写下处理说明（不超过 2000 字）。")
        seen.add(item["request"])
        clean.append((item["request"], text.strip()))
    return clean


def answer(db, project, responses, number):
    with db:
        db.execute("BEGIN IMMEDIATE")
        _tables(db)
        db.executemany("UPDATE v2_float_notes SET status='done', response=?, answered_build=? WHERE id=? AND status='open'",
                       ((text, number, note) for note, text in responses))
    return state(db, project)


def open_requests(db):
    if db is None or not _has(db, "v2_float_notes"):
        return []
    return [dict(id=i, target=t, label=l, text=x) for i, t, l, x in db.execute(
        "SELECT id,target,label,text FROM v2_float_notes WHERE status='open' ORDER BY id")]
