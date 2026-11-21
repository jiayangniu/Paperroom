#!/usr/bin/env python3
"""Open a paper's lasting writing workspace in the browser, without the AI.

Usage: open_workspace.py [--no-browser] [paper folder]. Without a folder, the managed papers opened before are
offered, most recent first. Run through ~/.local/share/paperroom/Open-Paperroom.command.
"""
import argparse
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import activation  # noqa: E402
import room  # noqa: E402
from paperroom_mcp import VERSION  # noqa: E402


def recent():
    found = []
    for record in sorted(room.state_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            project = Path(json.loads(record.read_text("utf-8"))["project"])
            if project.is_dir() and activation.is_managed(project) and project not in found:
                found.append(project)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            continue
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
    typed = input("打开第几篇？请输入上面的编号：").strip()
    return papers[int(typed) - 1] if typed.isdigit() and 1 <= int(typed) <= len(papers) else None


def main(argv):
    parser = argparse.ArgumentParser(description="重新打开已由 Paperroom 管理的论文")
    parser.add_argument("project", type=Path, nargs="?")
    parser.add_argument("--no-browser", action="store_true", help="仅输出本机工作区链接")
    args = parser.parse_args(argv)
    project = args.project.expanduser() if args.project else choose()
    if project is None or not project.is_dir():
        print("没有找到这个论文文件夹。")
        return 1
    project = project.resolve()
    if not activation.is_managed(project):
        print(f"这篇论文尚未启用 Paperroom。请在聊天中说「用 Paperroom 管理这篇论文」，并指定目录 {project}。")
        return 1
    url = room.workspace_url(project, room.ensure(project, VERSION))
    print(f"Paperroom {VERSION} · {project}\n{url}\n写作间在后台运行，可以关掉这个窗口。")
    if not args.no_browser:
        try:
            webbrowser.open(url, new=2)
        except (OSError, webbrowser.Error):
            print("请在这台电脑的浏览器中打开上面的链接。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
