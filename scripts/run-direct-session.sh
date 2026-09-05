#!/usr/bin/env bash
set -euo pipefail

readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
readonly secure_state=/usr/local/bin/secure-persistent-state

if (( $# == 0 )); then
  echo "Usage: run-direct-session <command> [args...]" >&2
  exit 2
fi

[[ -f "$runtime_lib" && -r "$runtime_lib" && ! -L "$runtime_lib" ]] \
  || { echo "ERROR: Remote Dev role definitions are unavailable" >&2; exit 1; }
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"

harden_state_on_exit() {
  local session_status=$?

  trap - EXIT
  # The interactive command may remove or replace its own project directory.
  # Recover with a shell builtin before spawning any post-session helper so
  # Bash never initializes a child process from a deleted cwd.
  if ! remote_dev_recover_safe_cwd; then
    echo "ERROR: failed to recover a safe current directory after direct session" >&2
    exit 1
  fi
  if ! "$secure_state"; then
    echo "ERROR: failed to secure persistent credential state after direct session" >&2
    exit 1
  fi

  exit "$session_status"
}

trap harden_state_on_exit EXIT
"$@"
