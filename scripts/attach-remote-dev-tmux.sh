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
    session_command="cd $quoted_workspace && exec codex"
    ;;
  shell)
    printf -v quoted_workspace '%q' "$workspace"
    session_command="cd $quoted_workspace && exec bash --login"
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

if "${tmux_cmd[@]}" has-session -t "=$session" 2>/dev/null; then
  active_window="$("${tmux_cmd[@]}" display-message -p -t "=$session" '#{window_id}')"
  "${tmux_cmd[@]}" rename-window -t "$active_window" "$window_name"

  if [[ "${REMOTE_DEV_TMUX_DETACHED:-0}" == "1" ]]; then
    exit 0
  fi

  exec "${tmux_cmd[@]}" attach-session -t "=$session"
fi

new_session=(new-session)
if [[ "${REMOTE_DEV_TMUX_DETACHED:-0}" == "1" ]]; then
  new_session+=(-d)
fi
new_session+=(-s "$session" -n "$window_name" "$session_command")

if [[ "${REMOTE_DEV_TMUX_DETACHED:-0}" == "1" ]]; then
  "${tmux_cmd[@]}" "${new_session[@]}"
  exit 0
fi

exec "${tmux_cmd[@]}" "${new_session[@]}"
