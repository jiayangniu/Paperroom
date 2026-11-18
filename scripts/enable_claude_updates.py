"""Switch Claude Code's Paperroom marketplace to the project's update branch."""
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install

URL = "https://github.com/jiayangniu/Paperroom.git"
BRANCH = "v2-author-workspace"
SOURCE = {"source": "git", "url": URL, "ref": BRANCH}
MARKET = install.MARKET


def read_settings(path):
    if path.is_symlink():
        raise ValueError(f"设置文件是符号链接，请在其实际位置配置更新源：{path}")
    raw = path.read_bytes() if path.exists() else None
    data = json.loads(raw) if raw is not None else {}
    if not isinstance(data, dict) or not isinstance(data.get("extraKnownMarketplaces", {}), dict):
        raise ValueError(f"无法读取 Claude Code 用户设置：{path}")
    aliases = data.get("additionalMarketplaces", {})
    if isinstance(aliases, dict) and MARKET in aliases:
        raise ValueError(f"请先核对 {path} 中 additionalMarketplaces 里的同名源。")
    return raw, data


def replace_entry(path, expected, replacement):
    raw, settings = read_settings(path)
    entries = settings.setdefault("extraKnownMarketplaces", {})
    current = entries.get(MARKET)
    if current == replacement:
        return
    if current not in expected:
        raise ValueError("Claude Code 的 Paperroom 设置已在别处变动，请重新运行。")
    if replacement is None:
        entries.pop(MARKET, None)
        if not entries:
            settings.pop("extraKnownMarketplaces")
    else:
        entries[MARKET] = replacement
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        staged = Path(tmp.name)
        try:
            if raw is not None:
                os.fchmod(tmp.fileno(), stat.S_IMODE(path.stat().st_mode))
            tmp.write((json.dumps(settings, ensure_ascii=False, indent=2) + "\n").encode())
            tmp.flush()
            if read_settings(path)[0] != raw:
                raise ValueError("Claude Code 的设置刚刚更新，请再运行一次。")
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)


def legacy_path(source, root):
    if source.get("source") != "directory":
        return None
    path = Path(source.get("path", ""))
    if path not in (root / "marketplace-0.2.0", root / "marketplace-0.3.0") or path.is_symlink():
        return None
    if path.exists():
        catalog = json.loads((path / ".claude-plugin/marketplace.json").read_bytes())
        if catalog.get("name") != MARKET or [p.get("name") for p in catalog["plugins"]] != ["paperroom"]:
            return None
    return path


def native_market(cli):
    markets = json.loads(install.output(cli, "marketplace", "list", "--json"))
    return next((entry for entry in markets if entry["name"] == MARKET), None)


def is_remote(source):
    return all(source.get(k) == v for k, v in SOURCE.items())


def user_plugin(cli):
    plugins = json.loads(install.output(cli, "list", "--json"))
    return next((p for p in plugins if p["id"] == install.PLUGIN and p.get("scope") == "user"), None)


def migrate(cli, config_dir, local_root):
    path = config_dir / "settings.json"
    _, settings = read_settings(path)
    before = settings.get("extraKnownMarketplaces", {}).get(MARKET)
    previous = native_market(cli)
    for source in [previous, before["source"] if before is not None else None]:
        if source is not None and not is_remote(source) and legacy_path(source, local_root) is None:
            raise ValueError(f"{MARKET} 已配置为其他来源，请在 Claude Code 内核对。")
    original = user_plugin(cli)
    # The native add command rejects a different declared source under this name.
    # Point the declaration at Git first, retaining the existing plugin identity.
    declared = {**(before or {}), "source": SOURCE}
    just_source = {"source": SOURCE}
    replace_entry(path, [before], declared)
    try:
        if previous and is_remote(previous):
            install.output(cli, "marketplace", "update", MARKET)
        else:
            install.output(cli, "marketplace", "add", URL + "#" + BRANCH, "--scope", "user")
        current = native_market(cli)
        if not current or not is_remote(current):
            raise RuntimeError("Claude Code 尚未登记指定的 GitHub 更新分支。")
        manifest = Path(current["installLocation"]) / "plugins/paperroom/.claude-plugin/plugin.json"
        version = json.loads(manifest.read_bytes())["version"]
        if not original or original.get("version") != version:
            action = "update" if original else "install"
            install.output(cli, action, install.PLUGIN, "--scope", "user")
        installed = user_plugin(cli)
        if not installed or installed.get("version") != version:
            raise RuntimeError("Claude Code 尚未安装 GitHub 分支上发布的版本。")
        # Native add rewrites its declaration and drops autoUpdate, so set it last.
        replace_entry(path, [just_source, declared], {**declared, "autoUpdate": True})
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        try:
            # Restore the old settings and registration if a fetch or upgrade failed.
            old_path = legacy_path(previous or {}, local_root)
            old_decl = {"source": {"source": "directory", "path": str(old_path)}}
            latest = native_market(cli)
            if old_path and old_path.is_dir() and (not latest or is_remote(latest)):
                replace_entry(path, [just_source, declared, before], old_decl)
                install.output(cli, "marketplace", "add", str(old_path), "--scope", "user")
            replace_entry(path, [just_source, declared, before, old_decl], before)
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as rollback:
            raise RuntimeError(f"迁移未完成：{exc}\n恢复旧源时遇到问题：{rollback}") from exc
        raise
    return version


def main():
    cli = install.binary("claude")
    if cli is None:
        raise ValueError("未找到 Claude Code。请先安装 Claude Code 再运行。")
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    local = Path.home() / ".local/share/paperroom"
    print("正在从 GitHub 检查 Paperroom 并为 Claude Code 开启自动更新…", flush=True)
    with install.installation_lock(local):
        version = migrate(cli, config, local)
    print(f"Claude Code 已安装 Paperroom {version}，并已开启自动更新。\n"
          "请在原 Claude Code 会话输入 /reload-plugins，或重新打开会话。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        sys.exit(f"Paperroom：{error}")
