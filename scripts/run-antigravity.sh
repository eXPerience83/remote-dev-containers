#!/usr/bin/env bash
set -euo pipefail

readonly manager=/usr/local/bin/remote-dev-antigravity
readonly secure_state=/usr/local/bin/secure-persistent-state
readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh

[[ -f "$runtime_lib" && -r "$runtime_lib" && ! -L "$runtime_lib" ]] \
  || { echo "ERROR: Remote Dev role definitions are unavailable" >&2; exit 1; }
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"
resolved_role="$(remote_dev_resolve_role)" || exit $?
if [[ "$resolved_role" != antigravity ]]; then
  echo "ERROR: run-antigravity requires the gated REMOTE_DEV_ROLE=antigravity service" >&2
  exit 2
fi
export REMOTE_DEV_ROLE="$resolved_role"

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
[[ -d "$workspace" ]] || { echo "ERROR: WORKSPACE does not exist: $workspace" >&2; exit 2; }

current="$workspace"
previous=""
while [[ "$current" != / && "$current" != "$previous" ]]; do
  [[ ! -L "$current" ]] || { echo "ERROR: WORKSPACE contains a symlinked path component: $current" >&2; exit 2; }
  previous="$current"
  current="$(dirname "$current")"
done
cd "$workspace"

export AGY_CLI_DISABLE_AUTO_UPDATE=true

child_pid=""
harden_on_exit() {
  local session_status=$?
  trap - EXIT INT TERM
  if ! "$secure_state"; then
    echo "ERROR: failed to secure persistent state after Antigravity exited" >&2
    exit 1
  fi
  exit "$session_status"
}

forward_signal() {
  local signal_name="$1"
  local signal_status="$2"
  if [[ -n "$child_pid" ]] && kill -0 "$child_pid" 2>/dev/null; then
    kill -s "$signal_name" "$child_pid" 2>/dev/null || true
    wait "$child_pid" 2>/dev/null || true
  fi
  child_pid=""
  exit "$signal_status"
}

trap harden_on_exit EXIT
trap 'forward_signal INT 130' INT
trap 'forward_signal TERM 143' TERM

# Bash redirects stdin for asynchronous commands and makes them ignore INT/QUIT
# when job control is disabled. Preserve fd 0 explicitly and reset those signal
# dispositions before execing the interactive vendor CLI.
env --default-signal=INT,TERM,QUIT -- "$binary" "$@" <&0 &
child_pid=$!
session_status=0
wait "$child_pid" || session_status=$?
child_pid=""
exit "$session_status"
