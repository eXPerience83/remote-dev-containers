#!/usr/bin/env bash
set -euo pipefail

readonly DEFAULT_MANAGER=/usr/local/bin/remote-dev-antigravity
readonly DEFAULT_SECURE_STATE=/usr/local/bin/secure-persistent-state

testing=0
if [[ "${REMOTE_DEV_ANTIGRAVITY_TESTING:-0}" == "1" ]]; then
  testing=1
  manager="${REMOTE_DEV_ANTIGRAVITY_MANAGER:-$DEFAULT_MANAGER}"
  secure_state="${REMOTE_DEV_SECURE_STATE:-$DEFAULT_SECURE_STATE}"
else
  manager="$DEFAULT_MANAGER"
  secure_state="$DEFAULT_SECURE_STATE"
fi

[[ -x "$manager" ]] || { echo "ERROR: Antigravity runtime manager is unavailable" >&2; exit 1; }
[[ -x "$secure_state" ]] || { echo "ERROR: persistent-state hardening command is unavailable" >&2; exit 1; }

binary="$("$manager" path)"
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
status_output=""
status_result=0
status_output="$("$manager" status 2>&1)" || status_result=$?
if (( status_result != 0 )); then
  echo "ERROR: Antigravity runtime verification failed: $status_output" >&2
  echo "Run remote-dev-update-antigravity to install the reviewed version." >&2
  exit "$status_result"
fi

workspace="${WORKSPACE:-/workspace}"
[[ "$workspace" == /* && "$workspace" != //* && "$workspace" != *$'\n'* \
   && "$workspace" != *'/../'* && "$workspace" != */.. ]] \
  || { echo "ERROR: WORKSPACE must be a safe absolute path" >&2; exit 2; }
case "$workspace" in
  /|/root|/home|/opt|/usr|/usr/local|/etc|/var|/tmp)
    echo "ERROR: WORKSPACE is too broad: $workspace" >&2
    exit 2
    ;;
esac
if (( testing == 1 )); then
  mkdir -p "$workspace"
else
  [[ -d "$workspace" ]] || { echo "ERROR: WORKSPACE does not exist: $workspace" >&2; exit 2; }
fi

current="$workspace"
previous=""
while [[ "$current" != / && "$current" != "$previous" ]]; do
  [[ ! -L "$current" ]] || { echo "ERROR: WORKSPACE contains a symlinked path component: $current" >&2; exit 2; }
  previous="$current"
  current="$(dirname "$current")"
done
cd "$workspace"

export AGY_CLI_DISABLE_AUTO_UPDATE=true

harden_on_exit() {
  local session_status=$?
  trap - EXIT INT TERM
  if ! "$secure_state"; then
    echo "ERROR: failed to secure persistent state after Antigravity exited" >&2
    exit 1
  fi
  exit "$session_status"
}
trap harden_on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"$binary" "$@"
