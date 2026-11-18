"""The manuscript's LaTeX files are the single source of section prose.

A section is bound to its heading in the paper's main .tex (following \\input,
\\include and \\subfile). Paragraphs are blank-line separated prose blocks of that
section; floats, display math, headings and comments are not prose. Paperroom only
reads these files. Rendering compiles a marked copy outside the project.
"""
from difflib import SequenceMatcher
import os
import re
from pathlib import Path

INCLUDE = re.compile(r"\\(input|include|subfile)\s*\{([^{}]+)\}")
COMMENT = re.compile(r"(?<!\\)%")
HEADING = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\s*(?:\[[^\]]*\])?\s*\{")
LEVEL = {"part": -1, "chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3, "paragraph": 4}
STOP = re.compile(r"\\(?:end\{document\}|appendix\b|bibliography\s*\{|printbibliography\b|begin\{thebibliography\})")
LABEL = re.compile(r"\\label\s*\{([^{}]+)\}")
# Floats and listings sit between paragraphs; display math belongs to its paragraph.
NON_PROSE = ("figure", "figure*", "table", "table*", "algorithm", "algorithm*", "algorithmic", "tabular",
             "tabularx", "lstlisting", "verbatim", "minted", "wrapfigure", "wraptable", "sidewaysfigure",
             "sidewaystable", "tikzpicture")
BEGIN = re.compile(r"\\begin\s*\{([^{}]+)\}")
END = re.compile(r"\\end\s*\{([^{}]+)\}")
CJK = re.compile("[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef\U00020000-\U000323af]")
WORD = re.compile("[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef\U00020000-\U000323af]|[^\\s\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]+")
SEPARATOR = re.compile(r"(\\(?:label\s*\{[^{}]*\}|clearpage|newpage|cleardoublepage|pagebreak|noindent|medskip|"
                       r"bigskip|smallskip|vspace\*?\s*\{[^{}]*\})\s*)+")
START_MARK, END_MARK = "paperroom-start", "paperroom-end"


def mark(name):
    return _mark(name)


def _mark(name):
    # Written at shipout as an .aux comment with the physical page number, so
    # roman front matter or restarted numbering cannot shift the excerpt.
    return ("\\write\\csname @auxout\\endcsname{\\csname @percentchar\\endcsname " + name + " "
            "\\ifx\\ReadonlyShipoutCounter\\undefined\\the\\value{page}\\else\\the\\ReadonlyShipoutCounter\\fi}")


class SourceError(ValueError):
    """The section could not be found or read in the project's LaTeX."""


def _read(path, files=None, errors="strict"):
    """File text, or the pending content an edit is about to write (files maps
    resolved paths to new text, or None for a deletion)."""
    if files and path in files:
        if files[path] is None:
            raise FileNotFoundError(path)
        return files[path]
    return path.read_text("utf-8", errors=errors)


def _root(project):
    return Path(project).resolve(strict=True)


def _visible(path, root):
    rel = path.relative_to(root)
    return not any(part.startswith(".") for part in rel.parts)


def main_files(project, files=None):
    """Every .tex in the project that is a whole document. Unreadable files, links
    leading outside the project and link loops are skipped, never fatal."""
    root, found = _root(project), []
    def candidates():
        for directory, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(files):
                if name.endswith(".tex") and not name.startswith("."):
                    yield Path(directory, name)
    pending = [p for p in (files or {}) if p.suffix == ".tex" and p.is_relative_to(root) and not p.exists()]
    for index, path in enumerate([*candidates(), *pending]):
        if index >= 400:
            break
        try:
            target = path if path in pending else path.resolve(strict=True)
            if not target.is_relative_to(root) or (target not in pending and (
                    not target.is_file() or target.stat().st_size > 2_000_000)):
                continue
            text = strip_comments(_read(target, files, "replace"))
        except (OSError, RuntimeError):
            continue
        if re.search(r"\\documentclass\b", text) and re.search(r"\\begin\s*\{document\}", text):
            found.append(target)
    return found


def find_main(project, preferred=None, files=None):
    """Return the main .tex, or None for a project without LaTeX documents."""
    root = _root(project)
    if preferred:
        path = (root / preferred).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != ".tex":
            raise SourceError(f"找不到主文件 {preferred}。")
        return path
    mains = main_files(root, files)
    if len(mains) <= 1:
        return mains[0] if mains else None
    named = [m for m in mains if m.name.lower() in ("main.tex", "paper.tex", "manuscript.tex")]
    if len(named) == 1:
        return named[0]
    names = "、".join(m.relative_to(root).as_posix() for m in mains[:6])
    raise SourceError(f"项目中有多个主 .tex（{names}）。请用 bind_section_source 指定本节所在的主文件。")


def strip_comments(text):
    return "\n".join(line[:m.start()] if (m := COMMENT.search(line)) else line for line in text.split("\n"))


class Lines(list):
    """Expanded source lines; excluded lists files left out by \\includeonly."""
    excluded = ()


def _include_only(main, files):
    """Names allowed by \\includeonly in the main preamble, or None."""
    try:
        text = strip_comments(_read(main, files, "replace"))
    except OSError:
        return None
    preamble = re.split(r"\\begin\s*\{document\}", text, maxsplit=1)[0]
    match = re.search(r"\\includeonly\s*\{([^{}]*)\}", preamble)
    if not match:
        return None
    return {re.sub(r"\.tex$", "", name.strip()) for name in match.group(1).split(",") if name.strip()}


def expand(project, main, files=None):
    """Lines of the main file with includes inlined: (text, file, line number).
    Files left out by \\includeonly contribute only their page breaks, exactly as
    LaTeX would, so the marked copy compiles to the same document."""
    root = _root(project)
    base = main.parent
    lines = Lines()
    lines.excluded, lines.root = [], root
    only = _include_only(main, files)

    def read(path, numbered, depth, seen):
        for number, raw in numbered:
            comment = COMMENT.search(raw)
            code = raw[:comment.start()] if comment else raw
            match = INCLUDE.search(code)
            target = None
            if match:
                name = match.group(2).strip()
                for candidate in (base / name, base / (name + ".tex")):
                    if files and candidate.resolve() in files and files[candidate.resolve()] is not None:
                        resolved = candidate.resolve()
                    else:
                        try:
                            resolved = candidate.resolve(strict=True)
                        except OSError:
                            continue
                    if ((resolved.is_file() or (files and resolved in files)) and resolved.is_relative_to(root) and resolved.suffix.lower() == ".tex"
                            and resolved not in seen and depth < 20):
                        target = resolved
                        break
            if target is None:
                lines.append((raw, path, number))
                continue
            before, after = code[:match.start()], code[match.end():]
            if before.strip():
                lines.append((before, path, number))
            kind = match.group(1)
            if kind == "include":  # \include starts and ends on a new page
                lines.append(("\\clearpage", path, number))
            if kind == "include" and only is not None and re.sub(r"\.tex$", "", match.group(2).strip()) not in only:
                lines.excluded.append(target)
            else:
                walk(target, depth + 1, seen | {target}, body_only=kind == "subfile")
            if kind == "include":
                lines.append(("\\clearpage", path, number))
            if after.strip():
                lines.append((after, path, number))

    def walk(path, depth, seen, body_only=False):
        try:
            source = _read(path, files).splitlines()
        except (OSError, UnicodeError) as exc:
            raise SourceError(f"无法读取 {path.relative_to(root).as_posix()}：{exc}") from exc
        numbered = list(enumerate(source, 1))
        if body_only:  # a subfile carries its own preamble; only its body is inserted
            code = [strip_comments(t) for _, t in numbered]
            begin = next((i for i, t in enumerate(code) if re.search(r"\\begin\s*\{document\}", t)), None)
            end = next((i for i, t in enumerate(code) if re.search(r"\\end\s*\{document\}", t)), None)
            if begin is not None and end is not None and begin < end:
                numbered = numbered[begin + 1:end]
        read(path, numbered, depth, seen)
    walk(main, 0, {main})
    return lines


def _heading_title(code, start):
    depth, out = 1, []
    for char in code[start:]:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
        out.append(char)
    return "".join(out)


def plain(text):
    return " ".join(text.split())


def _title_key(text):
    text = re.sub(r"\\[a-zA-Z]+\*?\s*", " ", text)
    return plain(re.sub(r"[{}~]", " ", text)).casefold()


def locate(lines, *, title=None, label=None):
    """Index range [start, end) of the section body, starting at its heading line."""
    headings = []
    for index, (raw, _, _) in enumerate(lines):
        code = strip_comments(raw)
        match = HEADING.search(code)
        if match:
            headings.append((index, LEVEL[match.group(1)], _heading_title(code, match.end())))
    candidates = []
    for position, (index, level, heading) in enumerate(headings):
        if label:
            window = " ".join(strip_comments(lines[i][0]) for i in range(index, min(index + 3, len(lines))))
            if label not in LABEL.findall(window):
                continue
        elif _title_key(heading) != _title_key(title or ""):
            continue
        candidates.append((position, index, level))
    if not candidates and not label and _title_key(title or "") in ABSTRACT:
        return _abstract(lines)
    if not candidates:
        for path in getattr(lines, "excluded", ()):
            try:
                code = strip_comments(path.read_text("utf-8", errors="replace"))
            except OSError:
                continue
            for match in HEADING.finditer(code):
                heading = _heading_title(code, match.end())
                if (label and label in LABEL.findall(code[match.end():match.end() + 400])) or \
                        (not label and _title_key(heading) == _title_key(title or "")):
                    where = path.relative_to(lines.root).as_posix() if getattr(lines, "root", None) else path.name
                    raise SourceError(f"「{title or label}」位于 {where}，但主文件的 \\includeonly 没有包含它，"
                                      "编译结果里不会出现这一节。请在 \\includeonly 中加入该文件，或删除 \\includeonly 后重试。")
        what = f"\\label{{{label}}}" if label else f"标题为「{title}」的章节"
        raise SourceError(f"主 .tex 中没有找到{what}。新章节请先写入 \\section 标题，或用 bind_section_source 绑定。")
    if len(candidates) > 1:
        raise SourceError(f"主 .tex 中有多个「{title}」章节，请用 bind_section_source 指定 label。")
    position, start, level = candidates[0]
    end = len(lines)
    for index, other_level, _ in headings[position + 1:]:
        if other_level <= level:
            end = index
            break
    for index in range(start + 1, end):
        if STOP.search(strip_comments(lines[index][0])):
            end = index
            break
    return start, end


ABSTRACT = {"abstract", "摘要"}


def _abstract(lines):
    begin = next((i for i, (raw, _, _) in enumerate(lines)
                  if re.search(r"\\begin\s*\{abstract\}", strip_comments(raw))), None)
    if begin is None:
        raise SourceError("主 .tex 中没有找到 abstract 环境或 Abstract 章节。")
    end = next((i for i in range(begin + 1, len(lines))
                if re.search(r"\\end\s*\{abstract\}", strip_comments(lines[i][0]))), len(lines))
    return begin, end


def sections(lines):
    """Every top-level prose unit: the abstract environment and each heading at the
    paper's top heading level, as (title, start, end)."""
    found = []
    try:
        start, end = _abstract(lines)
        found.append(("Abstract", start, end))
    except SourceError:
        pass
    headings = []
    for index, (raw, _, _) in enumerate(lines):
        code = strip_comments(raw)
        match = HEADING.search(code)
        if match and match.group(1) != "part":
            headings.append((index, LEVEL[match.group(1)], _heading_title(code, match.end())))
    if headings:
        top = min(level for _, level, _ in headings)
        for position, (index, level, title) in enumerate(headings):
            if level != top:
                continue
            end = next((i for i, other, _ in headings[position + 1:] if other <= level), len(lines))
            end = next((i for i in range(index + 1, end) if STOP.search(strip_comments(lines[i][0]))), end)
            found.append((title, index, end))
    return found


def labels_near(lines, index):
    window = " ".join(strip_comments(lines[i][0]) for i in range(index, min(index + 3, len(lines))))
    return LABEL.findall(window)


FLOAT_ENVS = ("figure", "figure*", "table", "table*", "algorithm", "algorithm*", "wrapfigure", "wraptable",
              "sidewaysfigure", "sidewaystable")
IF_OPEN = re.compile(r"\\if[a-zA-Z@]*(?![a-zA-Z@])")


def _after_heading(code):
    """Text that follows a heading (and its labels) on the same line."""
    match = HEADING.search(code)
    if not match:
        return 0, code
    close = match.end() + len(_heading_title(code, match.end())) + 1
    rest = code[close:]
    labels = re.match(r"(\s*\\label\s*\{[^{}]*\})*\s*", rest)
    return close + labels.end(), rest[labels.end():]


def paragraphs(lines, start, end):
    """Prose paragraphs of the section: [{text, file, line, index, col}].

    Follows TeX: a blank line ends a paragraph, a comment-only line does not.
    Text after the heading on its own line is prose. Floats are not prose;
    \\iffalse ... \\fi and comment environments are hidden. Other conditionals
    cannot be decided here: the compiled markers show whether a paragraph printed.
    index/col locate the first character, for the compile marker."""
    out, block, env, hidden = [], [], [], []

    def flush():
        text = "\n".join(t for t, *_ in block).strip()
        if text:
            _, path, number, index, col = block[0]
            out.append(dict(text=text, file=path, line=number, index=index, col=col))
        block.clear()

    for index in range(start, end):
        raw, path, number = lines[index]
        code = strip_comments(raw)
        offset = 0
        if index == start:
            if not HEADING.search(code):
                continue  # the abstract's \begin line
            offset, code = _after_heading(code)
        stripped = code.strip()
        # Conditionals written on their own lines. \\iffalse/\\iftrue are decided here;
        # other \\if... are assumed shown and checked by the compiled markers.
        if stripped == "\\fi" and hidden and hidden[-1]["kind"] == "if":
            hidden.pop()
            continue
        if stripped == "\\else" and hidden and hidden[-1]["kind"] == "if":
            if hidden[-1]["known"]:
                hidden[-1]["visible"] = not hidden[-1]["visible"]
            continue
        if IF_OPEN.fullmatch(stripped):
            hidden.append(dict(kind="if", known=stripped in ("\\iffalse", "\\iftrue"),
                               visible=stripped != "\\iffalse"))
            continue
        if re.fullmatch(r"\\begin\s*\{comment\}", stripped):
            hidden.append(dict(kind="comment", known=True, visible=False))
            continue
        if re.fullmatch(r"\\end\s*\{comment\}", stripped) and hidden and hidden[-1]["kind"] == "comment":
            hidden.pop()
            continue
        if not all(level["visible"] for level in hidden):
            continue
        for name in BEGIN.findall(code):
            if name.strip() in NON_PROSE or env:
                env.append(name.strip())
        if env:
            for name in END.findall(code):
                if env and name.strip() == env[-1]:
                    env.pop()
            flush()
            continue
        if not stripped:
            if not raw.strip() or index == start:
                flush()  # a truly blank line ends the paragraph; a comment line does not
            continue
        if index != start and HEADING.search(stripped):
            flush()
            offset, rest = _after_heading(code)
            if rest.strip():
                block.append((rest.strip(), path, number, index, offset + len(rest) - len(rest.lstrip())))
            continue
        if SEPARATOR.fullmatch(stripped):
            flush()
            continue
        block.append((stripped, path, number, index, offset + len(code) - len(code.lstrip())))
    flush()
    return out


def floats(lines, start, end):
    """Float environments of a section as (begin index, end index, end column)."""
    found, index = [], start
    while index < end:
        code = strip_comments(lines[index][0])
        match = BEGIN.search(code)
        name = match.group(1).strip() if match else None
        if name in FLOAT_ENVS:
            closing = re.compile(r"\\end\s*\{" + re.escape(name) + r"\}")
            last = index
            while last < len(lines) and not closing.search(strip_comments(lines[last][0])):
                last += 1
            if last < len(lines):
                found.append((index, last, max(m.start() for m in closing.finditer(lines[last][0]))))
            index = last + 1
            continue
        index += 1
    return found


def tokens(text):
    return WORD.findall(text)


def _weight(items):
    return sum(0.5 if CJK.fullmatch(t) else 1 for t in items)


def change(old, new):
    """Return (changed fraction, weight of new prose). CJK characters weigh half a word."""
    a, b = tokens(old), tokens(new)
    if not a:
        return 1.0, _weight(b)
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    kept = sum(block.size for block in matcher.get_matching_blocks())
    added = [t for tag, _, _, j1, j2 in matcher.get_opcodes() if tag in ("replace", "insert") for t in b[j1:j2]]
    return 1 - kept / max(len(a), len(b)), _weight(added)


def is_whole_paragraph(old, new):
    """A paragraph that is new or more than half rewritten, ignoring very short additions."""
    ratio, added = change(old or "", new)
    return ratio > 0.5 and added >= 20


PAR_MARK, FLOAT_MARK = "paperroom-par-", "paperroom-sfloat-"


def marked_source(lines, start, end):
    """Expanded LaTeX with invisible markers: the section's start and end, the start
    of each paragraph (to prove it printed) and each float (which may be deferred)."""
    out = [raw for raw, _, _ in lines]
    inserts = []
    heading = strip_comments(out[start])
    match = HEADING.search(heading)
    if match:
        close = match.end() + len(_heading_title(heading, match.end())) + 1
    else:  # the abstract environment
        close = re.search(r"\\begin\s*\{abstract\}", heading).end()
    inserts.append((start, close, _mark(START_MARK)))
    for number, item in enumerate(paragraphs(lines, start, end)):
        col = item["col"]
        lead = re.match(r"\\item\b\s*(\[[^\]]*\])?", out[item["index"]][col:])
        if lead:  # inside a list the marker goes after \item, never before the first one
            col += lead.end()
        inserts.append((item["index"], col, _mark(PAR_MARK + str(number))))
    for number, (_, last, col) in enumerate(floats(lines, start, end)):
        inserts.append((last, col, _mark(FLOAT_MARK + str(number))))
    last = end - 1
    while last > start and (not strip_comments(out[last]).strip()
                            or SEPARATOR.fullmatch(strip_comments(out[last]).strip())):
        last -= 1
    for index, col, text in sorted(inserts, key=lambda i: (i[0], i[1]), reverse=True):
        out[index] = out[index][:col] + text + out[index][col:]
    if last > start:
        out[last] = strip_comments(out[last]).rstrip() + _mark(END_MARK)
    else:
        out[start] += _mark(END_MARK)
    return "\n".join(out) + "\n"


def marks(aux_text):
    """{marker: physical page} from the .aux comments written by _mark."""
    return {name: int(page) for name, page in re.findall(r"^%(paperroom-[\w-]+) (\d+)\s*$", aux_text, re.M)}


def marked_pages(aux_text):
    """Physical page range between the markers from a LaTeX .aux file."""
    pages = {}
    for name in (START_MARK, END_MARK):
        found = re.findall(r"^%" + re.escape(name) + r" (\d+)\s*$", aux_text, re.M)
        if found:
            pages[name] = found[-1]
    return pages.get(START_MARK), pages.get(END_MARK)


class Section:
    """A section's location in the manuscript source."""
    def __init__(self, project, main, start, end, lines):
        self.project, self.main, self.start, self.end, self.lines = project, main, start, end, lines

    @property
    def paragraphs(self):
        return paragraphs(self.lines, self.start, self.end)

    @property
    def heading(self):
        _, path, number = self.lines[self.start]
        return path, number

    def where(self, item=None):
        path, number = (item["file"], item["line"]) if item else self.heading
        return f"{Path(path).relative_to(self.project).as_posix()}:{number}"

    def source(self):
        return "\n".join(raw for raw, _, _ in self.lines) + "\n"

    def marked(self):
        return marked_source(self.lines, self.start, self.end)

    def pages_for(self, located):
        """Physical pages the author must see: heading to last line, plus pages where
        the section's floats landed. Every paragraph must have printed."""
        first, last = located.get(START_MARK), located.get(END_MARK)
        if not (first and last and first <= last):
            raise SourceError("无法确定本节所在页码，请检查本节是否被条件编译或 \\includeonly 排除。")
        found = self.paragraphs
        missing = [n for n in range(len(found)) if PAR_MARK + str(n) not in located]
        if missing:
            spots = "、".join(f"第 {n + 1} 段（{self.where(found[n])}）" for n in missing)
            raise SourceError(f"{spots}没有出现在编译结果中，可能被 \\if 条件、注释环境或 \\includeonly 排除。"
                              "请删除不会排版的段落，或改为确定会排版的写法后重试。")
        pages = set(range(first, last + 1))
        pages |= {page for name, page in located.items() if name.startswith(FLOAT_MARK)}
        return sorted(pages)


def section(project, title, binding=None, files=None):
    """Find a section by its stored binding or title. None when the project has no LaTeX."""
    binding = binding or {}
    main = find_main(project, binding.get("main"), files)
    if main is None:
        return None
    lines = expand(project, main, files)
    start, end = locate(lines, title=title, label=binding.get("label"))
    return Section(_root(project), main, start, end, lines)
