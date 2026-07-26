#!/usr/bin/env bash
set -euo pipefail

session="${TMUX_SESSION:-codex}"
window_name=remote-dev
workspace="${WORKSPACE:-/workspace}"

if [[ -z "$session" ]]; then
  echo "ERROR: TMUX_SESSION must not be empty" >&2
  exit 2
fi

case "${START_MODE:-menu}" in
  menu)
    session_command=/usr/local/bin/codex-menu
    ;;
  codex)
    printf -v quoted_workspace '%q' "$workspace"
    session_command="cd $quoted_workspace && exec /usr/local/bin/run-direct-session codex"
    ;;
  shell)
    printf -v quoted_workspace '%q' "$workspace"
    session_command="cd $quoted_workspace && exec /usr/local/bin/run-direct-session bash --login"
    ;;
  *)
    echo "ERROR: unsupported START_MODE=${START_MODE:-unset} (menu|codex|shell)" >&2
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
