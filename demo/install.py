"""Install the demo into an existing paper directory, retaining project instructions."""
import argparse
import filecmp
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = ("AGENTS.md", "paperroom.py", "room_server.py", "room.html", "render_pdf.js", ".gitignore", "LICENSE")
LINKS = {"AGENTS.md": "For academic manuscript work, read and follow paperroom_tool/AGENTS.md.",
         "CLAUDE.md": "@paperroom_tool/AGENTS.md"}


def install(target):
    if not target.is_dir():
        raise ValueError("请指定已存在的论文项目目录。")
    tool = target / "paperroom_tool"
    if tool.exists() and not all((tool / n).is_file() and filecmp.cmp(HERE / n, tool / n, shallow=False) for n in FILES):
        raise ValueError("paperroom_tool 中已有其他版本或同名内容。请选择空目录或手动合并。")
    content = {n: (target / n).read_text("utf-8") if (target / n).exists() else "" for n in LINKS}
    if not tool.exists():
        with tempfile.TemporaryDirectory(dir=target) as tmp:
            stage = Path(tmp) / "paperroom_tool"
            stage.mkdir()
            for name in FILES:
                shutil.copy2(HERE / name, stage / name)
            stage.rename(tool)
    for name, line in LINKS.items():
        if line not in content[name].splitlines():
            with (target / name).open("a", encoding="utf-8") as out:
                out.write(("\n\n" if content[name] else "") + line + "\n")
    notes = target / "paperroom-notes.md"
    if not notes.exists():
        shutil.copyfile(HERE / "project.md", notes)
    print("已接入项目。请从论文目录运行 python3 paperroom_tool/paperroom.py serve，并开启新的 AI 会话。")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project", type=Path)
    try:
        install(p.parse_args().project.resolve())
    except (OSError, ValueError) as exc:
        p.exit(1, f"Paperroom · {exc}\n")
