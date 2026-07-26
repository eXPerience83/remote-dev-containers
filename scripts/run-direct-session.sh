#!/usr/bin/env bash
set -euo pipefail

if (( $# == 0 )); then
  echo "Usage: run-direct-session <command> [args...]" >&2
  exit 2
fi

harden_state_on_exit() {
  local session_status=$?

  trap - EXIT
  if ! /usr/local/bin/secure-persistent-state; then
    echo "ERROR: failed to secure persistent credential state after direct session" >&2
    exit 1
  fi

  exit "$session_status"
}

trap harden_state_on_exit EXIT
"$@"
