#!/usr/bin/env bash
set -euo pipefail

runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"

role="$(remote_dev_resolve_role)"
export REMOTE_DEV_ROLE="$role"
workspace="${WORKSPACE:-/workspace}"
if [[ "$role" == codex || "$role" == antigravity ]]; then
  workspace="$(remote_dev_validate_workspace_root "$workspace")" || exit $?
fi
cd "$workspace"

active_project_name=""
active_project_path=""
project_choice_name=""
project_count=0

harden_state_or_exit() {
  if ! /usr/local/bin/secure-persistent-state; then
    echo "ERROR: failed to secure persistent credential state" >&2
    exit 1
  fi
}

pause_for_menu() {
  local prompt="${1:-Press Enter to return to the menu...}"
  read -r -p "$prompt" _
}

report_action_failure() {
  local label="$1"
  local action_status="$2"

  echo >&2
  echo "ERROR: $label exited with status $action_status" >&2
}

run_interactive_and_harden_to() {
  local return_prompt="$1"
  local label="$2"
  shift 2
  local action_status=0

  clear
  "$@" || action_status=$?
  harden_state_or_exit

  if (( action_status != 0 )); then
    report_action_failure "$label" "$action_status"
  fi

  pause_for_menu "$return_prompt"
  return "$action_status"
}

run_interactive_and_harden() {
  local label="$1"
  shift

  run_interactive_and_harden_to \
    "Press Enter to return to the menu..." \
    "$label" \
    "$@"
}

run_context7_action() {
  local label="$1"
  shift

  run_interactive_and_harden_to \
    "Press Enter to return to the Context7 menu..." \
    "$label" \
    "$@"
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

  pause_for_menu "Press Enter to return to the menu..."
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
  pause_for_menu "Press Enter to return to the menu..."
}

refresh_project_selection() {
  local resolved=""
  local listing=""
  local -a projects=()

  listing="$(remote_dev_list_projects "$workspace")" || return $?
  if [[ -n "$listing" ]]; then
    mapfile -t projects <<<"$listing"
  fi
  project_count="${#projects[@]}"

  if [[ -n "$active_project_name" ]]; then
    if resolved="$(remote_dev_project_path "$workspace" "$active_project_name" 2>/dev/null)"; then
      active_project_path="$resolved"
      return 0
    fi
    active_project_name=""
    active_project_path=""
  fi

  if (( project_count == 1 )); then
    active_project_name="${projects[0]}"
    if resolved="$(remote_dev_project_path "$workspace" "$active_project_name" 2>/dev/null)"; then
      active_project_path="$resolved"
    else
      active_project_name=""
      active_project_path=""
    fi
  fi
}

project_status_summary() {
  if [[ -n "$active_project_name" ]]; then
    printf 'Project: %s\n' "$active_project_name"
  elif (( project_count == 0 )); then
    printf 'Project: none (create one in Projects...)\n'
  else
    printf 'Project: not selected (%d available)\n' "$project_count"
  fi
}

ensure_active_project() {
  local refresh_status=0

  refresh_project_selection || refresh_status=$?
  if (( refresh_status != 0 )); then
    return "$refresh_status"
  fi
  if [[ -n "$active_project_name" ]]; then
    return 0
  fi

  if (( project_count == 0 )); then
    echo "ERROR: no projects are available under $workspace; create one in Projects..." >&2
  else
    echo "ERROR: multiple projects are available; select one in Projects... before starting an agent" >&2
  fi
  return 2
}

choose_project_name() {
  local heading="$1"
  local choice=""
  local normalized_choice=""
  local max_choice=""
  local listing=""
  local index=0
  local -a projects=()

  project_choice_name=""
  listing="$(remote_dev_list_projects "$workspace")" || return $?
  if [[ -n "$listing" ]]; then
    mapfile -t projects <<<"$listing"
  fi
  if (( ${#projects[@]} == 0 )); then
    echo "No projects are available under $workspace."
    return 1
  fi

  clear
  printf '%s\n' "$heading" "${heading//?/=}"
  for index in "${!projects[@]}"; do
    printf '%d) %s\n' "$((index + 1))" "${projects[$index]}"
  done
  max_choice="$(( ${#projects[@]} + 1 ))"
  printf '%s) Back\n' "$max_choice"
  read -r -p "> " choice

  if [[ ! "$choice" =~ ^[0-9]+$ ]]; then
    return 1
  fi

  normalized_choice="${choice#"${choice%%[!0]*}"}"
  if [[ -z "$normalized_choice" ]]; then
    normalized_choice=0
  fi
  if [[ "$normalized_choice" == 0 ]] || (( ${#normalized_choice} > ${#max_choice} )); then
    return 1
  fi
  # Equal-length ASCII digit strings have the same lexicographic and numeric ordering.
  # Keep this non-arithmetic guard so oversized input is rejected before Bash integer conversion.
  # shellcheck disable=SC2071
  if (( ${#normalized_choice} == ${#max_choice} )) && [[ "$normalized_choice" > "$max_choice" ]]; then
    return 1
  fi

  index=$((10#$normalized_choice - 1))
  if (( index == ${#projects[@]} )); then
    return 1
  fi
  if (( index < 0 || index >= ${#projects[@]} )); then
    return 1
  fi

  project_choice_name="${projects[$index]}"
}

select_project_action() {
  local resolved=""
  local choose_status=0

  choose_project_name "Select project" || choose_status=$?
  if (( choose_status != 0 )); then
    return "$choose_status"
  fi
  resolved="$(remote_dev_project_path "$workspace" "$project_choice_name")" || return $?
  active_project_name="$project_choice_name"
  active_project_path="$resolved"
}

create_project_action() {
  local name=""
  local resolved=""
  local action_status=0

  clear
  echo "Create project"
  echo "=============="
  echo "Projects are created as direct child directories of $workspace."
  read -r -p "Project name: " name
  if resolved="$(remote_dev_create_project "$workspace" "$name")"; then
    active_project_name="$name"
    active_project_path="$resolved"
    echo
    echo "Created project: $resolved"
  else
    action_status=$?
  fi
  pause_for_menu "Press Enter to return to the Projects menu..."
  return "$action_status"
}

delete_project_action() {
  local confirmation=""
  local resolved=""
  local action_status=0
  local choose_status=0

  choose_project_name "Delete project" || choose_status=$?
  if (( choose_status != 0 )); then
    return "$choose_status"
  fi
  resolved="$(remote_dev_project_path "$workspace" "$project_choice_name")" || return $?

  clear
  cat <<DELETE_WARNING
Delete project
==============
Path: $resolved

This permanently removes the entire project directory and all of its contents.
Type the exact project name to confirm: $project_choice_name
DELETE_WARNING
  read -r -p "> " confirmation
  if remote_dev_delete_project "$workspace" "$project_choice_name" "$confirmation"; then
    if [[ "$active_project_name" == "$project_choice_name" ]]; then
      active_project_name=""
      active_project_path=""
    fi
    refresh_project_selection || action_status=$?
    if (( action_status == 0 )); then
      echo
      echo "Deleted project: $project_choice_name"
    fi
  else
    action_status=$?
  fi
  pause_for_menu "Press Enter to return to the Projects menu..."
  return "$action_status"
}

show_projects_menu() {
  local summary=""

  while true; do
    refresh_project_selection
    summary="$(project_status_summary)"
    clear
    cat <<MENU
Remote Dev — Projects
${summary}
=====================
1) Select project
2) Create project
3) Delete project
4) Back
MENU
    read -r -p "> " choice
    case "$choice" in
      1)
        if select_project_action; then :; fi
        ;;
      2)
        if create_project_action; then :; fi
        ;;
      3)
        if delete_project_action; then :; fi
        ;;
      4)
        return 0
        ;;
      *)
        sleep 1
        ;;
    esac
  done
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
  local launch_mode=""
  local project_status=0
  local -a command=(/usr/local/bin/run-codex)

  ensure_active_project || project_status=$?
  if (( project_status != 0 )); then
    pause_for_menu
    return "$project_status"
  fi

  launch_mode="$next_codex_mode"
  next_codex_mode=""
  if [[ -n "$launch_mode" ]]; then
    command+=(--approval-mode "$launch_mode")
    label+=" ($launch_mode)"
  fi
  command+=(--cd "$active_project_path")
  command+=("$@")

  run_interactive_and_harden "$label" "${command[@]}"
}

run_antigravity_action() {
  local label="$1"
  shift
  local project_status=0
  local -a command=()

  ensure_active_project || project_status=$?
  if (( project_status != 0 )); then
    pause_for_menu
    return "$project_status"
  fi

  command=(env "REMOTE_DEV_PROJECT=$active_project_name" /usr/local/bin/run-antigravity)
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
        if run_context7_action "Context7 install/repair" "${context7_install_command[@]}"; then :; fi
        ;;
      2)
        if run_context7_action "Context7 connection test" "${context7_test_command[@]}"; then :; fi
        ;;
      3)
        if run_context7_action "Context7 contract update" "${context7_update_command[@]}"; then :; fi
        ;;
      4)
        if run_context7_action "Context7 removal" "${context7_remove_command[@]}"; then :; fi
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

show_unavailable_action() {
  local message="$1"
  clear
  printf '%s\n' "$message"
  pause_for_menu
}

if remote-dev-version --check >/dev/null 2>&1; then
  version_summary="$(remote-dev-version --menu)"
else
  version_summary="Image metadata unavailable"
fi

show_codex_menu() {
  local next_mode_summary="" runtime_summary="" context7_summary="" project_summary=""

  while true; do
    refresh_codex_policy
    next_mode_summary="$(next_codex_mode_summary)"
    runtime_summary="$(codex_runtime_status_summary)"
    context7_summary="$(context7_status_summary)"
    refresh_project_selection
    project_summary="$(project_status_summary)"
    clear
    cat <<MENU
Remote Dev — Codex
${version_summary}
${runtime_summary}
${context7_summary}
${policy_summary}
${next_mode_summary}
${project_summary}
==================
1) Start Codex
2) Resume a Codex session (current project)
3) Projects...
4) Approval mode for next launch...
5) Update optional Codex runtime from official OpenAI release
6) Remove optional Codex runtime (use bundled fallback)
7) Context7 integration...
8) Sign in to Codex with device code
9) Sign in to GitHub CLI
10) Run diagnostics
11) Open a login shell
12) Exit this tmux session
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
        show_projects_menu
        ;;
      4)
        if choose_next_codex_mode; then :; fi
        ;;
      5)
        if run_interactive_and_harden "Codex runtime update" /usr/local/bin/remote-dev-codex-runtime update; then :; fi
        ;;
      6)
        if run_interactive_and_harden "Codex runtime removal" /usr/local/bin/remote-dev-codex-runtime remove; then :; fi
        ;;
      7)
        show_context7_menu
        ;;
      8)
        if run_interactive_and_harden "Codex login" codex login --device-auth; then :; fi
        ;;
      9)
        if run_github_login; then :; fi
        ;;
      10)
        run_diagnostics
        ;;
      11)
        if run_interactive_and_harden "Login shell" bash --login; then :; fi
        ;;
      12)
        exit 0
        ;;
      *)
        sleep 1
        ;;
    esac
  done
}

show_antigravity_menu() {
  local status_summary="" project_summary=""

  while true; do
    status_summary="$(antigravity_status_summary)"
    refresh_project_selection
    project_summary="$(project_status_summary)"
    clear
    cat <<MENU
Remote Dev — Antigravity
${version_summary}
${status_summary}
${project_summary}
========================
1) Start Antigravity (use /resume to browse/resume older conversations)
2) Continue latest Antigravity conversation (current project)
3) Projects...
4) Launch/approval options [not available]
5) Install Antigravity from Google
6) Update Antigravity from Google
7) Context7 integration [pending #95]
8) Antigravity sign-in [handled during launch]
9) Sign in to GitHub CLI
10) Run diagnostics
11) Open a login shell
12) Exit this tmux session
MENU
    read -r -p "> " choice
    case "$choice" in
      1)
        if run_antigravity_action "Antigravity"; then :; fi
        ;;
      2)
        if run_antigravity_action "Antigravity continue" --continue; then :; fi
        ;;
      3)
        show_projects_menu
        ;;
      4)
        show_unavailable_action "Antigravity does not currently expose a Remote Dev-reviewed launch/approval option."
        ;;
      5)
        if run_interactive_and_harden "Antigravity installation" /usr/local/bin/remote-dev-install-antigravity; then :; fi
        ;;
      6)
        if run_interactive_and_harden "Antigravity update" /usr/local/bin/remote-dev-update-antigravity; then :; fi
        ;;
      7)
        show_unavailable_action "Context7 for Antigravity is not implemented yet; see #95."
        ;;
      8)
        show_unavailable_action "Antigravity authentication is currently handled by the vendor flow during launch."
        ;;
      9)
        if run_github_login; then :; fi
        ;;
      10)
        run_diagnostics
        ;;
      11)
        if run_interactive_and_harden "Login shell" bash --login; then :; fi
        ;;
      12)
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
