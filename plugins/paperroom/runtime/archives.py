"""Independent, commit-labelled copies of a manuscript, with a safety copy before restore."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile


SUFFIX = ".paperroom-archives"
MARKER = ".paperroom-archive-store-v1"
STATE_FILE = ".paperroom-archive-state.json"
DATABASES = {Path(".paperroom/project.sqlite3"), Path("paperroom_tool/.paperroom/project.sqlite3")}
SIDECARS = {Path(str(path) + suffix) for path in DATABASES for suffix in ("-wal", "-shm", "-journal")}


class SafetyCopyFailed(ValueError):
    """The outgoing manuscript could not be archived; switching has not begun."""


class StaleGeneration(ValueError):
    pass


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value):
        raise ValueError("Invalid archive ID.")
    return uuid.UUID(value).hex


def _commit(text):
    if not isinstance(text, str) or len(text) > 240 or len(text.splitlines()) > 1:
        raise ValueError("Use a single line of up to 240 characters for the commit.")
    return text.strip()


def _json(path):
    if path.is_symlink():
        raise ValueError("Unexpected symbolic link in the archive store.")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as f:
        tmp = Path(f.name)
        try:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _state_path(project):
    return Path(project) / STATE_FILE


def _state(project):
    try:
        state = _json(_state_path(project))
        if (not isinstance(state, dict) or state.get("format") != 1 or
                any(not isinstance(state[k], str) or not re.fullmatch(r"[0-9a-f]{32}", state[k])
                    for k in ("generation", "pending", "target", "backup") if k in state)):
            raise ValueError("The archive switch record is invalid.")
        return state
    except FileNotFoundError:
        return {}


def generation(project):
    """Read under workspace_lock when the caller will act on the result."""
    return _state(project).get("generation", "")


@contextmanager
def _lock(project, exclusive):
    # Neither a read nor a write to an existing paper requires access to the parent
    # folder or home directory. All local clients must still agree on the same lock.
    if os.name == "posix":
        folder = Path("/tmp") / f"paperroom-archive-locks-{os.getuid()}"
        folder.mkdir(mode=0o700, exist_ok=True)
        info = folder.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("The Paperroom lock directory must belong to the current user.")
    else:
        folder = Path(tempfile.gettempdir()) / "paperroom-archive-locks"
        folder.mkdir(exist_ok=True)
    path = folder / hashlib.sha256(os.fsencode(str(project))).hexdigest()
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield


@contextmanager
def workspace_lock(project):
    """Paperroom activities may run together, but cannot straddle a folder switch."""
    project = Path(project).resolve()
    while True:
        with _lock(project, False):
            if "pending" not in _state(project):
                yield
                return
        with _lock(project, True):
            _recover(project)


def _store(project, create=False):
    if project == project.parent:
        raise ValueError("Choose a manuscript folder before saving an archive.")
    store = project.with_name(project.name + SUFFIX)
    try:
        mode = store.lstat().st_mode
    except FileNotFoundError:
        if create:
            store.mkdir(mode=0o700)
            try:
                (store / MARKER).touch(mode=0o600)
            except OSError:
                store.rmdir()
                raise
        return store
    if (not stat.S_ISDIR(mode) or (store / MARKER).is_symlink() or not (store / MARKER).is_file()):
        raise ValueError("The archive folder name is already in use. Check the folder beside the manuscript.")
    return store


def _entry(store, key):
    p = store / _id(key)
    if p.is_symlink() or not p.is_dir() or (p / "files").is_symlink() or not (p / "files").is_dir():
        raise ValueError("This archive is unavailable.")
    row = _json(p / "commit.json")
    if row["id"] != p.name:
        raise ValueError("The archive record does not match its folder.")
    return row


def _listing(project):
    store = _store(project)
    entries = []
    if store.is_dir():
        entries = [_entry(store, p.name) for p in store.iterdir() if re.fullmatch(r"[0-9a-f]{32}", p.name)]
    return {"archives": sorted(entries, key=lambda row: (row["created"], row["id"]), reverse=True),
            "generation": generation(project)}


def listing(project):
    project = Path(project).resolve()
    with workspace_lock(project):
        return _listing(project)


def _protected(path):
    return path.name == ".git" or (path.name.endswith(SUFFIX) and not path.is_symlink()
                                   and (path / MARKER).is_file())


def _inventory(root):
    """lstat only. No archive, source, or destination symlink is traversed."""
    entries = {}
    def visit(folder):
        for item in folder.iterdir():
            rel = item.relative_to(root)
            if _protected(item) or rel == Path(STATE_FILE):
                continue
            info = item.lstat()
            if rel in SIDECARS and (not item.name.endswith("-wal") or info.st_size == 0):
                continue
            if stat.S_ISDIR(info.st_mode):
                # Reading a WAL database may create transient sidecars. Directory
                # entries below capture real additions/deletions without that noise.
                entries[rel] = (info.st_mode, info.st_ino)
                visit(item)
            else:
                entries[rel] = (info.st_mode, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    visit(root)
    return entries


def _copy_database(src, dest):
    # SQLite supplies one committed view, including committed pages in an open WAL.
    with closing(sqlite3.connect(src.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(dest)) as target:
        source.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")
    shutil.copystat(src, dest)


def _copy_tree(source, destination):
    before = _inventory(source)
    destination.mkdir()
    dirs = []
    for rel, info in before.items():
        if rel in SIDECARS:  # WAL changes participate in validation, not the filesystem copy.
            continue
        src, dest = source / rel, destination / rel
        mode = info[0]
        if stat.S_ISLNK(mode):
            dest.symlink_to(os.readlink(src))
        elif stat.S_ISDIR(mode):
            dest.mkdir()
            dirs.append(rel)
        elif stat.S_ISREG(mode):
            if rel in DATABASES:
                _copy_database(src, dest)
            else:
                shutil.copy2(src, dest)
        else:
            raise ValueError(f"Cannot archive a special file: {rel}")
    if before != _inventory(source):
        raise ValueError("The manuscript changed while copying. Save the archive again.")
    for rel in reversed(dirs):
        shutil.copystat(source / rel, destination / rel)
    return before


def _capture(project, store, key, text, automatic):
    with tempfile.TemporaryDirectory(prefix=".copy-", dir=store) as folder:
        entry = Path(folder) / "entry"
        entry.mkdir()
        inventory = _copy_tree(project, entry / "files")
        metadata = {"id": key, "created": datetime.now(timezone.utc).isoformat(), "commit": text,
                    "automatic": automatic}
        _write_json(entry / "commit.json", metadata)
        os.rename(entry, store / key)
    return inventory


def _verify_generation(state, expected):
    if state.get("generation", "") != expected:
        raise StaleGeneration("The workspace switched to another archive. Reload it before continuing.")


def create(project, commit="", *, request_id, expected_generation):
    project, key, text = Path(project).resolve(), _id(request_id), _commit(commit)
    with _lock(project, True):
        _recover(project)
        _verify_generation(_state(project), expected_generation)
        store = _store(project, True)
        if os.path.lexists(store / key):
            existing = _entry(store, key)
            if existing["commit"] != text or existing["automatic"]:
                raise ValueError("This request ID has already been used.")
        else:
            _capture(project, store, key, text, False)
        return {**_listing(project), "created": key}


def _dir(path):
    return not path.is_symlink() and path.is_dir()


def _contains_protected(folder):
    return any(_protected(child) or (_dir(child) and _contains_protected(child)) for child in folder.iterdir())


def _plan(current, staged):
    """Plan entry renames, retaining shared directory identities and all Git metadata."""
    moves = []
    def visit(rel):
        old, new = current / rel, staged / rel
        old_names = {p.name for p in old.iterdir()} if _dir(old) else set()
        new_names = {p.name for p in new.iterdir()} if _dir(new) else set()
        for name in sorted(old_names | new_names):
            sub = rel / name
            a, b = current / sub, staged / sub
            had, has = name in old_names, name in new_names
            if sub == Path(STATE_FILE) or _protected(a):
                continue
            if had and _dir(a) and has and _dir(b):
                # A read-only directory can still be restored by replacing its
                # entry in a writable parent. Keep Git and nested archive stores in place.
                old_mode, new_mode = stat.S_IMODE(a.stat().st_mode), stat.S_IMODE(b.stat().st_mode)
                if (old_mode != new_mode or not new_mode & stat.S_IWUSR) and not _contains_protected(a):
                    moves.append([str(sub), True, True])
                else:
                    visit(sub)
            elif had and _dir(a) and _contains_protected(a):
                if has:
                    raise ValueError(f"Restoring this entry would replace Git or archive metadata: {sub}")
                visit(sub)
            else:
                moves.append([str(sub), had, has])
    visit(Path())
    return moves


def _checked_path(root, rel):
    path = Path(rel)
    if path.is_absolute() or not path.parts or ".." in path.parts or ".git" in path.parts:
        raise ValueError("Invalid path in the archive switch record.")
    candidate = root / path
    if candidate.parent.resolve() != candidate.parent:
        raise ValueError("A directory in the archive switch record has become a symbolic link.")
    return candidate


def _recover(project):
    """An interrupted switch replays the inverse renames before any further project access."""
    state = _state(project)
    if "pending" not in state:
        return
    stage = _store(project) / (".switch-" + _id(state["pending"]))
    if stage.is_symlink() or not stage.is_dir():
        raise ValueError("The unfinished archive switch folder is unavailable.")
    plan = _json(stage / "moves.json")
    for rel, had, has in reversed(plan):
        live = _checked_path(project, rel)
        old = _checked_path(stage / "old", rel)
        new = _checked_path(stage / "new", rel)
        if has and not os.path.lexists(new):
            os.replace(live, new)
        if had and os.path.lexists(old):
            os.replace(old, live)
    del state["pending"]
    _write_json(_state_path(project), state)
    shutil.rmtree(stage, ignore_errors=True)


def _record_restore_event(project, target_row, backup_id):
    """If the restored manuscript has a Paperroom journal, note the archive resume point."""
    db_path = None
    for rel in (Path("paperroom_tool/.paperroom/project.sqlite3"), Path(".paperroom/project.sqlite3")):
        candidate = project / rel
        if candidate.is_file() and not candidate.is_symlink():
            db_path = candidate
            break
    if db_path is None:
        return
    try:
        import journal
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=rw", uri=True, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_journal'").fetchone():
                return
            resumed_version = None
            resumed_display = None
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_versions'").fetchone():
                row = db.execute("SELECT body FROM v2_versions ORDER BY number DESC LIMIT 1").fetchone()
                if row:
                    latest = json.loads(row[0])
                    resumed_version = latest.get("number")
                    resumed_display = latest.get("display_number")
            journal.append(db, "checkpoint_restored", {
                "archive_id": target_row.get("id", ""),
                "commit": target_row.get("commit", ""),
                "resumed_from_version": resumed_version,
                "resumed_display_number": resumed_display,
                "backup_archive_id": backup_id,
            })
    except (OSError, sqlite3.Error, ValueError):
        pass


def switch(project, archive_id, commit="", *, request_id, expected_generation):
    project, key, dest, text = Path(project).resolve(), _id(request_id), _id(archive_id), _commit(commit)
    with _lock(project, True):
        _recover(project)
        state = _state(project)
        if state.get("generation") == key:
            if state.get("target") != dest or state.get("commit") != text:
                raise ValueError("This request ID has already been used.")
            return {**_listing(project), "backup": state["backup"]}
        _verify_generation(state, expected_generation)
        store = _store(project)
        target_row = _entry(store, dest)
        backup = uuid.uuid4().hex
        stage_id = uuid.uuid4().hex
        stage = store / (".switch-" + stage_id)
        stage.mkdir(mode=0o700)
        try:
            _copy_tree(store / dest / "files", stage / "new")
            (stage / "old").mkdir()
            try:
                inventory = _capture(project, store, backup, text, True)
            except (OSError, sqlite3.Error, ValueError) as exc:
                raise SafetyCopyFailed(str(exc)) from exc
            plan = _plan(project, stage / "new")
            # Prepare before the first rename. Recovery distinguishes a pending move
            # from a completed move by which side still has its original directory entry.
            for rel, had, has in plan:
                if had:
                    (stage / "old" / rel).parent.mkdir(parents=True, exist_ok=True)
            _write_json(stage / "moves.json", plan)
            _write_json(_state_path(project), {"format": 1, **state, "pending": stage_id})
            if inventory != _inventory(project):
                raise ValueError("The manuscript changed after its safety copy. Switch again to save the latest changes.")
            for rel, had, has in plan:
                live = _checked_path(project, rel)
                if had:
                    os.replace(live, stage / "old" / rel)
                if has:
                    os.replace(stage / "new" / rel, live)
            _write_json(_state_path(project), {"format": 1, "generation": key, "backup": backup, "target": dest, "commit": text})
        except BaseException:
            _recover(project)
            raise
        finally:
            # Retain the original entries if recovery itself needs a later retry.
            if "pending" not in _state(project):
                shutil.rmtree(stage, ignore_errors=True)
        _record_restore_event(project, target_row, backup)
        return {**_listing(project), "backup": backup}


def _zip_tree(bundle, folder, prefix):
    bundle.write(folder, prefix + "/")
    for child in sorted(folder.iterdir()):
        name = prefix + "/" + child.name
        if child.is_symlink():
            raise ValueError(f"请将符号链接替换为普通文件后再导出：{name}")
        if child.is_dir():
            _zip_tree(bundle, child, name)
        elif child.is_file():
            bundle.write(child, name)
        else:
            raise ValueError(f"Cannot export special file: {name}")


def export_zip(project, output, include_history, expected_generation):
    """Create a portable manuscript using committed SQLite data, including its WAL."""
    project = Path(project).resolve()
    if type(include_history) is not bool:
        raise ValueError("Invalid history option.")
    with _lock(project, True):
        _recover(project)
        _verify_generation(_state(project), expected_generation)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "manuscript"
            _copy_tree(project, copy)
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as bundle:
                _zip_tree(bundle, copy, project.name)
                if include_history:
                    store = _store(project)
                    if store.is_dir():
                        bundle.write(store / MARKER, store.name + "/" + MARKER)
                        for row in _listing(project)["archives"]:
                            entry = store / row["id"]
                            prefix = store.name + "/" + row["id"]
                            bundle.write(entry / "commit.json", prefix + "/commit.json")
                            _zip_tree(bundle, entry / "files", prefix + "/files")
