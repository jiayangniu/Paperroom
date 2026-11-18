#!/usr/bin/env python3
"""Build the macOS Chat extension and the Claude Code / Codex distribution."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/paperroom"
RUNTIME = PLUGIN / "runtime"
ASSET_TYPES = {".py", ".js", ".css", ".html", ".svg", ".woff2", ".woff", ".png", ".json"}
LAUNCHERS = {"Install-Paperroom.command", "Try-Paperroom.command", "Enable-Claude-Updates.command", "paperroom_mcp.py"}


def release_info():
    manifest = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
    codex = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
    envelopes = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    response = subprocess.run(
        [sys.executable, "-B", str(RUNTIME / "paperroom_mcp.py")],
        input="\n".join(map(json.dumps, envelopes)) + "\n", text=True, capture_output=True, timeout=10
    )
    if response.returncode:
        raise RuntimeError(response.stderr.strip())
    hello, tools = [json.loads(line)["result"] for line in response.stdout.splitlines()]
    if manifest["version"] != codex["version"] or hello["serverInfo"]["version"] != manifest["version"]:
        raise ValueError("MCP runtime and client manifests require matching versions.")
    return manifest, [{key: tool[key] for key in ("name", "description")} for tool in tools["tools"]]


def runtime_files():
    return sorted(file for file in RUNTIME.rglob("*")
                  if file.is_file() and file.suffix in ASSET_TYPES
                  and all(not part.startswith(".") and part != "__pycache__"
                          for part in file.relative_to(RUNTIME).parts))


def bundle_manifest(native, tools):
    return {
        **native,
        "manifest_version": "0.3",
        "display_name": "Paperroom",
        "server": {
            "type": "python", "entry_point": "server/paperroom_mcp.py",
            "mcp_config": {
                "command": "/usr/bin/python3",
                "args": ["-B", "${__dirname}/server/paperroom_mcp.py"],
                "env": {"PAPERROOM_TSA_URL": "${user_config.tsa_url}"},
            },
        },
        "user_config": {
            "tsa_url": {
                "type": "string", "title": "时间戳服务地址（可选）",
                "description": "填入你信任的 RFC 3161 服务的 HTTPS 地址。留空即可仅使用本机时间戳。",
                "required": False, "default": "",
            },
        },
        "tools": tools,
        "compatibility": {"platforms": ["darwin"], "runtimes": {"python": ">=3.9.0"}},
    }


def archive_bytes(files):
    data = io.BytesIO()
    with ZipFile(data, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            entry = ZipInfo(name)
            entry.compress_type = ZIP_DEFLATED
            entry.create_system = 3
            mode = 0o755 if Path(name).name in LAUNCHERS else 0o644
            entry.external_attr = (0o100000 | mode) << 16
            archive.writestr(entry, content)
    return data.getvalue()


def build(destination, desktop_only=False):
    native, tools = release_info()
    assets = runtime_files()
    desktop = {"manifest.json": json.dumps(bundle_manifest(native, tools), ensure_ascii=False, indent=2).encode(),
               "LICENSE": (ROOT / "LICENSE").read_bytes()}
    for file in assets:
        desktop["server/" + file.relative_to(RUNTIME).as_posix()] = file.read_bytes()
    artifacts = {"Paperroom.mcpb": archive_bytes(desktop)}
    if not desktop_only:
        files = list(assets) + [
            ROOT / path for path in (
                "install.py", "Install-Paperroom.command", "Try-Paperroom.command", "Enable-Claude-Updates.command",
                "scripts/enable_claude_updates.py", "scripts/verify_timestamps.py", "LICENSE",
                "scripts/try_workspace.py", "demo/examples/evidence.csv", "demo/examples/intro.tex", "demo/examples/intro.pdf",
                "demo/examples/intro-original.tex", "demo/examples/intro-original.pdf",
                ".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json",
                "plugins/paperroom/.mcp.json", "plugins/paperroom/codex.mcp.json",
                "plugins/paperroom/.claude-plugin/plugin.json", "plugins/paperroom/.codex-plugin/plugin.json",
            )
        ]
        zipped = {"paperroom-plugin/" + file.relative_to(ROOT).as_posix(): file.read_bytes() for file in files}
        zipped["paperroom-plugin/README.md"] = (
            "# Paperroom " + native["version"] + "\n\n"
            "解压完整目录后，在 macOS 双击 [Try-Paperroom.command](Try-Paperroom.command)，"
            "就能在浏览器里体验三级大纲和整节审阅。示例使用本包内的虚构实验，单独运行即可。\n\n"
            "Claude Code 用户可双击 [Enable-Claude-Updates.command](Enable-Claude-Updates.command)，"
            "将已有插件升级并开启 GitHub 第二版分支的自动更新。重新打开本地 Claude Code 会话即可加载新版。\n\n"
            "要在 Claude Code 或 Codex 的原聊天里使用，请双击 [Install-Paperroom.command](Install-Paperroom.command)，"
            "或在解压目录运行 `python3 install.py`。需要 Python 3.9 或以上版本。"
            "重新载入插件，在论文项目里说“用 Paperroom 帮我重写引言”。\n\n"
            "Claude 桌面版 Chat 请安装另行提供的 Paperroom.mcpb。\n\n"
            "核验写作间导出的时间戳文件可运行 `python3 scripts/verify_timestamps.py record.json`。"
            "可用 `--ca-file trusted-ca.pem` 指定核验者信任的 CA 证书。\n\n"
            "[项目主页](https://github.com/jiayangniu/Paperroom) · [许可](LICENSE)\n"
        ).encode()
        artifacts["Paperroom-Plugin-" + native["version"] + ".zip"] = archive_bytes(zipped)

    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as tmp:
        for name, data in artifacts.items():
            file = Path(tmp) / name
            file.write_bytes(data)
            os.replace(file, destination / name)
    return list(artifacts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "packages")
    args = parser.parse_args()
    for name in build(args.output):
        print(args.output / name)


if __name__ == "__main__":
    main()
