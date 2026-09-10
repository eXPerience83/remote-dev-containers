#!/usr/bin/env bash
set -euo pipefail

readonly manager=/usr/local/bin/remote-dev-antigravity
readonly policy_helper=/usr/local/bin/remote-dev-antigravity-policy
readonly oauth_helper=/usr/local/bin/remote-dev-antigravity-oauth
readonly picker_helper=/usr/local/bin/remote-dev-antigravity-picker
readonly secure_state=/usr/local/bin/secure-persistent-state
readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
readonly default_approval_mode=autonomous

fail_usage() {
  printf 'ERROR: %s\n' "$1" >&2
  printf 'Usage: run-antigravity [--approval-mode autonomous|guarded] [--print-policy] [--] [agy arguments...]\n' >&2
  exit 2
}

validate_approval_mode() {
  local mode="$1"
  local source="$2"
  case "$mode" in
    autonomous|guarded) ;;
    *) fail_usage "unsupported $source approval mode: $mode (autonomous|guarded)" ;;
  esac
}

reject_policy_override() {
  local argument="$1"
  echo "ERROR: run-antigravity owns the approval policy; refusing argument: $argument" >&2
  exit 2
}

open_resume_picker=0
explicit_mode=""
explicit_mode_set=0
print_policy=0
forwarded=()

while (( $# > 0 )); do
  argument="$1"
  shift
  case "$argument" in
    --remote-dev-open-resume-picker)
      (( open_resume_picker == 0 )) || fail_usage "--remote-dev-open-resume-picker may be specified only once"
      open_resume_picker=1
      ;;
    --approval-mode)
      (( explicit_mode_set == 0 )) || fail_usage "--approval-mode may be specified only once"
      (( $# > 0 )) || fail_usage "--approval-mode requires autonomous or guarded"
      [[ "$1" != -- ]] || fail_usage "--approval-mode requires autonomous or guarded"
      explicit_mode="$1"
      explicit_mode_set=1
      shift
      ;;
    --approval-mode=*)
      (( explicit_mode_set == 0 )) || fail_usage "--approval-mode may be specified only once"
      explicit_mode="${argument#*=}"
      [[ -n "$explicit_mode" ]] || fail_usage "--approval-mode requires autonomous or guarded"
      explicit_mode_set=1
      ;;
    --print-policy)
      (( print_policy == 0 )) || fail_usage "--print-policy may be specified only once"
      print_policy=1
      ;;
    --)
      forwarded+=(-- "$@")
      break
      ;;
    *)
      forwarded+=("$argument")
      ;;
  esac
done

approval_mode=""
mode_source=""
if (( explicit_mode_set == 1 )); then
  validate_approval_mode "$explicit_mode" per-launch
  approval_mode="$explicit_mode"
  mode_source=per-launch
elif [[ -n "${REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE:-}" ]]; then
  validate_approval_mode "$REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE" deployment
  approval_mode="$REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE"
  mode_source=deployment
else
  approval_mode="$default_approval_mode"
  mode_source=default
fi
readonly approval_mode mode_source

for argument in "${forwarded[@]}"; do
  case "$argument" in
    --dangerously-skip-permissions|--dangerously-skip-permissions=*)
      reject_policy_override "$argument"
      ;;
  esac
done

if (( print_policy == 1 )) && (( ${#forwarded[@]} > 0 || open_resume_picker == 1 )); then
  fail_usage "--print-policy cannot be combined with Antigravity arguments or picker actions"
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

if (( print_policy == 1 )); then
  printf '%s\n' \
    'Inner sandbox: not managed by approval mode' \
    'Isolation boundary: outer container' \
    "Antigravity approval mode: $approval_mode"
  if [[ "$approval_mode" == autonomous ]]; then
    echo 'Approval behavior: vendor permission/review bypass for this launch'
  else
    echo 'Approval behavior: vendor request/review semantics'
  fi
  echo "Mode source: $mode_source"
  if [[ -x "$policy_helper" && ! -L "$policy_helper" ]]; then
    policy_output=""
    policy_status=0
    policy_output="$("$policy_helper" status 2>&1)" || policy_status=$?
    if [[ -n "$policy_output" ]]; then
      printf '%s\n' "$policy_output"
    else
      echo "Antigravity guarded compatibility: unavailable (exit $policy_status)"
    fi
  else
    echo 'Antigravity guarded compatibility: unavailable (policy helper missing)'
  fi
  exit 0
fi

[[ -x "$manager" ]] || { echo "ERROR: Antigravity runtime manager is unavailable" >&2; exit 1; }
[[ -x "$secure_state" ]] || { echo "ERROR: persistent-state hardening command is unavailable" >&2; exit 1; }
[[ -x "$policy_helper" && ! -L "$policy_helper" ]] \
  || { echo "ERROR: Antigravity approval-policy helper is unavailable" >&2; exit 1; }
if (( open_resume_picker )); then
  [[ "${TMUX_PANE:-}" =~ ^%[0-9]+$ ]] \
    || { echo "ERROR: the Antigravity conversation picker requires a tmux pane" >&2; exit 2; }
  [[ -x "$picker_helper" ]] \
    || { echo "ERROR: Antigravity conversation-picker helper is unavailable" >&2; exit 1; }
fi

if [[ "$approval_mode" == guarded ]]; then
  guarded_output=""
  guarded_status=0
  guarded_output="$("$policy_helper" check-guarded 2>&1)" || guarded_status=$?
  if (( guarded_status != 0 )); then
    echo "ERROR: Remote Dev cannot guarantee guarded Antigravity semantics with the current vendor settings." >&2
    [[ -z "$guarded_output" ]] || printf '%s\n' "$guarded_output" >&2
    if (( guarded_status == 3 )); then
      echo "Run 'remote-dev-antigravity-policy repair-guarded --yes' explicitly, or change the vendor approval settings manually." >&2
    fi
    exit 2
  fi
fi

binary="$("$manager" path)"
if [[ ! -f "$binary" || -L "$binary" || ! -x "$binary" ]]; then
  cat >&2 <<EOF
ERROR: Antigravity is absent, damaged or incomplete at the canonical path:
  $binary
Run remote-dev-update-antigravity to repair existing state, or
remote-dev-install-antigravity for a first installation.
EOF
  exit 1
fi

# Fully verify the canonical executable once against its private manifest
# before a real session. Verification is offline and never executes vendor code.
verify_output=""
verify_result=0
verify_output="$("$manager" verify 2>&1)" || verify_result=$?
if (( verify_result != 0 )); then
  echo "ERROR: Antigravity runtime verification failed: $verify_output" >&2
  echo "Run remote-dev-update-antigravity explicitly to repair or replace the installation." >&2
  exit "$verify_result"
fi

workspace="$(remote_dev_workspace_root)" || exit $?
project="$(remote_dev_resolve_project "$workspace")" || exit $?
remote_dev_enter_project "$workspace" "$project" || exit $?
entered_project_identity="$(stat -Lc '%d:%i' -- . 2>/dev/null)" || {
  remote_dev_runtime_error "project path changed after entering Antigravity project: $project"
  remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
  exit 2
}
entered_project_path_identity="$(stat -Lc '%d:%i' -- "$project" 2>/dev/null)" || {
  remote_dev_runtime_error "project path changed after entering Antigravity project: $project"
  remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
  exit 2
}
if [[ "$entered_project_identity" != "$entered_project_path_identity" ]]; then
  remote_dev_runtime_error "project path changed after entering Antigravity project: $project"
  remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
  exit 2
fi

export AGY_CLI_DISABLE_AUTO_UPDATE=true

owned_policy_args=()
if [[ "$approval_mode" == autonomous ]]; then
  owned_policy_args+=(--dangerously-skip-permissions)
fi

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
  if ! remote_dev_recover_safe_cwd; then
    echo "ERROR: failed to recover a safe current directory after Antigravity exited" >&2
    exit 1
  fi
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

assert_entered_project_identity() {
  local current_identity=""
  local path_identity=""

  current_identity="$(stat -Lc '%d:%i' -- . 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed before Antigravity vendor launch: $project"
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  }
  path_identity="$(stat -Lc '%d:%i' -- "$project" 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed before Antigravity vendor launch: $project"
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  }
  if [[ "$current_identity" != "$entered_project_identity" \
     || "$path_identity" != "$entered_project_identity" ]]; then
    remote_dev_runtime_error "project path changed before Antigravity vendor launch: $project"
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  fi

  # Identity alone is insufficient because stat -L follows a replacement
  # symlink back to the original inode. Re-apply the complete direct-child/Git
  # boundary, then repeat the inode check so a swap during that validation also
  # fails closed.
  if ! remote_dev_assert_project_git_boundary "$workspace" "$project"; then
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  fi
  current_identity="$(stat -Lc '%d:%i' -- . 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed before Antigravity vendor launch: $project"
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  }
  path_identity="$(stat -Lc '%d:%i' -- "$project" 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed before Antigravity vendor launch: $project"
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  }
  if [[ "$current_identity" != "$entered_project_identity" \
     || "$path_identity" != "$entered_project_identity" ]]; then
    remote_dev_runtime_error "project path changed before Antigravity vendor launch: $project"
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  fi
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

# Revalidate the selected project after the prelaunch helpers have finished. A
# concurrent replacement must not make Remote Dev validate one directory while
# the vendor process inherits another directory inode as its cwd.
assert_entered_project_identity || exit $?

# Bash redirects stdin for asynchronous commands and makes them ignore INT/QUIT
# when job control is disabled. Preserve fd 0 explicitly and reset those signal
# dispositions before execing the interactive vendor CLI.
env --default-signal=INT,TERM,QUIT -- "$binary" "${owned_policy_args[@]}" "${forwarded[@]}" <&0 &
child_pid=$!
start_picker_helper
session_status=0
wait "$child_pid" || session_status=$?
child_pid=""
stop_auxiliary_helpers
exit "$session_status"
