#!/usr/bin/env python3
"""Install Paperroom once for the available local Codex and Claude Code clients."""
import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARKET = "paperroom-local"
PLUGIN = "paperroom@" + MARKET
VERSION = "0.2.0"
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
        extensions = Path.home()/".vscode/extensions"
        options = [Path.home()/".local/bin/claude", *sorted(
            extensions.glob("anthropic.claude-code-*/resources/native-binary/claude"),
            key=lambda p:p.stat().st_mtime, reverse=True)]
    return next((p for p in options if p.is_file() and os.access(p,os.X_OK)),None)


def deploy_source():
    parent = Path.home()/".local/share/paperroom"
    destination = parent/("marketplace-"+VERSION)
    parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        for group in FOLDERS:
            for src in (ROOT/group).rglob("*"):
                if not src.is_file() or "__pycache__" in src.parts or src.name in (".DS_Store",) or src.suffix==".pyc":
                    continue
                target = destination/src.relative_to(ROOT)
                if not target.is_file() or not filecmp.cmp(src,target,shallow=False):
                    raise ValueError(f"已存在内容不同的同版本插件目录：{destination}")
        return destination
    with tempfile.TemporaryDirectory(dir=parent) as temp:
        staged = Path(temp)/"marketplace"
        staged.mkdir()
        for item in FOLDERS:
            shutil.copytree(ROOT/item,staged/item,ignore=IGNORE)
        launcher = staged/"plugins/paperroom/runtime/paperroom_mcp.py"
        launcher.chmod(0o755)
        shutil.copyfile(ROOT/"LICENSE",staged/"LICENSE")
        staged.rename(destination)
    return destination


def output(cli,*args):
    proc = subprocess.run([str(cli),"plugin",*args],text=True,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,timeout=60)
    if proc.returncode:
        raise RuntimeError((proc.stderr.strip()+"\n"+proc.stdout.strip()).strip() or "插件命令未成功")
    return proc.stdout.strip()


def register(client,cli,directory):
    entries = json.loads(output(cli,"marketplace","list","--json"))
    if client == "codex":
        entries = entries["marketplaces"]
    current = next((e for e in entries if e.get("name")==MARKET),None)
    if current:
        location = current.get("root") or current.get("path") or current.get("installLocation")
        if not location or Path(location).resolve()!=directory.resolve():
            raise ValueError(f"{client} 已配置另一个同名插件源：{location}。保留原配置，请先核对。")
    else:
        output(cli,"marketplace","add",str(directory))

    def record():
        items = json.loads(output(cli,"list","--json",*(["-m",MARKET] if client=="codex" else [])))
        if client=="codex":
            items=items["installed"]
        return next((e for e in items if (e.get("pluginId") or e.get("id"))==PLUGIN
                     and (client=="codex" or e.get("scope")=="user")),{})

    if not record().get("enabled"):
        if client=="codex":
            output(cli,"add",PLUGIN)
        elif record():
            output(cli,"enable",PLUGIN,"--scope","user")
        else:
            output(cli,"install",PLUGIN,"--scope","user")
    final=record()
    if not final.get("enabled"):
        raise RuntimeError("客户端已处理安装请求，但未报告启用；请查看客户端的 Plugins 列表。")
    print(f"{client}：已安装并启用 {PLUGIN}（{final.get('version',VERSION)}）。",flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--client",choices=("auto","codex","claude"),default="auto")
    args=p.parse_args()
    targets = ("claude","codex") if args.client=="auto" else (args.client,)
    clients = {name:binary(name) for name in targets}
    if not any(clients.values()):
        raise ValueError("未找到本机 Claude Code 或 Codex CLI。请先安装所需客户端，或将其加入 PATH。")
    location=deploy_source()
    failures=[]
    for name,cli in clients.items():
        if cli is None:
            print(f"未发现 {name}，已跳过。")
            continue
        try:
            register(name,cli,location)
        except (OSError,ValueError,KeyError,RuntimeError,subprocess.TimeoutExpired) as exc:
            failures.append(f"{name}：{exc}")
    if failures:
        raise RuntimeError("\n".join(failures))
    print("请重新载入客户端插件。之后直接在论文的工作目录中提出写作请求即可。")


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,RuntimeError) as exc:
        sys.exit(str(exc))
