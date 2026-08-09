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

codex_policy_summary() {
  /usr/local/bin/run-codex --print-policy \
    | grep -E '^(Codex approval mode|Codex approval policy|Mode source):'
}

codex_runtime_status_summary() {
  local summary="" status=0
  local -a runtime_manager_command=(
    /usr/local/bin/remote-dev-codex-runtime status --menu
  )
  summary="$("${runtime_manager_command[@]}" 2>&1)" || status=$?
  if [[ -n "$summary" ]]; then
    printf '%s\n' "$summary"
  else
    printf 'Codex runtime: status unavailable (exit %s)\n' "$status"
  fi
}

context7_status_summary() {
  local summary="" status=0
  local -a context7_status_command=(
    /usr/local/bin/remote-dev-context7 status --menu
  )
  summary="$("${context7_status_command[@]}" 2>&1)" || status=$?
  if [[ -n "$summary" ]]; then
    printf '%s\n' "$summary"
  else
    printf 'Context7: status unavailable (exit %s)\n' "$status"
  fi
}

configured_codex_mode=""
policy_summary=""
refresh_codex_policy() {
  policy_summary="$(codex_policy_summary)"
  configured_codex_mode="$(
    sed -n 's/^Codex approval mode: //p' <<<"$policy_summary"
  )"
  case "$configured_codex_mode" in
    autonomous|guarded) ;;
    *)
      echo "ERROR: unable to resolve the configured Codex approval mode" >&2
      exit 1
      ;;
  esac
}

next_codex_mode=""
choose_next_codex_mode() {
  clear
  cat <<MENU
Approval mode for next launch
=============================
1) Use configured mode — ${configured_codex_mode}
2) Autonomous — no confirmations
3) Guarded — asks for confirmations
4) Back
MENU
  read -r -p "> " choice
  case "$choice" in
    1) next_codex_mode="" ;;
    2) next_codex_mode=autonomous ;;
    3) next_codex_mode=guarded ;;
    4) return 1 ;;
    *)
      sleep 1
      return 1
      ;;
  esac
}

next_codex_mode_summary() {
  if [[ -n "$next_codex_mode" ]]; then
    printf 'Next launch mode: %s (one launch)\n' "$next_codex_mode"
  else
    printf 'Next launch mode: configured (%s)\n' "$configured_codex_mode"
  fi
}

run_codex_action() {
  local label="$1"
  shift
  local launch_mode="$next_codex_mode"
  local -a command=(/usr/local/bin/run-codex)

  next_codex_mode=""
  if [[ -n "$launch_mode" ]]; then
    command+=(--approval-mode "$launch_mode")
    label+=" ($launch_mode)"
  fi
  command+=("$@")

  run_interactive_and_harden "$label" "${command[@]}"
}

show_context7_menu() {
  local status_summary=""
  local -a context7_install_command=(/usr/local/bin/remote-dev-context7 install)
  local -a context7_test_command=(/usr/local/bin/remote-dev-context7 test)
  local -a context7_update_command=(/usr/local/bin/remote-dev-context7 update)
  local -a context7_remove_command=(/usr/local/bin/remote-dev-context7 remove)

  while true; do
    status_summary="$(context7_status_summary)"
    clear
    cat <<MENU
Remote Dev — Codex — Context7
${status_summary}
=============================
Context7 is an optional external Upstash service.
Configuration/status are offline; only Test performs an explicit network check.
1) Install / repair hosted Context7 MCP integration
2) Test bundled Codex config and Context7 hosted endpoint
3) Update / reapply reviewed hosted integration contract
4) Remove Remote Dev-managed Context7 integration
5) Back
MENU
    read -r -p "> " choice
    case "$choice" in
      1)
        if run_interactive_and_harden "Context7 install/repair" "${context7_install_command[@]}"; then :; fi
        ;;
      2)
        if run_interactive_and_harden "Context7 connection test" "${context7_test_command[@]}"; then :; fi
        ;;
      3)
        if run_interactive_and_harden "Context7 contract update" "${context7_update_command[@]}"; then :; fi
        ;;
      4)
        if run_interactive_and_harden "Context7 removal" "${context7_remove_command[@]}"; then :; fi
        ;;
      5)
        return 0
        ;;
      *)
        sleep 1
        ;;
    esac
  done
}

antigravity_status_summary() {
  local summary="" status=0
  summary="$(/usr/local/bin/remote-dev-antigravity status --menu 2>&1)" || status=$?
  if [[ -n "$summary" ]]; then
    printf '%s\n' "$summary"
  else
    printf 'Antigravity: status unavailable (exit %s)\n' "$status"
  fi
}

if remote-dev-version --check >/dev/null 2>&1; then
  version_summary="$(remote-dev-version --menu)"
else
  version_summary="Image metadata unavailable"
fi

show_codex_menu() {
  local next_mode_summary="" runtime_summary="" context7_summary=""

  while true; do
    refresh_codex_policy
    next_mode_summary="$(next_codex_mode_summary)"
    runtime_summary="$(codex_runtime_status_summary)"
    context7_summary="$(context7_status_summary)"
    clear
    cat <<MENU
Remote Dev — Codex
${version_summary}
${runtime_summary}
${context7_summary}
${policy_summary}
${next_mode_summary}
==================
1) Start Codex
2) Resume a Codex session
3) Approval mode for next launch...
4) Update optional Codex runtime from official OpenAI release
5) Remove optional Codex runtime (use bundled fallback)
6) Context7 integration...
7) Sign in to Codex with device code
8) Sign in to GitHub CLI
9) Run diagnostics
10) Open a login shell
11) Exit this tmux session
MENU
    read -r -p "> " choice
    case "$choice" in
      1)
        if run_codex_action "Codex"; then :; fi
        ;;
      2)
        if run_codex_action "Codex resume" resume; then :; fi
        ;;
      3)
        if choose_next_codex_mode; then :; fi
        ;;
      4)
        if run_interactive_and_harden "Codex runtime update" /usr/local/bin/remote-dev-codex-runtime update; then :; fi
        ;;
      5)
        if run_interactive_and_harden "Codex runtime removal" /usr/local/bin/remote-dev-codex-runtime remove; then :; fi
        ;;
      6)
        show_context7_menu
        ;;
      7)
        if run_interactive_and_harden "Codex login" codex login --device-auth; then :; fi
        ;;
      8)
        if run_github_login; then :; fi
        ;;
      9)
        run_diagnostics
        ;;
      10)
        if run_interactive_and_harden "Login shell" bash --login; then :; fi
        ;;
      11)
        exit 0
        ;;
      *)
        sleep 1
        ;;
    esac
  done
}

show_antigravity_menu() {
  local status_summary=""

  while true; do
    status_summary="$(antigravity_status_summary)"
    clear
    cat <<MENU
Remote Dev — Antigravity
${version_summary}
${status_summary}
========================
1) Start Antigravity
2) Resume an Antigravity session
3) Install Antigravity from Google
4) Update Antigravity from Google
5) Sign in to GitHub CLI
6) Run diagnostics
7) Open a login shell
8) Exit this tmux session
MENU
    read -r -p "> " choice
    case "$choice" in
      1)
        if run_interactive_and_harden "Antigravity" /usr/local/bin/run-antigravity; then :; fi
        ;;
      2)
        if run_interactive_and_harden \
          "Antigravity resume" \
          /usr/local/bin/run-antigravity --remote-dev-open-resume-picker; then :; fi
        ;;
      3)
        if run_interactive_and_harden "Antigravity installation" /usr/local/bin/remote-dev-install-antigravity; then :; fi
        ;;
      4)
        if run_interactive_and_harden "Antigravity update" /usr/local/bin/remote-dev-update-antigravity; then :; fi
        ;;
      5)
        if run_github_login; then :; fi
        ;;
      6)
        run_diagnostics
        ;;
      7)
        if run_interactive_and_harden "Login shell" bash --login; then :; fi
        ;;
      8)
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
  antigravity) show_antigravity_menu ;;
  shell) show_shell_menu ;;
  *)
    echo "ERROR: internal unsupported menu role: $role" >&2
    exit 2
    ;;
esac