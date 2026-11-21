#!/usr/bin/env python3
"""Install the local Paperroom plugin for Claude Code and Codex."""
import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKET = "paperroom-local"
PLUGIN = "paperroom@" + MARKET
VERSION = json.loads((ROOT / "plugins/paperroom/.claude-plugin/plugin.json").read_text())["version"]
FOLDERS = (".agents", ".claude-plugin", "plugins")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def binary(client):
    found = shutil.which(client)
    if found:
        return Path(found)
    if client == "codex":
        options = [Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"),
                   Path("/Applications/Codex.app/Contents/Resources/codex")]
    else:
        desktop = Path.home() / "Library/Application Support/Claude/claude-code"
        bundled = list(desktop.glob("*/*/claude.app/Contents/MacOS/claude"))
        extensions = Path.home() / ".vscode/extensions"
        bundled.extend(extensions.glob("anthropic.claude-code-*/resources/native-binary/claude"))
        options = [Path.home() / ".local/bin/claude", *sorted(
            bundled, key=lambda path: path.stat().st_mtime, reverse=True)]
    return next((path for path in options if path.is_file() and os.access(path, os.X_OK)), None)


@contextmanager
def installation_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".install.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if lock.seek(0, os.SEEK_END) == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        # Closing the file descriptor releases the operating-system lock.
        yield


def deploy_source(parent, source_root=ROOT, version=VERSION):
    destination = parent / ("marketplace-" + version)
    if destination.exists():
        for group in FOLDERS:
            for source in (source_root / group).rglob("*"):
                if not source.is_file() or "__pycache__" in source.parts or source.name == ".DS_Store" or source.suffix == ".pyc":
                    continue
                target = destination / source.relative_to(source_root)
                if not target.is_file() or not filecmp.cmp(source, target, shallow=False):
                    raise ValueError(f"同版本的插件目录有本地修改，请检查 {destination}")
        return destination
    with tempfile.TemporaryDirectory(dir=parent) as temporary:
        staged = Path(temporary) / "marketplace"
        staged.mkdir()
        for folder in FOLDERS:
            shutil.copytree(source_root / folder, staged / folder, ignore=IGNORE)
        (staged / "plugins/paperroom/runtime/paperroom_mcp.py").chmod(0o755)
        shutil.copyfile(source_root / "LICENSE", staged / "LICENSE")
        staged.rename(destination)
    return destination


def output(cli, *args):
    process = subprocess.run([str(cli), "plugin", *args], text=True, capture_output=True, timeout=60)
    if process.returncode:
        raise RuntimeError((process.stderr.strip() + "\n" + process.stdout.strip()).strip() or "插件命令未成功")
    return process.stdout.strip()


def previous_source(path, parent):
    """Only move a native client's registration for our own versioned single-plugin catalog."""
    if path.is_symlink() or path.parent.resolve() != parent.resolve():
        return False
    if not re.fullmatch(r"marketplace-[0-9]+\.[0-9]+\.[0-9]+", path.name):
        return False
    if not path.exists():
        # A deleted old installation still has an unambiguous versioned user path.
        return True
    try:
        for catalog in (".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json"):
            document = json.loads((path / catalog).read_text())
            if document["name"] != MARKET or [p["name"] for p in document["plugins"]] != ["paperroom"]:
                return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


def installed_entry(client, cli):
    options = ["-m", MARKET] if client == "codex" else []
    records = json.loads(output(cli, "list", "--json", *options))
    if client == "codex":
        records = records["installed"]
    return next((entry for entry in records if (entry.get("pluginId") or entry.get("id")) == PLUGIN
                 and (client == "codex" or entry.get("scope") == "user")), {})


def register(client, cli, directory, version=VERSION):
    listings = json.loads(output(cli, "marketplace", "list", "--json"))
    entries = listings["marketplaces"] if client == "codex" else listings
    current = next((entry for entry in entries if entry.get("name") == MARKET), None)
    old = None
    if current:
        location = current.get("root") or current.get("path") or current.get("installLocation")
        if not location:
            raise ValueError(f"{client} 未报告已有插件源的位置，请检查 {MARKET}")
        old = Path(location)
        if old.resolve() != directory.resolve() and not previous_source(old, directory.parent):
            raise ValueError(f"{client} 正在使用自定义的同名插件源，请检查 {old}")

    replacing = old is not None and old.resolve() != directory.resolve()
    switched = False
    if replacing and client == "codex":
        output(cli, "marketplace", "remove", MARKET)
    try:
        if old is None or replacing:
            output(cli, "marketplace", "add", str(directory))
            switched = True
        entry = installed_entry(client, cli)
        if client == "codex":
            # A new source can advertise its version before the local plugin cache is refreshed.
            if switched or entry.get("version") != version or not entry.get("enabled"):
                output(cli, "add", PLUGIN)
        elif not entry:
            output(cli, "install", PLUGIN, "--scope", "user")
        else:
            if entry.get("version") != version:
                output(cli, "update", PLUGIN, "--scope", "user")
            if not entry.get("enabled"):
                output(cli, "enable", PLUGIN, "--scope", "user")
        final = installed_entry(client, cli)
        if not final.get("enabled") or final.get("version") != version:
            raise RuntimeError(f"请检查 {client} 的 Plugins 列表：需要启用的 Paperroom {version}")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        if client == "codex" and replacing and old.is_dir():
            if switched:
                output(cli, "marketplace", "remove", MARKET)
            output(cli, "marketplace", "add", str(old))
            if switched:
                output(cli, "add", PLUGIN)
        raise
    print(f"{client} 已安装并启用 {PLUGIN} ({version})。", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", choices=("auto", "codex", "claude"), default="auto")
    update_options = parser.add_mutually_exclusive_group()
    update_options.add_argument("--auto-update", action="store_true",
                                help="Also enable daily updates for Codex from Paperroom's GitHub main (macOS).")
    update_options.add_argument("--disable-auto-update", action="store_true",
                                help="Stop Paperroom’s daily Codex updates on macOS.")
    arguments = parser.parse_args()
    if arguments.auto_update or arguments.disable_auto_update:
        if sys.platform != "darwin" or arguments.client != "codex":
            parser.error("更新订阅只适用于 macOS，请指定 --client codex。")
        from scripts import codex_updates
        if arguments.disable_auto_update:
            codex_updates.disable(Path.home())
            return
    targets = ("claude", "codex") if arguments.client == "auto" else (arguments.client,)
    clients = {name: binary(name) for name in targets}
    if not any(clients.values()):
        raise ValueError("未找到本机 Claude Code 或 Codex CLI。请先安装所需客户端，或将其加入 PATH。")
    parent = Path.home() / ".local/share/paperroom"
    failures = []
    with installation_lock(parent):
        location = deploy_source(parent)
        for name, cli in clients.items():
            if cli is None:
                print(f"未发现 {name}，已跳过。")
                continue
            try:
                register(name, cli, location)
                if arguments.auto_update:
                    codex_updates.enable(Path.home(), ROOT, location, cli)
            except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
                failures.append(f"{name}：{exc}")
    if failures:
        raise RuntimeError("\n".join(failures))
    print("请重新载入客户端插件，并在论文所在的项目中继续写作。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        sys.exit(str(exc))
