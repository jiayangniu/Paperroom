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
LAUNCHERS = {"Install-Paperroom.command", "Try-Paperroom.command", "Enable-Claude-Updates.command", "Enable-Codex-Updates.command", "paperroom_mcp.py"}


def release_info():
    manifest = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text())
    codex = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text())
    envelopes = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    # Reading the tool list must not repoint the author's real launcher at this source folder.
    with tempfile.TemporaryDirectory() as state:
        response = subprocess.run(
            [sys.executable, "-B", str(RUNTIME / "paperroom_mcp.py")],
            input="\n".join(map(json.dumps, envelopes)) + "\n", text=True, capture_output=True, timeout=10,
            env={**os.environ, "PAPERROOM_STATE_DIR": state, "PAPERROOM_CLIENT": "claude-chat"})
    if response.returncode:
        raise RuntimeError(response.stderr.strip())
    hello, tools = [json.loads(line)["result"] for line in response.stdout.splitlines()]
    if manifest["version"] != codex["version"] or hello["serverInfo"]["version"] != manifest["version"]:
        raise ValueError("MCP runtime and client manifests require matching versions.")
    return manifest, [{key: tool[key] for key in ("name", "description")} for tool in tools["tools"]]


def runtime_files():
    return sorted(file for file in RUNTIME.rglob("*")
                  if file.is_file() and (file.suffix in ASSET_TYPES or file == RUNTIME / "README-workflow.md")
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
                "env": {"PAPERROOM_CLIENT": "claude-chat", "PAPERROOM_TSA_URL": "${user_config.tsa_url}"},
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
                "install.py", "Install-Paperroom.command", "Try-Paperroom.command", "Enable-Claude-Updates.command", "Enable-Codex-Updates.command",
                "scripts/enable_claude_updates.py", "scripts/codex_updates.py", "scripts/verify_timestamps.py", "LICENSE",
                "docs/writing-guide.md", "docs/writing-guide.zh-CN.md",
                "scripts/try_workspace.py", "demo/examples/evidence.csv", "demo/examples/intro.tex", "demo/examples/intro.pdf",
                "demo/examples/intro-original.tex", "demo/examples/intro-original.pdf",
                ".agents/plugins/marketplace.json", ".claude-plugin/marketplace.json",
                "plugins/paperroom/.mcp.json", "plugins/paperroom/codex.mcp.json", "plugins/paperroom/hooks/hooks.json",
                "plugins/paperroom/.claude-plugin/plugin.json", "plugins/paperroom/.codex-plugin/plugin.json",
                "plugins/paperroom/skills/open/SKILL.md",
                "plugins/paperroom/skills/open/agents/openai.yaml",
            )
        ]
        zipped = {"paperroom-plugin/" + file.relative_to(ROOT).as_posix(): file.read_bytes() for file in files}
        zipped["paperroom-plugin/README.md"] = (
            "# Paperroom " + native["version"] + "\n\n"
            "On macOS, double-click [Try-Paperroom.command](Try-Paperroom.command) in this extracted folder to try "
            "the three-level outline and section review on a sample paper.\n\n"
            "Claude Code users can double-click [Enable-Claude-Updates.command](Enable-Claude-Updates.command) to "
            "upgrade and turn on automatic updates from the main branch, where releases are published, "
            "then reopen their Claude Code session.\n\n"
            "To use Paperroom in Claude Code or Codex, double-click [Install-Paperroom.command](Install-Paperroom.command), "
            "or run `python3 install.py` here (Python 3.9 or later). For automatic Codex updates on macOS, double-click [Enable-Codex-Updates.command](Enable-Codex-Updates.command) or run "
            "`python3 install.py --client codex --auto-update`. Open a new session in your manuscript folder.\n\n"
            "To start, say \"Use Paperroom to manage this manuscript.\" Reopen it with `/paperroom:open` "
            "in Claude Code or `$paperroom:open` in Codex and click the returned link. "
            "Codex's `/hooks` controls the optional edit checks.\n\n"
            "Claude desktop Chat uses the separate Paperroom.mcpb. Tell Chat which manuscript folder to open. "
            "Verify an exported writing log with "
            "`python3 scripts/verify_timestamps.py record.json`.\n\n"
            "Read the [writing guide](docs/writing-guide.md) for each step, references, polish and figures. "
            "Your AI reads its own [instructions](plugins/paperroom/runtime/README-workflow.md) by calling `get_usage()`.\n\n"
            "## 中文\n\n"
            "解压完整目录后，在 macOS 双击 [Try-Paperroom.command](Try-Paperroom.command)，"
            "就能在浏览器里体验三级大纲和整节审阅。示例使用本包内的虚构实验，单独运行即可。\n\n"
            "Claude Code 用户可双击 [Enable-Claude-Updates.command](Enable-Claude-Updates.command)，"
            "将已有插件升级并开启 GitHub main 分支（正式发布版）的自动更新。重新打开本地 Claude Code 会话即可加载新版。\n\n"
            "要在 Claude Code 或 Codex 的原聊天里使用，请双击 [Install-Paperroom.command](Install-Paperroom.command)，"
            "或在解压目录运行 `python3 install.py`。需要 Python 3.9 或以上版本。"
            "macOS 上可运行 `python3 install.py --client codex --auto-update` 为 Codex 开启自动更新。\n\n"
            "在论文目录开一个新会话，说“用 Paperroom 管理这篇论文”。下次打开写作间，Claude Code 输入 "
            "`/paperroom:open`，Codex 输入 `$paperroom:open`，点击返回的链接。\n\n"
            "Claude 桌面版 Chat 请安装另行提供的 Paperroom.mcpb，在对话里告诉它要打开哪篇论文的文件夹。"
            "每一步怎么做、怎样请 AI 给参考或润色、图表放在哪里，见[写作指导](docs/writing-guide.zh-CN.md)。"
            "AI 调用 `get_usage()` 会读到写给它的[操作说明](plugins/paperroom/runtime/README-workflow.md)。\n\n"
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
