#!/usr/bin/env bash
set -euo pipefail

runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"

role="$(remote_dev_resolve_role)"
export REMOTE_DEV_ROLE="$role"
cd "${WORKSPACE:-/workspace}"

harden_state_or_exit() {
  if ! /usr/local/bin/secure-persistent-state; then
    echo "ERROR: failed to secure persistent credential state" >&2
    exit 1
  fi
}

report_action_failure() {
  local label="$1"
  local action_status="$2"

  echo >&2
  echo "ERROR: $label exited with status $action_status" >&2
  read -r -p "Press Enter to return to the menu..." _
}

run_interactive_and_harden() {
  local label="$1"
  shift
  local action_status=0

  clear
  "$@" || action_status=$?
  harden_state_or_exit

  if (( action_status != 0 )); then
    report_action_failure "$label" "$action_status"
  fi

  return "$action_status"
}

run_github_login() {
  local action_status=0

  clear
  if gh auth login --hostname "${GH_HOST:-github.com}" --git-protocol https --web; then
    if gh auth setup-git; then
      :
    else
      action_status=$?
      echo "ERROR: GitHub authentication succeeded, but Git credential setup failed" >&2
    fi
  else
    action_status=$?
    echo "ERROR: GitHub CLI authentication failed or was cancelled" >&2
  fi

  harden_state_or_exit

  if (( action_status != 0 )); then
    report_action_failure "GitHub CLI setup" "$action_status"
  fi

  return "$action_status"
}

run_diagnostics() {
  local doctor_status=0

  clear
  /usr/local/bin/remote-dev-doctor || doctor_status=$?
  if (( doctor_status != 0 )); then
    echo >&2
    echo "ERROR: diagnostics reported one or more failures (status $doctor_status)" >&2
  fi
  read -r -p "Press Enter to continue..." _
}

if remote-dev-version --check >/dev/null 2>&1; then
  version_summary="$(remote-dev-version --menu)"
else
  version_summary="Image metadata unavailable"
fi

show_codex_menu() {
  while true; do
    clear
    cat <<MENU
Remote Dev — Codex
${version_summary}
==================
1) Start Codex
2) Resume a Codex session
3) Sign in to Codex with device code
4) Sign in to GitHub CLI
5) Run diagnostics
6) Open a login shell
7) Exit this tmux session
MENU
    read -r -p "> " choice
    case "$choice" in
      1)
        if run_interactive_and_harden "Codex" /usr/local/bin/run-codex; then :; fi
        ;;
      2)
        if run_interactive_and_harden "Codex resume" /usr/local/bin/run-codex resume; then :; fi
        ;;
      3)
        if run_interactive_and_harden "Codex login" codex login --device-auth; then :; fi
        ;;
      4)
        if run_github_login; then :; fi
        ;;
      5)
        run_diagnostics
        ;;
      6)
        if run_interactive_and_harden "Login shell" bash --login; then :; fi
        ;;
      7)
        exit 0
        ;;
      *)
        sleep 1
        ;;
    esac
  done
}

show_shell_menu() {
  while true; do
    clear
    cat <<MENU
Remote Dev — Shell
${version_summary}
==================
1) Open a login shell
2) Sign in to GitHub CLI
3) Run diagnostics
4) Exit this tmux session
MENU
    read -r -p "> " choice
    case "$choice" in
      1)
        if run_interactive_and_harden "Login shell" bash --login; then :; fi
        ;;
      2)
        if run_github_login; then :; fi
        ;;
      3)
        run_diagnostics
        ;;
      4)
        exit 0
        ;;
      *)
        sleep 1
        ;;
    esac
  done
}

case "$role" in
  codex) show_codex_menu ;;
  shell) show_shell_menu ;;
  *)
    echo "ERROR: internal unsupported menu role: $role" >&2
    exit 2
    ;;
esac
