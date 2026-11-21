#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
if [ ! -f install.py ]; then
    echo "请解压完整的 Paperroom-Plugin 安装包，并在解压目录内双击 Enable-Codex-Updates.command。"
    exit 1
fi
exec python3 install.py --client codex --auto-update
