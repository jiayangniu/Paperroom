#!/usr/bin/env python3
"""Open the real v2 author workspace with a synthetic, review-ready paper."""
import argparse
import secrets
import shutil
import sqlite3
import sys
import tempfile
import webbrowser
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins/paperroom/runtime"))
import outline
import paperroom
import section_review
import workspace_server


def seed(project):
    assets = project / "examples"
    assets.mkdir()
    for filename in ("evidence.csv", "intro.tex", "intro.pdf"):
        shutil.copyfile(ROOT / "demo/examples" / filename, assets / filename)

    source = (assets / "intro.tex").read_text(encoding="utf-8")
    body = source.split(r"\section*{Introduction}", 1)[1].split(r"\end{document}", 1)[0]
    paragraphs = [text.strip() for text in body.strip().split("\n\n")]
    plans = [
        ("说明解质量与计算成本回答不同的问题。",
         ["先指出固定预算下需要同时报告解质量和精确评估次数。", "再说明最终误差更小无法单独证明更早达到阈值。"]),
        ("提出筛选候选能否节省精确评估的研究问题，并限定证据的范围。",
         ["问筛选能否减少达到同一目标所需的精确评估次数。", "交代三组配对运行中观察到的方向。",
          "最后说明下一步需要在统一停止规则下做更大的比较。"]),
    ]
    if len(paragraphs) != len(plans):
        raise ValueError("教学节选与示例逐句大纲的段数不一致。")
    with closing(paperroom.connect(workspace_server.database_path(project))) as db:
        state = outline.update_assets(
            db, project, 0,
            "在相同目标阈值下，筛选候选能否减少所需的精确评估次数？",
            "虚构教学数据，见 examples/evidence.csv。三次配对运行中，基线分别使用 100、104、97 次精确评估，"
            "筛选方法分别使用 76、83、78 次，六次运行均达到目标。"
        )
        state = outline.submit(db, project, state["version"], "paper", [
            {"title": "Introduction", "purpose": "提出计算成本问题，说明比较条件和证据边界。"},
            {"title": "Results", "purpose": "展示三组配对运行，并讨论数据支持的结论。"},
        ])
        intro = state["sections"][0]["id"]
        state = outline.submit(db, project, state["version"], "section",
                               [{"purpose": purpose} for purpose, _ in plans], section=intro)
        for item, (_, sentences), text in zip(state["sections"][0]["paragraphs"], plans, paragraphs):
            paragraph = item["id"]
            state = outline.submit(db, project, state["version"], "paragraph", sentences,
                                   section=intro, paragraph=paragraph)
            plan = outline.require_paragraph(db, project, intro, paragraph)
            section_review.save_paragraph_draft(db, project, intro, paragraph, plan["revision"], text)
        section_review.publish_section(db, project, intro, tex="examples/intro.tex",
                                       pdf="examples/intro.pdf", minimum=2)
    return intro


def prepare(project):
    """Build and render in staging before putting any example files into the chosen folder."""
    if project.is_symlink():
        raise ValueError("请选择普通空文件夹。")
    project.mkdir(parents=True, exist_ok=True)
    if not project.is_dir() or any(project.iterdir()):
        raise ValueError("示例需要空文件夹，请选择一个新的目录。")
    with tempfile.TemporaryDirectory(prefix=".paperroom-prepare-", dir=project) as directory:
        staging = Path(directory)
        section = seed(staging)
        if any(entry != staging for entry in project.iterdir()):
            raise ValueError("准备期间有其他文件写入。请选用新的空文件夹。")
        for entry in staging.iterdir():
            entry.rename(project / entry.name)
    return section


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", type=Path, metavar="EMPTY_DIR",
                        help="在指定空目录生成示例后退出")
    parser.add_argument("--port", type=int, default=0, help="监听端口，默认使用空闲端口")
    parser.add_argument("--no-browser", action="store_true", help="仅输出浏览器地址")
    args = parser.parse_args()
    project = (args.prepare_only.expanduser().absolute() if args.prepare_only is not None
               else Path(tempfile.mkdtemp(prefix="Paperroom-demo-")))
    section = prepare(project)
    print(f"示例论文目录 · {project}", flush=True)
    if args.prepare_only is not None:
        print(f"Introduction · {section}", flush=True)
        return
    handler = workspace_server.handler_for(workspace_server.database_path(project),
                                           secrets.token_urlsafe(32), project)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        query = urlencode({"view": "review", "section": section})
        url = f"http://127.0.0.1:{server.server_port}/workspace?{query}"
        print(f"Paperroom · {url}\n按 Control-C 关闭演示服务。", flush=True)
        if not args.no_browser:
            webbrowser.open(url, new=2)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, sqlite3.Error) as exc:
        sys.exit(f"Paperroom · {exc}")
