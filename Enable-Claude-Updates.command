#!/bin/sh
set -eu
cd -- "$(dirname -- "$0")"
exec python3 -B scripts/enable_claude_updates.py
