#!/usr/bin/env bash
set -euo pipefail

readonly manager=/usr/local/bin/remote-dev-antigravity
readonly oauth_helper=/usr/local/bin/remote-dev-antigravity-oauth
readonly picker_helper=/usr/local/bin/remote-dev-antigravity-picker
readonly secure_state=/usr/local/bin/secure-persistent-state
readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh

open_resume_picker=0
if [[ "${1:-}" == --remote-dev-open-resume-picker ]]; then
  open_resume_picker=1
  shift
fi

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
if (( open_resume_picker )); then
  [[ "${TMUX_PANE:-}" =~ ^%[0-9]+$ ]] \
    || { echo "ERROR: the Antigravity conversation picker requires a tmux pane" >&2; exit 2; }
  [[ -x "$picker_helper" ]] \
    || { echo "ERROR: Antigravity conversation-picker helper is unavailable" >&2; exit 1; }
fi

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
oauth_helper_pid=""
oauth_ready_file=""
picker_helper_pid=""
picker_baseline_sha256=""

stop_oauth_helper() {
  if [[ -n "$oauth_helper_pid" ]] && kill -0 "$oauth_helper_pid" 2>/dev/null; then
    kill "$oauth_helper_pid" 2>/dev/null || true
    # The helper may be waiting for an interactive tmux popup. Give it enough
    # time to close the popup and unlink the private OAuth URL before SIGKILL.
    for _ in {1..100}; do
      kill -0 "$oauth_helper_pid" 2>/dev/null || break
      sleep 0.05
    done
    if kill -0 "$oauth_helper_pid" 2>/dev/null; then
      kill -KILL "$oauth_helper_pid" 2>/dev/null || true
    fi
    wait "$oauth_helper_pid" 2>/dev/null || true
  fi
  oauth_helper_pid=""
  if [[ -n "$oauth_ready_file" ]]; then
    rm -f -- "$oauth_ready_file"
  fi
  oauth_ready_file=""
}

stop_picker_helper() {
  if [[ -n "$picker_helper_pid" ]] && kill -0 "$picker_helper_pid" 2>/dev/null; then
    kill "$picker_helper_pid" 2>/dev/null || true
    wait "$picker_helper_pid" 2>/dev/null || true
  fi
  picker_helper_pid=""
}

stop_auxiliary_helpers() {
  stop_picker_helper
  stop_oauth_helper
}

start_oauth_helper() {
  if [[ "${REMOTE_DEV_ANTIGRAVITY_OAUTH_HELPER:-1}" != 1 ]]; then
    return 0
  fi
  if [[ -z "${TMUX_PANE:-}" || ! "$TMUX_PANE" =~ ^%[0-9]+$ ]]; then
    return 0
  fi
  if [[ ! -x "$oauth_helper" ]]; then
    echo "WARNING: Antigravity OAuth link helper is unavailable" >&2
    return 0
  fi

  oauth_ready_file="/tmp/.remote-dev-antigravity-oauth-ready.$$"
  rm -f -- "$oauth_ready_file"
  local -a oauth_command=(
    "$oauth_helper"
    watch
    --pane "$TMUX_PANE"
    --ready-file "$oauth_ready_file"
  )
  "${oauth_command[@]}" &
  oauth_helper_pid=$!

  # capture_pane() has a three-second deadline. Allow that full interval plus
  # one second of scheduler/startup margin before falling back to the vendor UI.
  for _ in {1..80}; do
    if [[ -f "$oauth_ready_file" ]]; then
      rm -f -- "$oauth_ready_file"
      oauth_ready_file=""
      return 0
    fi
    if ! kill -0 "$oauth_helper_pid" 2>/dev/null; then
      wait "$oauth_helper_pid" 2>/dev/null || true
      oauth_helper_pid=""
      rm -f -- "$oauth_ready_file"
      oauth_ready_file=""
      echo "WARNING: Antigravity OAuth link helper did not initialize" >&2
      return 0
    fi
    sleep 0.05
  done

  echo "WARNING: Antigravity OAuth link helper timed out during initialization" >&2
  stop_oauth_helper
}

capture_picker_baseline() {
  (( open_resume_picker )) || return 0
  if ! picker_baseline_sha256="$(
    "$picker_helper" snapshot --pane "$TMUX_PANE"
  )"; then
    echo "ERROR: unable to capture the tmux pane before starting Antigravity" >&2
    exit 1
  fi
  [[ "$picker_baseline_sha256" =~ ^[0-9a-f]{64}$ ]] \
    || { echo "ERROR: Antigravity picker returned an invalid screen baseline" >&2; exit 1; }
}

start_picker_helper() {
  (( open_resume_picker )) || return 0
  "$picker_helper" watch \
    --pane "$TMUX_PANE" \
    --pid "$child_pid" \
    --baseline-sha256 "$picker_baseline_sha256" &
  picker_helper_pid=$!
}

harden_on_exit() {
  local session_status=$?
  trap - EXIT INT TERM
  stop_auxiliary_helpers
  if ! "$secure_state"; then
    echo "ERROR: failed to secure persistent state after Antigravity exited" >&2
    exit 1
  fi
  exit "$session_status"
}

forward_signal() {
  local signal_name="$1"
  local signal_status="$2"
  stop_auxiliary_helpers
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

# Start the OAuth watcher before the vendor process so it can capture a new
# authorization URL without reusing stale terminal content.
start_oauth_helper
# Record the current visible pane before Antigravity starts. The picker helper
# accepts its prompt only after the screen has changed from this baseline.
capture_picker_baseline

# Bash redirects stdin for asynchronous commands and makes them ignore INT/QUIT
# when job control is disabled. Preserve fd 0 explicitly and reset those signal
# dispositions before execing the interactive vendor CLI.
env --default-signal=INT,TERM,QUIT -- "$binary" "$@" <&0 &
child_pid=$!
start_picker_helper
session_status=0
wait "$child_pid" || session_status=$?
child_pid=""
stop_auxiliary_helpers
exit "$session_status"
