#!/usr/bin/env bash
set -euo pipefail

cd "${WORKSPACE:-/workspace}"

while true; do
  clear
  cat <<'MENU'
Codex Remote Dev
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
    1) codex ;;
    2) codex resume ;;
    3) codex login --device-auth ;;
    4)
      gh auth login --hostname "${GH_HOST:-github.com}" --git-protocol https --web
      gh auth setup-git || true
      ;;
    5) codex-doctor; read -r -p "Press Enter to continue..." _ ;;
    6) bash --login ;;
    7) exit 0 ;;
    *) sleep 1 ;;
  esac
done
