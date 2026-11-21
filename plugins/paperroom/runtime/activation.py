"""Project enrollment travels with the manuscript. Chat selections stay on this machine."""
import hashlib
import os
import tempfile
from pathlib import Path

import launcher
from workspace_server import database_path


NOT_MANAGED = "此目录没有 Paperroom 写作间。只有作者明确要求用 Paperroom 管理这篇论文时，才可调用 activate_project。"
NOT_SELECTED = "当前对话尚未选择这篇论文的 Paperroom 写作间。请等作者明确要求打开或使用 Paperroom。"


def is_managed(project):
    db = database_path(project)
    marker = db.parent / "managed"
    return db.is_file() or (not marker.is_symlink() and marker.is_file())


def enable(project):
    """Only an explicit enrollment creates project state. Old databases qualify in place."""
    db = database_path(project)
    if not is_managed(project):
        db.parent.mkdir(parents=True, exist_ok=True)
        marker = db.parent / "managed"
        try:
            # Exclusive creation makes simultaneous enrollment idempotent.
            marker.touch(mode=0o600, exist_ok=False)
        except FileExistsError:
            if marker.is_symlink() or not marker.is_file():
                raise ValueError("Invalid Paperroom project marker.")


def _session_file(session_id):
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    key = hashlib.sha256(session_id.encode()).hexdigest()
    return launcher.home() / "sessions" / key


def session_project(session_id):
    path = _session_file(session_id)
    if path is not None:
        try:
            root = Path(path.read_text(encoding="utf-8"))
            if root.is_absolute() and root.is_dir() and is_managed(root):
                return root
        except (OSError, ValueError, RuntimeError):
            pass
    return None


def bind_session(session_id, project):
    path = _session_file(session_id)
    if path is None:
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False)
    staged = Path(handle.name)
    try:
        with handle:
            handle.write(str(Path(project).resolve()))
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def end_session(session_id):
    path = _session_file(session_id)
    if path is not None:
        path.unlink(missing_ok=True)
