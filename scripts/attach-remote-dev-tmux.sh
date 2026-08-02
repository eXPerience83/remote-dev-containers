#!/usr/bin/env bash
set -euo pipefail

runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"

role="$(remote_dev_resolve_role)"
start_mode="$(remote_dev_resolve_start_mode "$role")"
export REMOTE_DEV_ROLE="$role"
export REMOTE_DEV_START_MODE="$start_mode"

session="${TMUX_SESSION:-$(remote_dev_default_tmux_session "$role")}"
window_name=remote-dev
workspace="${WORKSPACE:-/workspace}"
readonly run_codex_binary=/usr/local/bin/run-codex
readonly run_antigravity_binary=/usr/local/bin/run-antigravity

if [[ -z "$session" ]]; then
  echo "ERROR: TMUX_SESSION must not be empty" >&2
  exit 2
fi

case "$start_mode" in
  menu)
    session_command=/usr/local/bin/remote-dev-menu
    ;;
  agent)
    printf -v quoted_workspace '%q' "$workspace"
    case "$role" in
      codex)
        printf -v quoted_agent_binary '%q' "$run_codex_binary"
        session_command="cd $quoted_workspace && exec /usr/local/bin/run-direct-session $quoted_agent_binary"
        ;;
      antigravity)
        printf -v quoted_agent_binary '%q' "$run_antigravity_binary"
        session_command="cd $quoted_workspace && exec $quoted_agent_binary"
        ;;
      *)
        echo "ERROR: direct agent mode is not implemented for REMOTE_DEV_ROLE=$role" >&2
        exit 2
        ;;
    esac
    ;;
  shell)
    printf -v quoted_workspace '%q' "$workspace"
    session_command="cd $quoted_workspace && exec /usr/local/bin/run-direct-session bash --login"
    ;;
  *)
    echo "ERROR: internal unsupported start mode: $start_mode" >&2
    exit 2
    ;;
esac

tmux_cmd=(tmux)
if [[ -n "${TMUX_SOCKET_NAME:-}" ]]; then
  tmux_cmd+=(-L "$TMUX_SOCKET_NAME")
fi

create_error=""
if ! create_error="$("${tmux_cmd[@]}" new-session -d -s "$session" -n "$window_name" "$session_command" 2>&1)"; then
  if ! "${tmux_cmd[@]}" has-session -t "=$session" 2>/dev/null; then
    echo "ERROR: failed to create tmux session $session" >&2
    [[ -n "$create_error" ]] && printf '%s\n' "$create_error" >&2
    exit 1
  fi
fi

active_window="$("${tmux_cmd[@]}" display-message -p -t "=$session:" '#{window_id}')"
if [[ -z "$active_window" ]]; then
  echo "ERROR: tmux session $session has no active window" >&2
  exit 1
fi
"${tmux_cmd[@]}" rename-window -t "$active_window" "$window_name"

if [[ "${REMOTE_DEV_TMUX_DETACHED:-0}" == "1" ]]; then
  exit 0
fi

exec "${tmux_cmd[@]}" attach-session -t "=$session"
