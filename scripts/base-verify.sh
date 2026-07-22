#!/usr/bin/env bash
set -euo pipefail

required=(bash git git-lfs gh ssh curl wget jq rg fd tmux ttyd mise python node npm uv shellcheck)
missing=0
for cmd in "${required[@]}"; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "MISSING: $cmd" >&2
    missing=1
  fi
done

if (( missing != 0 )); then
  exit 1
fi

python --version
node --version
npm --version
uv --version
gh --version | head -n 1
ttyd --version
mise --version
