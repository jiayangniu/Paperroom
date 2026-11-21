#!/usr/bin/env python3
"""Open a paper's lasting writing workspace in the browser, without the AI.

Usage: open_workspace.py [paper folder]. Without a folder, the papers opened before are
offered, most recent first. Run through ~/.local/share/paperroom/Open-Paperroom.command.
"""
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import room  # noqa: E402
from paperroom_mcp import VERSION  # noqa: E402


def recent():
    found = []
    for record in sorted(room.state_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            project = Path(json.loads(record.read_text("utf-8"))["project"])
        except (OSError, ValueError, KeyError):
            continue
        if project.is_dir() and project not in found:
            found.append(project)
    return found


def choose():
    papers = recent()
    if not papers:
        print("还没有打开过论文。请把论文文件夹拖到这个窗口里再回车，或在论文文件夹里运行本命令。")
        typed = input("论文文件夹：").strip().strip("'\"")
        return Path(typed).expanduser() if typed else None
    if len(papers) == 1:
        return papers[0]
    for number, project in enumerate(papers, 1):
        print(f"{number}. {project.name}  ({project})")
    typed = input("打开第几篇？直接回车打开第 1 篇：").strip()
    if not typed:
        return papers[0]
    return papers[int(typed) - 1] if typed.isdigit() and 1 <= int(typed) <= len(papers) else None


def main(argv):
    project = Path(argv[0]).expanduser() if argv else choose()
    if project is None or not project.is_dir():
        print("没有找到这个论文文件夹。")
        return 1
    project = project.resolve()
    url = f"http://127.0.0.1:{room.ensure(project, VERSION)}/workspace"
    print(f"Paperroom {VERSION} · {project.name}\n{url}\n写作间在后台运行，可以关掉这个窗口。")
    webbrowser.open(url, new=2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
