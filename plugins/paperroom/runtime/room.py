"""Keep one workspace server per manuscript alive across chat windows, client restarts and updates.

The server runs as its own background process. Its port and token are kept in the user's
Paperroom state folder and reused whenever it starts again, so a page the author left open
reconnects by itself. Every client (Claude Code, Claude Chat, Codex) finds the same server
through that record. A newer plugin version takes over from an older server on the same port;
an older one never replaces a newer server. The server exits after a long idle period.
"""
import hashlib
import http.client
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
LAUNCHED = []  # detached servers started by this process; never waited on
IDLE_SECONDS = 12 * 3600
START_SECONDS = 10


def state_dir():
    base = os.environ.get("PAPERROOM_STATE_DIR") or str(Path.home() / ".local/share/paperroom")
    folder = Path(base).expanduser() / "rooms"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass
    return folder


def enabled():
    return os.environ.get("PAPERROOM_ROOM", "").strip().lower() not in ("off", "0", "false", "no")


def idle_seconds():
    try:
        return max(1.0, float(os.environ.get("PAPERROOM_ROOM_IDLE", IDLE_SECONDS)))
    except ValueError:
        return IDLE_SECONDS


def project_key(project):
    return hashlib.sha256(str(Path(project).resolve()).encode("utf-8")).hexdigest()[:20]


def workspace_url(project, port, query=None):
    # A port may eventually be allocated to another paper. Keep the project identity in bookmarks.
    params = {key: value for key, value in (query or {}).items() if value is not None}
    params["room"] = project_key(project)
    return f"http://127.0.0.1:{port}/workspace?{urlencode(params)}"


def record_path(project):
    return state_dir() / (project_key(project) + ".json")


def read_record(project):
    try:
        record = json.loads(record_path(project).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("project") != str(Path(project).resolve()):
        return None
    if not isinstance(record.get("token"), str) or not isinstance(record.get("port"), int):
        return None
    return record


def write_record(project, record):
    path = record_path(project)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as tmp:
        staged = Path(tmp.name)
        try:
            os.chmod(staged, 0o600)
            json.dump(record, tmp)
            tmp.flush()
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)


@contextmanager
def project_lock(project):
    """Only one client at a time decides whether to start or replace a project's server."""
    lock = record_path(project).with_suffix(".lock")
    with open(lock, "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield


def version_key(version):
    return tuple(int(part) for part in re.findall(r"\d+", str(version or "")))


def request(record, method, path, timeout=1.5):
    """Talk to the local server directly (no proxy), presenting the project's token."""
    connection = http.client.HTTPConnection("127.0.0.1", record["port"], timeout=timeout)
    try:
        connection.request(method, path, headers={"X-Paperroom-Token": record["token"],
                                                  "Host": f"127.0.0.1:{record['port']}"})
        response = connection.getresponse()
        body = response.read()
        return response.status, json.loads(body or b"{}")
    finally:
        connection.close()


def probe(record):
    try:
        status, info = request(record, "GET", "/api/room")
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return info if status == 200 and isinstance(info, dict) else None


def port_free(port):
    if not port:
        return False
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def stop(record, info):
    """Ask a running server to exit; fall back to a signal for a server that does not answer."""
    try:
        request(record, "POST", "/api/room/stop")
    except (OSError, ValueError, http.client.HTTPException):
        pass
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline and probe(record):
        time.sleep(0.1)
    pid = info.get("pid")
    if probe(record) and isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and probe(record):
            time.sleep(0.1)
    for process in [p for p in LAUNCHED if p.pid == pid]:
        try:
            process.wait(timeout=3)   # reap a server this process started itself
            LAUNCHED.remove(process)
        except subprocess.TimeoutExpired:
            pass


def ensure(project, version):
    """Return the port of the project's running server, starting or upgrading it if needed."""
    project = Path(project).resolve()
    for process in list(LAUNCHED):
        if process.poll() is not None:   # reap servers that already exited (idle or stopped)
            LAUNCHED.remove(process)
    with project_lock(project):
        record = read_record(project)
        if record:
            info = probe(record)
            if info and info.get("project") == str(project):
                if version_key(info.get("version")) >= version_key(version):
                    return record["port"]
                stop(record, info)
        token = record["token"] if record else secrets.token_urlsafe(32)
        port = record["port"] if record and port_free(record["port"]) else 0
        log = record_path(project).with_suffix(".log")
        env = {**os.environ, "PAPERROOM_ROOM_TOKEN": token, "PAPERROOM_ROOM_VERSION": str(version)}
        popen_kwargs = dict(cwd=str(HERE), env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, close_fds=True)
        if os.name == "nt":
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            popen_kwargs["start_new_session"] = True
        with open(log, "wb") as errors:
            popen_kwargs["stderr"] = errors
            process = subprocess.Popen(
                [sys.executable, str(HERE / "workspace_server.py"), str(project), "--room", "--port", str(port)],
                **popen_kwargs)
        LAUNCHED.append(process)
        deadline = time.monotonic() + START_SECONDS
        while time.monotonic() < deadline:
            current = read_record(project)
            if current and current.get("pid") == process.pid and probe(current):
                return current["port"]
            if process.poll() is not None:
                break
            time.sleep(0.05)
        if process.poll() is None:
            process.terminate()
        detail = log.read_text("utf-8", "replace").strip().splitlines()[-1:] if log.is_file() else []
        raise RuntimeError("写作间后台服务没有启动" + ("：" + detail[0] if detail else "。"))


def announce(project, port, token, version):
    """Called by the server once it is listening: record where the page can find it."""
    write_record(project, {"project": str(Path(project).resolve()), "port": port, "token": token,
                           "version": str(version), "pid": os.getpid(), "runtime": str(HERE),
                           "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
