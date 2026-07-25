#!/usr/bin/env bash
set -euo pipefail

cd "${WORKSPACE:-/workspace}"

run_interactive_and_harden() {
  clear
  "$@" || true
  /usr/local/bin/secure-persistent-state
}

while true; do
  version_summary="$(remote-dev-version --menu 2>/dev/null || printf 'Image metadata unavailable')"
  clear
  cat <<MENU
Codex Remote Dev
${version_summary}
================
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
      run_interactive_and_harden codex
      ;;
    2)
      run_interactive_and_harden codex resume
      ;;
    3)
      run_interactive_and_harden codex login --device-auth
      ;;
    4)
      clear
      if gh auth login --hostname "${GH_HOST:-github.com}" --git-protocol https --web; then
        gh auth setup-git || true
      fi
      /usr/local/bin/secure-persistent-state
      ;;
    5)
      clear
      codex-doctor
      read -r -p "Press Enter to continue..." _
      ;;
    6)
      run_interactive_and_harden bash --login
      ;;
    7)
      exit 0
      ;;
    *)
      sleep 1
      ;;
  esac
done
