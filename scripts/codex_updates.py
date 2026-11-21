"""Daily, opt-in macOS updater for Paperroom's published Codex package on GitHub main."""
import io
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile


LABEL = "org.paperroom.codex-update"
BASE = "https://raw.githubusercontent.com/jiayangniu/Paperroom/main/"
MANIFEST = "plugins/paperroom/.codex-plugin/plugin.json"
DAY = 24 * 60 * 60


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError(f"无效的 Paperroom 发布版本：{value!r}")
    return tuple(map(int, value.split(".")))


def release(manifest):
    if manifest.get("name") != "paperroom":
        raise ValueError("GitHub 清单未标明 Paperroom")
    value = manifest.get("version")
    version(value)
    return value


def fetch(path):
    with urlopen(BASE + path, timeout=40) as response:
        return response.read()


def apply_latest(cli, parent):
    # Use the installer shipped alongside the updater, even after the download was removed.
    import install

    remote = release(json.loads(fetch(MANIFEST)))
    with install.installation_lock(parent):
        installed = install.installed_entry("codex", cli)
        if not installed.get("enabled") or version(remote) <= version(installed["version"]):
            return
        data = fetch(f"packages/Paperroom-Plugin-{remote}.zip")
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            with ZipFile(io.BytesIO(data)) as archive:
                archive.extractall(temporary)
            source = Path(temporary) / "paperroom-plugin"
            for name in (MANIFEST, "plugins/paperroom/.claude-plugin/plugin.json"):
                if release(json.loads((source / name).read_text())) != remote:
                    raise ValueError("GitHub 安装包与发布清单的版本不一致")
            location = install.deploy_source(parent, source, remote)
        install.register("codex", cli, location, remote)


def put(path, data):
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as staged:
        name = staged.name
        try:
            staged.write(data)
            staged.flush()
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)


def plist_path(home):
    return home / "Library/LaunchAgents" / (LABEL + ".plist")


def launchctl(*args, check=True):
    result = subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True, timeout=20)
    if check and result.returncode:
        raise RuntimeError("launchctl: " + (result.stderr.strip() or str(result.returncode)))
    return result.returncode


def enable(home, source, installation, cli):
    for name in ("install.py", "scripts/codex_updates.py"):
        put(installation / name, (source / name).read_bytes())
    target = plist_path(home)
    old = target.read_bytes() if target.exists() else None
    domain = f"gui/{os.getuid()}"
    options = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(installation / "scripts/codex_updates.py"), str(cli)],
        "RunAtLoad": True,
        "StartInterval": DAY,
        "StandardErrorPath": str(installation.parent / "codex-update.log"),
    }
    # Preserve the chosen Codex profile, not the rest of a terminal's environment.
    if os.environ.get("CODEX_HOME"):
        options["EnvironmentVariables"] = {"CODEX_HOME": str(Path(os.environ["CODEX_HOME"]).expanduser().resolve())}
    data = plistlib.dumps(options)
    service = f"{domain}/{LABEL}"
    loaded = launchctl("print", service, check=False) == 0
    if data != old or not loaded:
        if loaded:
            launchctl("bootout", service)
        try:
            put(target, data)
            launchctl("bootstrap", domain, str(target))
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            if old is None:
                target.unlink(missing_ok=True)
            else:
                put(target, old)
                if loaded:
                    launchctl("bootstrap", domain, str(target))
            raise
    print("已启用 Codex 自动更新：登录及每 24 小时检查 GitHub main，新会话加载新版。", flush=True)


def disable(home):
    service = f"gui/{os.getuid()}/{LABEL}"
    if launchctl("print", service, check=False) == 0:
        launchctl("bootout", service)
    plist_path(home).unlink(missing_ok=True)
    print("已关闭 Paperroom 的 Codex 自动更新。", flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        apply_latest(Path(sys.argv[1]), Path.home() / ".local/share/paperroom")
    except (OSError, ValueError, KeyError, BadZipFile, RuntimeError, subprocess.TimeoutExpired) as exc:
        sys.exit("Paperroom 更新未完成：" + str(exc))
