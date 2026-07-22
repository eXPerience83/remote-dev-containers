#!/usr/bin/env bash
set -euo pipefail

codex --version
gh --version | head -n 1
git --version
python --version
node --version
npm --version
uv --version
ttyd --version
tmux -V
mise --version

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
cd "$workdir"
git init -q
printf 'print("ok")\n' > smoke.py
python smoke.py | grep -Fx ok
node -e 'console.log("ok")' | grep -Fx ok
