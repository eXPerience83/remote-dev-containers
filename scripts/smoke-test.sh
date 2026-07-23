#!/usr/bin/env bash
set -euo pipefail

if [[ ! -r /etc/os-release ]]; then
  echo "MISSING: /etc/os-release" >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
expected_ubuntu="${REMOTE_DEV_UBUNTU_VERSION:-}"
printf 'Base OS: %s %s (expected Ubuntu %s)\n' "${ID:-unknown}" "${VERSION_ID:-unknown}" "${expected_ubuntu:-unset}"
if [[ "${ID:-}" != "ubuntu" || -z "$expected_ubuntu" || "${VERSION_ID:-}" != "$expected_ubuntu" ]]; then
  echo "ERROR: child image is not based on the expected Ubuntu release" >&2
  exit 1
fi

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
