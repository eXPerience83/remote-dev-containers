#!/usr/bin/env bash
set -euo pipefail

readonly staging_parent=/root/.local/share/remote-dev/antigravity
if [[ ! -d "$staging_parent" || -L "$staging_parent" ]]; then
  echo "ERROR: Antigravity staging directory is unavailable or unsafe: $staging_parent" >&2
  exit 1
fi

export TMPDIR="$staging_parent"
exec /usr/local/bin/remote-dev-antigravity update "$@"
