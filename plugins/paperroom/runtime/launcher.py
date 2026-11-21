"""A fixed way to open the writing workspace that needs neither the AI nor a known install path.

Every time a Paperroom server starts (Claude Chat, Claude Code or Codex launch it even when the
client later blocks its tool calls), it refreshes Open-Paperroom.command in the user's Paperroom
folder so that it runs the newest installed Paperroom. Double-clicking it, or running it with a
paper's folder, starts or reuses that paper's lasting workspace and opens it in the browser.
A script inside a paper's folder only needs to call this one file.
"""
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "Open-Paperroom.command"


def home():
    base = os.environ.get("PAPERROOM_STATE_DIR") or str(Path.home() / ".local/share/paperroom")
    return Path(base).expanduser()


def _version_key(version):
    return tuple(int(part) for part in re.findall(r"\d+", str(version or "")))


def _atomic_write(path, text, mode):
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as tmp:
        staged = Path(tmp.name)
        try:
            tmp.write(text)
            tmp.flush()
            os.chmod(staged, mode)
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)


def refresh(version, runtime=HERE, python=None):
    """Point the launcher at this runtime unless a newer installed one already owns it."""
    folder = home()
    folder.mkdir(parents=True, exist_ok=True)
    record = folder / "launcher.json"
    try:
        current = json.loads(record.read_text("utf-8"))
    except (OSError, ValueError):
        current = {}
    newer_elsewhere = (current.get("runtime") != str(runtime)
                       and Path(current.get("runtime", ""), "open_workspace.py").is_file()
                       and _version_key(current.get("version")) > _version_key(version))
    if newer_elsewhere:
        return folder / NAME
    python = python or sys.executable
    script = ("#!/bin/sh\n"
              "# Paperroom: open the writing workspace. Refreshed each time Paperroom starts;\n"
              "# give a paper's folder, or run it without one to pick a recent paper.\n"
              f"exec {_quote(python)} {_quote(str(Path(runtime) / 'open_workspace.py'))} \"$@\"\n")
    _atomic_write(folder / NAME, script, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    _atomic_write(record, json.dumps({"version": str(version), "runtime": str(runtime), "python": python}),
                  stat.S_IRUSR | stat.S_IWUSR)
    return folder / NAME


def _quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def project_script():
    """What a paper's own double-click script needs to contain."""
    return ("#!/bin/sh\n"
            "# Paperroom: open this paper's writing workspace (works across updates).\n"
            "OPEN=\"$HOME/.local/share/paperroom/Open-Paperroom.command\"\n"
            "if [ ! -x \"$OPEN\" ]; then\n"
            "  echo \"还没有找到 Paperroom 启动器。请把 Paperroom 更新到 0.6.16 或更新的版本，打开一次 Claude 或 Codex 后再双击。\"\n"
            "  exit 1\n"
            "fi\n"
            "exec \"$OPEN\" \"$(cd \"$(dirname \"$0\")\" && pwd)\"\n")
