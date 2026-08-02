#!/usr/bin/env bash
set -euo pipefail

readonly DEFAULT_MANAGER=/usr/local/bin/remote-dev-antigravity
readonly DEFAULT_SECURE_STATE=/usr/local/bin/secure-persistent-state

if [[ "${REMOTE_DEV_ANTIGRAVITY_TESTING:-0}" == "1" ]]; then
  manager="${REMOTE_DEV_ANTIGRAVITY_MANAGER:-$DEFAULT_MANAGER}"
  secure_state="${REMOTE_DEV_SECURE_STATE:-$DEFAULT_SECURE_STATE}"
else
  manager="$DEFAULT_MANAGER"
  secure_state="$DEFAULT_SECURE_STATE"
fi

[[ -x "$manager" ]] || { echo "ERROR: Antigravity runtime manager is unavailable" >&2; exit 1; }
[[ -x "$secure_state" ]] || { echo "ERROR: persistent-state hardening command is unavailable" >&2; exit 1; }

binary="$($manager path)"
if [[ ! -f "$binary" || -L "$binary" || ! -x "$binary" ]]; then
  cat >&2 <<EOF
ERROR: Antigravity is not installed at the canonical path:
  $binary
Run remote-dev-install-antigravity explicitly before launching it.
EOF
  exit 1
fi

# This verifies the reviewed hash and version before the executable is invoked
# for a real session. It never downloads or updates anything.
$manager status >/dev/null

workspace="${WORKSPACE:-/workspace}"
[[ "$workspace" == /* && "$workspace" != *$'\n'* ]] \
  || { echo "ERROR: WORKSPACE must be an absolute path" >&2; exit 2; }
mkdir -p "$workspace"
cd "$workspace"

export AGY_CLI_DISABLE_AUTO_UPDATE=true

session_status=0
"$binary" "$@" || session_status=$?

if ! "$secure_state"; then
  echo "ERROR: failed to secure persistent state after Antigravity exited" >&2
  exit 1
fi

exit "$session_status"
