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

if command -v bwrap >/dev/null 2>&1; then
  echo "ERROR: the system Bubblewrap executable must not be installed in the default outer-isolation image" >&2
  exit 1
fi

if [[ ! -r /etc/os-release ]]; then
  echo "MISSING: /etc/os-release" >&2
  exit 1
fi

ttyd_index=/usr/share/remote-dev/ttyd/index.html
expected_ttyd_index_sha=84724f4f4e63b559631ace65df3f21f2941b1dd8199b76f78ca3d5f9e07aadd8
if [[ ! -f "$ttyd_index" || -L "$ttyd_index" ]]; then
  echo "ERROR: Remote Dev ttyd index must be a regular non-symlink file" >&2
  exit 1
fi
if [[ "$(stat -c '%u:%g %a' "$ttyd_index")" != "0:0 444" ]]; then
  echo "ERROR: Remote Dev ttyd index must be root-owned mode 0444" >&2
  exit 1
fi
if [[ "$(sha256sum "$ttyd_index" | cut -d' ' -f1)" != "$expected_ttyd_index_sha" ]]; then
  echo "ERROR: Remote Dev ttyd index hash mismatch" >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
expected_ubuntu="${REMOTE_DEV_UBUNTU_VERSION:-}"
printf 'Base OS: %s %s (expected Ubuntu %s)\n' "${ID:-unknown}" "${VERSION_ID:-unknown}" "${expected_ubuntu:-unset}"
if [[ "${ID:-}" != "ubuntu" || -z "$expected_ubuntu" || "${VERSION_ID:-}" != "$expected_ubuntu" ]]; then
  echo "ERROR: unexpected base operating system" >&2
  exit 1
fi

python --version
node --version
npm --version
uv --version
gh --version | head -n 1
ttyd --version
mise --version
