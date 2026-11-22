#!/usr/bin/env python3
"""Paperroom: local author checkpoints shared by terminal writing assistants."""
import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

import latex_source

HERE = Path(__file__).resolve().parent
DATA = HERE / ".paperroom" / "project.sqlite3"


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    # Empty the journal instead of deleting it after each write, so sandboxes that
    # forbid deleting files (e.g. Cowork) don't ask for permission on every save.
    db.execute("PRAGMA journal_mode=TRUNCATE")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS artifacts (
            task TEXT, revision INTEGER, page INTEGER, content BLOB NOT NULL,
            PRIMARY KEY(task, revision, page)
        );
    """)
    return db


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(db, task):
    row = db.execute("SELECT body FROM tasks WHERE id=?", (task,)).fetchone()
    if not row:
        raise ValueError("找不到这个写作任务。")
    return json.loads(row[0])


def start(db, title, reference, count, minimum, single):
    if not title.strip() or count < 1 or minimum < 1 or (single and count != 1):
        raise ValueError("请提供范围名称、正确的段落数和审稿条数。局部改写只处理一段。")
    job = dict(id=secrets.token_hex(6), title=title.strip(), reference=reference,
               outline_reference=reference if not single else "", count=count, minimum=minimum,
               phase="paragraph" if single else "outline", version=1, outline="",
               paragraphs=[], drafts=[], created=now())
    with db:
        db.execute("INSERT INTO tasks VALUES (?,?)", (job["id"], json.dumps(job)))
    return job


def edit(db, task, update):
    with db:
        db.execute("BEGIN IMMEDIATE")
        job = get(db, task)
        update(job)
        job["version"] += 1
        db.execute("UPDATE tasks SET body=? WHERE id=?", (json.dumps(job), task))
    return job


def check(job, version, phases):
    if version != job["version"] or job["phase"] not in phases:
        raise ValueError("这个阶段已经发生变化。请刷新页面或重新查看 status。")


def clean_notes(items):
    if not isinstance(items, list) or any(not isinstance(x, str) for x in items):
        raise ValueError("请输入文字。")
    return [x.strip() for x in items if x.strip()]


def respond(db, task, version, items):
    """Author-facing form entry. The agent CLI has no equivalent command."""
    answers = clean_notes(items)
    def update(job):
        check(job, version, ("outline", "paragraph", "review"))
        if job["phase"] == "review":
            unique = {" ".join(x.casefold().split()) for x in answers}
            if len(unique) != len(answers) or len(unique) < job["minimum"]:
                raise ValueError(f"请写至少 {job['minimum']} 条各不相同的审稿想法。")
            job["drafts"][-1].update(notes=answers, reviewed=now())
            job["phase"] = "reviewed"
        else:
            if len(answers) != 1:
                raise ValueError("请先用自己的话写下本阶段的思路。")
            if job["phase"] == "outline":
                job["outline"] = answers[0]
            else:
                job["paragraphs"].append(dict(reference=job["reference"], author=answers[0]))
            job["phase"] = "ready" if len(job["paragraphs"]) == job["count"] else "discussion"
        job["reference"] = ""
    return edit(db, task, update)


def plan(db, task, reference, version=None):
    def update(job):
        check(job, job["version"] if version is None else version, ("discussion",))
        if not reference.strip():
            raise ValueError("请提供刚刚讨论的句子安排。")
        job.update(phase="paragraph", reference=reference)
    return edit(db, task, update)


def publish(db, task, version, source, images):
    def update(job):
        check(job, version, ("ready", "reviewed"))
        if not source or not images:
            raise ValueError("当前版本缺少 LaTeX 或审阅图片。")
        revision = len(job["drafts"]) + 1
        blobs = [source, *images]
        db.executemany("INSERT INTO artifacts VALUES (?,?,?,?)",
                       ((task, revision, page, blob) for page, blob in enumerate(blobs)))
        job["drafts"].append(dict(revision=revision, pages=len(images), created=now(),
                                  source_sha256=hashlib.sha256(source).hexdigest(), notes=[]))
        job["phase"] = "review"
    return edit(db, task, update)


def run_program(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=240, text=True, errors="replace")
    if result.returncode:
        raise ValueError(result.stdout[-2500:] or f"{args[0]} 运行失败。")


def page_numbers(spec):
    if spec == "all":
        return None
    out = []
    for item in spec.split(","):
        bounds = item.split("-")
        if len(bounds) > 2 or not all(n.isdigit() and int(n) > 0 for n in bounds):
            raise ValueError("页码格式示例：1,3-5")
        lo, hi = int(bounds[0]), int(bounds[-1])
        if hi < lo or hi - lo > 1000:
            raise ValueError("请检查页码范围。")
        out.extend(range(lo, hi + 1))
    return list(dict.fromkeys(out))


MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_DOCUMENT_PAGES = 100


# Apps started from the Dock or Finder often lack the folders MacTeX and Homebrew add to PATH.
TEX_FOLDERS = ("/Library/TeX/texbin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/texbin")
BUNDLED_TECTONIC = ("/Applications/ChatGPT.app/Contents/Resources/tectonic/bin/tectonic",
                    "/Applications/ChatGPT.app/Contents/Resources/tectonic/tectonic",
                    "/Applications/Codex.app/Contents/Resources/tectonic/bin/tectonic")
NO_TEX = ("没有找到 LaTeX 编译器（pdfLaTeX 或 Tectonic）。请在这台电脑上安装 MacTeX、BasicTeX，"
          "或运行 brew install tectonic，然后重新打开客户端。")


def tex_tool(name):
    """A TeX program on PATH or in the usual install folders, or None."""
    found = shutil.which(name)
    if found:
        return found
    for folder in TEX_FOLDERS:
        path = Path(folder) / name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def tectonic_path():
    found = tex_tool("tectonic")
    if found:
        return found
    named = os.environ.get("CODEX_TECTONIC_PATH")
    for candidate in ([named] if named else []) + list(BUNDLED_TECTONIC):
        path = Path(candidate)
        if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def tex_available():
    return bool(tex_tool("pdflatex") or tectonic_path())


def compile_tex(tex, folder, sources):
    """Compile tex into folder, keeping the .aux. sources is the folder whose subfolders
    \\include may write into (the paper's own folder)."""
    folder = Path(folder)
    pdflatex, tectonic = tex_tool("pdflatex"), tectonic_path()
    if pdflatex:
        # \\include writes each part's .aux beside it inside -output-directory,
        # so multi-file papers need their source folders mirrored there.
        for index, sub in enumerate(p for p in Path(sources).rglob("*") if p.is_dir()):
            if index >= 500:
                break
            relative = sub.relative_to(sources)
            if not any(part.startswith(".") for part in relative.parts):
                (folder / relative).mkdir(parents=True, exist_ok=True)

        def latex():
            run_program([pdflatex, "-no-shell-escape", "-halt-on-error", "-interaction=nonstopmode",
                         f"-output-directory={folder}", tex.name], cwd=tex.parent)
        latex()
        bibliography(tex, folder, sources)
        latex()
        latex()
    elif tectonic:
        args = [tectonic, "--untrusted", "--keep-intermediates", "-o", str(folder)]
        if os.environ.get("PAPERROOM_TEX_OFFLINE") == "1":
            args.append("--only-cached")
        run_program([*args, str(tex)], cwd=tex.parent)
    else:
        raise ValueError(NO_TEX)
    return folder / tex.with_suffix(".pdf").name


def bibliography(tex, folder, sources):
    """Run BibTeX between pdfLaTeX passes when the paper cites a .bib and no .bbl of the
    same job name is already beside it. The .bbl lands in the output folder, which
    pdfLaTeX also reads from. BibTeX warnings never stop the build."""
    aux = Path(folder) / (tex.stem + ".aux")
    if not aux.is_file() or "\\bibdata" not in aux.read_text("utf-8", errors="replace"):
        return
    bibtex = tex_tool("bibtex")
    if (tex.parent / (tex.stem + ".bbl")).exists() or not bibtex:
        return
    paths = os.pathsep.join([str(tex.parent), str(Path(sources).resolve()), ""])
    subprocess.run([bibtex, tex.stem], cwd=folder, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=120, env={**os.environ, "BIBINPUTS": paths, "BSTINPUTS": paths})


@contextmanager
def marked_build(main, source):
    """Compile a marked copy of the paper beside its files (as links in a temporary folder,
    never in the project). The copy keeps the paper's own file name: the job name then
    matches an existing .bbl, and no file starts with a dot, which TeX's default
    openout_any=p refuses to write. Yields (pdf path, .aux text)."""
    with tempfile.TemporaryDirectory() as folder:
        farm, out = Path(folder) / "paper", Path(folder) / "out"
        farm.mkdir(); out.mkdir()
        for entry in main.parent.iterdir():
            if not entry.name.startswith(".") and entry.name != main.name:
                (farm / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
        marked = farm / main.name
        marked.write_text(source, encoding="utf-8")
        pdf = compile_tex(marked, out, main.parent)
        aux = out / (marked.stem + ".aux")
        yield pdf, aux.read_text("utf-8", errors="replace") if aux.is_file() else ""


class CompiledLocations(dict):
    """Physical marker pages and label numbers read from the same compiler run."""
    def __init__(self, aux):
        super().__init__(latex_source.marks(aux))
        self.label_numbers = dict(re.findall(r"\\newlabel\{([^{}]+)\}\{\{([^{}]*)\}", aux))


def render_marked(main, source, select):
    """Compile marked LaTeX beside the paper's files (as links in a temporary folder,
    never in the project). select maps {marker: physical page} to the pages to keep.
    Returns (excerpt pdf, page images, kept pages, {marker: physical page})."""
    with marked_build(main, source) as (pdf, aux):
        located = CompiledLocations(aux)
        pages = select(located)
        if not pages:
            return None, [], [], located
        captured, images = _render(None, pdf, ",".join(map(str, pages)), capture=True)
        return captured, images, pages, located


def render_section(section):
    """Capture only the physical pages from a section's heading to its last line."""
    captured, images, pages, _ = render_marked(section.main, section.marked(), section.pages_for)
    runs, start = [], pages[0]
    for previous, page in zip(pages, pages[1:] + [None]):
        if page != previous + 1:
            runs.append(str(start) if start == previous else f"{start}-{previous}")
            start = page
    return captured, images, ",".join(runs)


def render(tex, pdf, pages):
    return _render(tex, pdf, pages, capture=False)[1]


def render_document(tex, pdf, pages):
    """Capture a PDF excerpt and rasterize the very same pages in the same order."""
    return _render(tex, pdf, pages, capture=True)


def _render(tex, pdf, pages, capture):
    if tex is not None:
        tex = tex.resolve(strict=True)
    if not isinstance(pages, str) or len(pages) > 512:
        raise ValueError("请核对节选页码。")
    selected = page_numbers(pages)
    if capture and selected and len(selected) > MAX_DOCUMENT_PAGES:
        raise ValueError("一次最多保存 100 页节选。")
    with tempfile.TemporaryDirectory() as folder:
        directory = Path(folder)
        snapshot_folder = directory / "frozen"
        if capture:
            snapshot_folder.mkdir()
        if pdf:
            pdf = pdf.resolve(strict=True)
            if capture:
                # The paper's TeX build can rewrite its PDF at any time. Both the
                # downloaded vector document and its PNGs must use identical bytes.
                with pdf.open("rb") as stream:
                    before = os.fstat(stream.fileno())
                    if not 0 < before.st_size <= MAX_DOCUMENT_BYTES:
                        raise ValueError("PDF 须大于零且不超过 32 MiB。")
                    content = stream.read(MAX_DOCUMENT_BYTES + 1)
                    after = os.fstat(stream.fileno())
                    if len(content) != before.st_size or before.st_mtime_ns != after.st_mtime_ns:
                        raise ValueError("读取时 PDF 已更新，请重新选择文件。")
                pdf = snapshot_folder / "input.pdf"
                pdf.write_bytes(content)
                del content
        else:
            pdf = compile_tex(tex, directory, tex.parent)
        if capture and (pdf.stat().st_size > MAX_DOCUMENT_BYTES or not pdf.stat().st_size):
            raise ValueError("PDF 须大于零且不超过 32 MiB。")
        captured = pdf
        if capture and selected:
            captured = snapshot_folder / "selected-pages.pdf"
        poppler = shutil.which("pdftoppm") and (not capture or
                   (shutil.which("pdfinfo") and (not selected or
                    (shutil.which("pdfseparate") and shutil.which("pdfunite")))))
        if poppler:
            scale = ["-scale-to", "2400"] if capture else []
            if capture:
                info = subprocess.run(["pdfinfo", str(pdf)], text=True, errors="replace", capture_output=True,
                                      timeout=30, env={**os.environ, "LC_ALL": "C"})
                total = next((int(line.split(":")[1].strip()) for line in info.stdout.splitlines()
                              if line.startswith("Pages:")), 0)
                if not total or (selected and max(selected) > total):
                    raise ValueError("无法读取 PDF 或节选页码超出范围。")
                if not selected and total > MAX_DOCUMENT_PAGES:
                    raise ValueError("请指定本节页码，一次最多保存 100 页。")
                if selected:
                    parts = []
                    for n in selected:
                        run_program(["pdfseparate", "-f", str(n), "-l", str(n), str(pdf),
                                     str(directory / "part-%d.pdf")])
                        parts.append(str(directory / f"part-{n}.pdf"))
                    run_program(["pdfunite", *parts, str(captured)])
            if selected:
                for idx, n in enumerate(selected, 1):
                    run_program(["pdftoppm", "-cropbox", "-png", "-r", "144", *scale, "-f", str(n), "-l", str(n),
                                 "-singlefile", str(pdf), str(directory / f"page-{idx}")])
            else:
                run_program(["pdftoppm", "-cropbox", "-png", "-r", "144", *scale, str(pdf), str(directory / "page")])
        elif sys.platform == "darwin" and shutil.which("osascript"):
            run_program(["osascript", "-l", "JavaScript", str(HERE / "render_pdf.js"), str(pdf), folder,
                         ",".join(map(str, selected)) if selected else "all", str(MAX_DOCUMENT_PAGES if capture else 0),
                         str(captured) if capture and selected else ""])
        else:
            raise ValueError("生成节选图片需要 Poppler 的 pdftoppm，macOS 使用系统自带 PDFKit。")
        files = sorted(directory.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        if not files or (selected and len(files) != len(selected)):
            raise ValueError("没有生成指定的页面，请核对 PDF 页码。")
        if capture and (captured.stat().st_size > MAX_DOCUMENT_BYTES or
                        sum(path.stat().st_size for path in files) > 128 * 1024 * 1024):
            raise ValueError("节选文件过大，请缩小页码范围。")
        return captured.read_bytes() if capture else None, [p.read_bytes() for p in files]


def args_for_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    cmd = parser.add_subparsers(dest="action", required=True)
    serve = cmd.add_parser("serve", help="打开本机作者界面")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-open", action="store_true")
    status = cmd.add_parser("status", help="列出任务，或查看某个任务的作者原话及版本")
    status.add_argument("id", nargs="?")
    start_cmd = cmd.add_parser("start", help="作者明确要求写作后，建立任务")
    start_cmd.add_argument("title")
    start_cmd.add_argument("--ref", required=True, type=Path, help="刚讨论过的参考材料，UTF-8 文本路径")
    start_cmd.add_argument("--paragraphs", type=int, default=1)
    start_cmd.add_argument("--min-notes", type=int, default=3)
    start_cmd.add_argument("--single", action="store_true", help="只改一段，直接进入句子安排")
    for name in ("plan", "publish"):
        sub = cmd.add_parser(name, help="提交段落讨论参考" if name == "plan" else "编译并提交当前稿件供审阅")
        sub.add_argument("id")
        sub.add_argument("--at", type=int, required=True, help="status 打印的当前 version")
        if name == "plan":
            sub.add_argument("--ref", required=True, type=Path)
        else:
            sub.add_argument("--tex", required=True, type=Path, help="可独立编译的 .tex，或与外部 PDF 配对的源文件")
            sub.add_argument("--pdf", type=Path, help="由当前源文件编译的 PDF，可来自 Overleaf")
            sub.add_argument("--pages", default="all", help="all 或如 1,3-4")
    return parser.parse_args()


def main():
    arg = args_for_cli()
    db_path = Path(os.environ.get("PAPERROOM_DB", DATA))
    if arg.action == "serve":
        from room_server import serve
        serve(db_path, arg.port, not arg.no_open)
        return
    with closing(connect(db_path)) as db:
        if arg.action == "status":
            if arg.id:
                result = get(db, arg.id)
            else:
                result = [dict(id=j["id"], title=j["title"], phase=j["phase"], version=j["version"])
                          for (body,) in db.execute("SELECT body FROM tasks ORDER BY rowid DESC")
                          for j in [json.loads(body)]]
        elif arg.action == "start":
            result = start(db, arg.title, arg.ref.read_text("utf-8"), arg.paragraphs, arg.min_notes, arg.single)
        elif arg.action == "plan":
            result = plan(db, arg.id, arg.ref.read_text("utf-8"), arg.at)
        elif arg.action == "publish":
            check(get(db, arg.id), arg.at, ("ready", "reviewed"))
            source = arg.tex.read_bytes()
            images = render(arg.tex, arg.pdf, arg.pages)
            if source != arg.tex.read_bytes():
                raise ValueError("编译期间源文件已修改。请重新发布。")
            result = publish(db, arg.id, arg.at, source, images)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
        sys.exit(f"Paperroom · {exc}")
