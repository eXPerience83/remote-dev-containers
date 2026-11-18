#!/usr/bin/env bash
set -euo pipefail

menu_source="${REMOTE_DEV_MENU:-/usr/local/bin/remote-dev-menu}"
workdir="$(mktemp -d)"
fixture_menu="$workdir/remote-dev-menu"
runtime_lib="$workdir/remote-dev-runtime.sh"
run_codex="$workdir/run-codex"
codex_runtime="$workdir/remote-dev-codex-runtime"
context7_manager="$workdir/remote-dev-context7"
secure_state="$workdir/secure-persistent-state"
bin_dir="$workdir/bin"
invocations="$workdir/invocations"
runtime_invocations="$workdir/runtime-invocations"
context7_invocations="$workdir/context7-invocations"
codex_cli_invocations="$workdir/codex-cli-invocations"
github_invocations="$workdir/github-invocations"
doctor_invocations="$workdir/doctor-invocations"
shell_invocations="$workdir/shell-invocations"
agent_environment="$workdir/agent-environment"
credential_environment="$workdir/credential-environment"
shell_environment="$workdir/shell-environment"
hardening_calls="$workdir/hardening-calls"
list_counter="$workdir/list-projects-counter"
development_root="$workdir/workspace/.remote-dev-tmp"

cleanup() {
  rm -rf "$workdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ ! -f "$menu_source" ]]; then
  echo "ERROR: missing Remote Dev menu source: $menu_source" >&2
  exit 1
fi

mkdir -p \
  "$bin_dir" \
  "$workdir/workspace/project" \
  "$development_root/tmp" \
  "$development_root/uv-cache" \
  "$development_root/npm-cache" \
  "$development_root/pip-cache"

cat > "$runtime_lib" <<'RUNTIME'
remote_dev_resolve_role() {
  printf '%s\n' "${REMOTE_DEV_TEST_ROLE:-codex}"
}

remote_dev_validate_workspace_root() {
  [[ "$1" == /* && -d "$1" && ! -L "$1" ]] || return 2
  printf '%s\n' "$1"
}

remote_dev_recover_safe_cwd() {
  builtin cd -P -- /
}

remote_dev_validate_project_name() {
  (( ${#1} > 0 && ${#1} <= 128 )) || return 2
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || return 2
  printf '%s\n' "$1"
}

remote_dev_list_projects() {
  local path name count=0
  if [[ "${REMOTE_DEV_TEST_BLOCK_PROJECTS:-0}" == 1 ]]; then
    echo 'ERROR: synthetic blocked project collection' >&2
    return 2
  fi
  if [[ "${REMOTE_DEV_TEST_LIST_PROJECTS_FAIL:-0}" == 1 ]]; then
    echo 'ERROR: synthetic project listing failure' >&2
    return 7
  fi
  if [[ -n "${REMOTE_DEV_TEST_LIST_PROJECTS_FAIL_ON_CALL:-}" ]]; then
    [[ -n "${REMOTE_DEV_TEST_LIST_PROJECTS_COUNTER:-}" ]] || return 8
    if [[ -f "$REMOTE_DEV_TEST_LIST_PROJECTS_COUNTER" ]]; then
      read -r count < "$REMOTE_DEV_TEST_LIST_PROJECTS_COUNTER"
    fi
    count=$((count + 1))
    printf '%s\n' "$count" > "$REMOTE_DEV_TEST_LIST_PROJECTS_COUNTER"
    if [[ "$count" == "$REMOTE_DEV_TEST_LIST_PROJECTS_FAIL_ON_CALL" ]]; then
      echo 'ERROR: synthetic project listing failure during action' >&2
      return 7
    fi
  fi
  for path in "$1"/*; do
    [[ -d "$path" && ! -L "$path" ]] || continue
    name="${path##*/}"
    remote_dev_validate_project_name "$name" >/dev/null 2>&1 || continue
    printf '%s\n' "$name"
  done | LC_ALL=C sort
}

remote_dev_project_path() {
  remote_dev_validate_workspace_root "$1" >/dev/null || return 2
  remote_dev_validate_project_name "$2" >/dev/null || return 2
  [[ -d "$1/$2" && ! -L "$1/$2" ]] || return 2
  printf '%s/%s\n' "$1" "$2"
}

remote_dev_create_project() {
  remote_dev_validate_project_name "$2" >/dev/null || return 2
  [[ ! -e "$1/$2" && ! -L "$1/$2" ]] || return 2
  mkdir -- "$1/$2"
  printf '%s/%s\n' "$1" "$2"
}

remote_dev_delete_project() {
  [[ "$2" == "$3" ]] || return 2
  remote_dev_project_path "$1" "$2" >/dev/null || return 2
  rm -rf -- "$1/$2"
}
RUNTIME

cat > "$run_codex" <<'RUN_CODEX'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == --print-policy ]]; then
  mode="${REMOTE_DEV_CODEX_APPROVAL_MODE:-autonomous}"
  if [[ -n "${REMOTE_DEV_CODEX_APPROVAL_MODE:-}" ]]; then
    source=deployment
  else
    source=default
  fi
  case "$mode" in
    autonomous) policy=never ;;
    guarded) policy=trust-derived ;;
    *) exit 2 ;;
  esac
  printf '%s\n' \
    'Inner sandbox: disabled explicitly' \
    'Isolation boundary: outer container' \
    "Codex approval mode: $mode"
  if [[ "$mode" == guarded ]]; then
    printf '%s\n' \
      'Project trust: untrusted (launch-scoped)' \
      'Approval behavior: prompt for commands except explicit exec-policy allows'
  else
    printf '%s\n' "Codex approval policy: $policy"
  fi
  printf '%s\n' "Mode source: $source"
  exit 0
fi

{
  printf '['
  separator=""
  for argument in "$@"; do
    printf '%s%s' "$separator" "$argument"
    separator=']['
  done
  printf ']\n'
} >> "$REMOTE_DEV_MENU_INVOCATIONS"
printf '%s\n' \
  "TMPDIR=${TMPDIR-<unset>} TMP=${TMP-<unset>} TEMP=${TEMP-<unset>} UV_CACHE_DIR=${UV_CACHE_DIR-<unset>} UV_TOOL_DIR=${UV_TOOL_DIR-<unset>} NPM_CONFIG_CACHE=${NPM_CONFIG_CACHE-<unset>} PIP_CACHE_DIR=${PIP_CACHE_DIR-<unset>} PRE_COMMIT_HOME=${PRE_COMMIT_HOME-<unset>}" \
  >> "$REMOTE_DEV_MENU_AGENT_ENVIRONMENT"

if [[ -n "${REMOTE_DEV_MENU_FAIL_ONCE_FILE:-}" && ! -e "$REMOTE_DEV_MENU_FAIL_ONCE_FILE" ]]; then
  : > "$REMOTE_DEV_MENU_FAIL_ONCE_FILE"
  exit 42
fi
RUN_CODEX
chmod 0755 "$run_codex"

cat > "$codex_runtime" <<'CODEX_RUNTIME'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  status)
    [[ "${2:-}" == --menu ]] || exit 2
    printf '%s\n' 'Codex: bundled 0.147.0'
    ;;
  update|remove)
    printf '%s\n' "$1" >> "$REMOTE_DEV_MENU_RUNTIME_INVOCATIONS"
    ;;
  *) exit 2 ;;
esac
CODEX_RUNTIME
chmod 0755 "$codex_runtime"

cat > "$context7_manager" <<'CONTEXT7'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  status)
    [[ "${2:-}" == --menu && "$#" == 2 ]] || exit 2
    if [[ "${REMOTE_DEV_MENU_CONTEXT7_DIAGNOSTIC_FAIL:-0}" == 1 ]]; then
      echo 'Codex Context7 status fixture failure' >&2
      exit 17
    fi
    printf '%s\n' 'Context7: not configured'
    ;;
  menu-state)
    [[ "$#" == 1 ]] || exit 2
    printf '%s\n' "${REMOTE_DEV_MENU_CONTEXT7_FIXTURE_STATE:-absent}"
    ;;
  plan)
    [[ "$#" == 1 ]] || exit 2
    printf '%s\n' "$*" >> "$REMOTE_DEV_MENU_CONTEXT7_INVOCATIONS"
    if [[ "${REMOTE_DEV_MENU_CONTEXT7_DIAGNOSTIC_FAIL:-0}" == 1 ]]; then
      echo 'Codex Context7 recovery plan fixture failure' >&2
      exit 19
    fi
    printf '%s\n' 'Context7 recovery: NOT INSTALLED (read-only)'
    ;;
  install)
    # This fixture stands in for the TTY-aware onboarding entrypoint;
    # an initial menu install must carry its locked expected state.
    [[ "$#" == 2 && ( "$2" == --menu-expect-absent || "$2" == --menu-expect-healthy ) ]] || exit 2
    printf '%s\n' "$*" >> "$REMOTE_DEV_MENU_CONTEXT7_INVOCATIONS"
    ;;
  update)
    [[ "$#" == 1 ]] || exit 2
    printf '%s\n' "$*" >> "$REMOTE_DEV_MENU_CONTEXT7_INVOCATIONS"
    ;;
  test)
    [[ "$#" == 2 && "$2" == --yes ]] || exit 2
    printf '%s\n' "$*" >> "$REMOTE_DEV_MENU_CONTEXT7_INVOCATIONS"
    ;;
  remove)
    [[ "$#" == 3 && "$2" == --expect-healthy && "$3" == --yes ]] || exit 2
    printf '%s\n' "$*" >> "$REMOTE_DEV_MENU_CONTEXT7_INVOCATIONS"
    ;;
  reinstall)
    [[ "$#" == 3 && "$2" == --menu-safe && "$3" == --yes ]] || exit 2
    printf '%s\n' "$*" >> "$REMOTE_DEV_MENU_CONTEXT7_INVOCATIONS"
    ;;
  *) exit 2 ;;
esac
CONTEXT7
chmod 0755 "$context7_manager"

cat > "$secure_state" <<'SECURE_STATE'
#!/usr/bin/env bash
set -euo pipefail
printf 'hardened\n' >> "$REMOTE_DEV_MENU_HARDENING_CALLS"
SECURE_STATE
chmod 0755 "$secure_state"

cat > "$bin_dir/remote-dev-version" <<'VERSION'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --check) exit 0 ;;
  --menu)
    printf '%s\n' \
      'Image: test @ 0123456789ab' \
      'Codex: codex-cli test'
    ;;
  *) exit 2 ;;
esac
VERSION

cat > "$bin_dir/clear" <<'CLEAR'
#!/usr/bin/env bash
exit 0
CLEAR

cat > "$bin_dir/codex" <<'CODEX_CLI'
#!/usr/bin/env bash
set -euo pipefail
{
  printf '['
  separator=""
  for argument in "$@"; do
    printf '%s%s' "$separator" "$argument"
    separator=']['
  done
  printf ']\n'
} >> "$REMOTE_DEV_MENU_CODEX_CLI_INVOCATIONS"
printf '%s\n' \
  "TMPDIR=${TMPDIR-<unset>} TMP=${TMP-<unset>} TEMP=${TEMP-<unset>} UV_CACHE_DIR=${UV_CACHE_DIR-<unset>} UV_TOOL_DIR=${UV_TOOL_DIR-<unset>} NPM_CONFIG_CACHE=${NPM_CONFIG_CACHE-<unset>} PIP_CACHE_DIR=${PIP_CACHE_DIR-<unset>} PRE_COMMIT_HOME=${PRE_COMMIT_HOME-<unset>}" \
  >> "$REMOTE_DEV_MENU_CREDENTIAL_ENVIRONMENT"
CODEX_CLI

cat > "$bin_dir/gh" <<'GH'
#!/usr/bin/env bash
set -euo pipefail
{
  printf '['
  separator=""
  for argument in "$@"; do
    printf '%s%s' "$separator" "$argument"
    separator=']['
  done
  printf ']\n'
} >> "$REMOTE_DEV_MENU_GITHUB_INVOCATIONS"
printf '%s\n' \
  "TMPDIR=${TMPDIR-<unset>} TMP=${TMP-<unset>} TEMP=${TEMP-<unset>} UV_CACHE_DIR=${UV_CACHE_DIR-<unset>} UV_TOOL_DIR=${UV_TOOL_DIR-<unset>} NPM_CONFIG_CACHE=${NPM_CONFIG_CACHE-<unset>} PIP_CACHE_DIR=${PIP_CACHE_DIR-<unset>} PRE_COMMIT_HOME=${PRE_COMMIT_HOME-<unset>}" \
  >> "$REMOTE_DEV_MENU_CREDENTIAL_ENVIRONMENT"
case "${1:-}:${2:-}" in
  auth:login|auth:setup-git) exit 0 ;;
  *) exit 2 ;;
esac
GH

cat > "$bin_dir/remote-dev-doctor" <<'DOCTOR'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' doctor >> "$REMOTE_DEV_MENU_DOCTOR_INVOCATIONS"
DOCTOR

cat > "$bin_dir/login-shell" <<'LOGIN_SHELL'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' shell >> "$REMOTE_DEV_MENU_SHELL_INVOCATIONS"
printf '%s\n' \
  "TMPDIR=${TMPDIR-<unset>} TMP=${TMP-<unset>} TEMP=${TEMP-<unset>} UV_CACHE_DIR=${UV_CACHE_DIR-<unset>} UV_TOOL_DIR=${UV_TOOL_DIR-<unset>} NPM_CONFIG_CACHE=${NPM_CONFIG_CACHE-<unset>} PIP_CACHE_DIR=${PIP_CACHE_DIR-<unset>} PRE_COMMIT_HOME=${PRE_COMMIT_HOME-<unset>}" \
  >> "$REMOTE_DEV_MENU_SHELL_ENVIRONMENT"
LOGIN_SHELL

chmod 0755 "$bin_dir"/*

if ! grep -Fxq 'runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh' "$menu_source"; then
  echo 'ERROR: missing fixture anchor: runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh' >&2
  exit 1
fi
for anchor in \
  '/usr/local/bin/run-codex' \
  '/usr/local/bin/remote-dev-codex-runtime' \
  '/usr/local/bin/remote-dev-context7' \
  '/usr/local/bin/secure-persistent-state' \
  '/usr/local/bin/remote-dev-doctor' \
  'bash --login'; do
  if ! grep -Fq "$anchor" "$menu_source"; then
    echo "ERROR: missing fixture anchor: $anchor" >&2
    exit 1
  fi
done

sed \
  -e "s|^runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh$|runtime_lib=$runtime_lib|" \
  -e "s|/usr/local/bin/run-codex|$run_codex|g" \
  -e "s|/usr/local/bin/remote-dev-codex-runtime|$codex_runtime|g" \
  -e "s|/usr/local/bin/remote-dev-context7|$context7_manager|g" \
  -e "s|/usr/local/bin/secure-persistent-state|$secure_state|g" \
  -e "s|/usr/local/bin/remote-dev-doctor|$bin_dir/remote-dev-doctor|g" \
  -e "s|bash --login|$bin_dir/login-shell|g" \
  "$menu_source" > "$fixture_menu"
chmod 0755 "$fixture_menu"

if ! grep -Fxq "runtime_lib=$runtime_lib" "$fixture_menu"; then
  echo "ERROR: failed to redirect runtime_lib to the test fixture" >&2
  exit 1
fi

assert_file_lines() {
  local file="$1"
  local label="$2"
  shift 2
  local -a expected=("$@") actual=()
  if [[ -f "$file" ]]; then
    mapfile -t actual < "$file"
  fi
  if (( ${#actual[@]} != ${#expected[@]} )); then
    printf 'ERROR: %s recorded %d lines, expected %d\n' "$label" "${#actual[@]}" "${#expected[@]}" >&2
    printf 'Actual: %s\n' "${actual[*]:-<none>}" >&2
    exit 1
  fi
  for index in "${!expected[@]}"; do
    if [[ "${actual[$index]}" != "${expected[$index]}" ]]; then
      printf 'ERROR: %s line %d is %q, expected %q\n' "$label" "$index" "${actual[$index]}" "${expected[$index]}" >&2
      exit 1
    fi
  done
}

run_menu() {
  local deployment_mode="$1" input="$2" output_file="$3" test_role="${4:-codex}"
  rm -f \
    "$invocations" \
    "$runtime_invocations" \
    "$context7_invocations" \
    "$codex_cli_invocations" \
    "$github_invocations" \
    "$doctor_invocations" \
    "$shell_invocations" \
    "$agent_environment" \
    "$credential_environment" \
    "$shell_environment" \
    "$hardening_calls"
  common_env=(
    PATH="$bin_dir:$PATH"
    WORKSPACE="$workdir/workspace"
    REMOTE_DEV_TEST_ROLE="$test_role"
    REMOTE_DEV_MENU_INVOCATIONS="$invocations"
    REMOTE_DEV_MENU_RUNTIME_INVOCATIONS="$runtime_invocations"
    REMOTE_DEV_MENU_CONTEXT7_INVOCATIONS="$context7_invocations"
    REMOTE_DEV_MENU_CODEX_CLI_INVOCATIONS="$codex_cli_invocations"
    REMOTE_DEV_MENU_GITHUB_INVOCATIONS="$github_invocations"
    REMOTE_DEV_MENU_DOCTOR_INVOCATIONS="$doctor_invocations"
    REMOTE_DEV_MENU_SHELL_INVOCATIONS="$shell_invocations"
    REMOTE_DEV_MENU_AGENT_ENVIRONMENT="$agent_environment"
    REMOTE_DEV_MENU_CREDENTIAL_ENVIRONMENT="$credential_environment"
    REMOTE_DEV_MENU_SHELL_ENVIRONMENT="$shell_environment"
    REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls"
    TMPDIR="$development_root/tmp"
    TMP="$development_root/tmp"
    TEMP="$development_root/tmp"
    UV_CACHE_DIR="$development_root/uv-cache"
    UV_TOOL_DIR="$development_root/uv-tools"
    NPM_CONFIG_CACHE="$development_root/npm-cache"
    PIP_CACHE_DIR="$development_root/pip-cache"
    PRE_COMMIT_HOME="$development_root/pre-commit-cache"
  )
  if [[ "$deployment_mode" == __unset__ ]]; then
    printf '%s' "$input" | env -u REMOTE_DEV_CODEX_APPROVAL_MODE "${common_env[@]}" timeout --foreground 30s "$fixture_menu" > "$output_file" 2>&1
  else
    printf '%s' "$input" | env REMOTE_DEV_CODEX_APPROVAL_MODE="$deployment_mode" "${common_env[@]}" timeout --foreground 30s "$fixture_menu" > "$output_file" 2>&1
  fi
}

assert_hardening_count() {
  local expected_count="$1" actual_count=0
  if [[ -f "$hardening_calls" ]]; then
    actual_count="$(wc -l < "$hardening_calls")"
  fi
  if (( actual_count != expected_count )); then
    echo "ERROR: persistent-state hardening ran $actual_count times, expected $expected_count" >&2
    exit 1
  fi
}

project_path="$workdir/workspace/project"
output="$workdir/output"
# Duplicate action choices are consumed by the success pause. If the pause
# disappears, the duplicate becomes another action and the exact call count fails.
run_menu __unset__ $'1\n1\n0\n' "$output"
assert_file_lines "$invocations" 'configured start' "[--cd][$project_path]"
assert_file_lines "$agent_environment" 'configured agent environment' \
  "TMPDIR=$development_root/tmp TMP=$development_root/tmp TEMP=$development_root/tmp UV_CACHE_DIR=$development_root/uv-cache UV_TOOL_DIR=$development_root/uv-tools NPM_CONFIG_CACHE=$development_root/npm-cache PIP_CACHE_DIR=$development_root/pip-cache PRE_COMMIT_HOME=$development_root/pre-commit-cache"
assert_hardening_count 1
grep -Fxq 'Codex: bundled 0.147.0' "$output"
grep -Fxq 'Context7: not configured' "$output"
grep -Fxq 'Project: project' "$output"
grep -Fxq '1) Start Codex' "$output"
grep -Fxq '2) Resume session (current project)' "$output"
grep -Fxq '3) Projects...' "$output"
grep -Fxq '4) Approval settings...' "$output"
grep -Fxq '5) Manage Codex...' "$output"
grep -Fxq '6) MCP integrations...' "$output"
grep -Fxq '7) Sign in to GitHub CLI' "$output"
grep -Fxq '0) Exit this tmux session' "$output"
grep -Fxq 'Next launch mode: configured (autonomous)' "$output"

echo 'Configured project-scoped Codex menu actions: OK'

run_menu __unset__ $'5\n1\n\n2\n\n0\n0\n' "$output"
assert_file_lines "$runtime_invocations" 'runtime menu actions' update remove
assert_hardening_count 2
grep -Fxq '1) Update from official OpenAI release' "$output"
grep -Fxq '2) Remove optional update / use bundled fallback' "$output"
grep -Fxq '0) Back' "$output"
echo 'Codex runtime update/remove result pauses: OK'

run_menu __unset__ $'5\n0\n0\n' "$output"
assert_file_lines "$runtime_invocations" 'cancelled manage menu'
assert_hardening_count 0
echo 'Codex Manage Back is nonmutating: OK'

# Projects now shows the shared 0 Back, but accepts the historical 4 as an alias.
run_menu __unset__ $'3\n0\n0\n' "$output"
assert_file_lines "$invocations" 'Projects Back 0'
assert_hardening_count 0
grep -Fxq '0) Back' "$output"

run_menu __unset__ $'3\n4\n0\n' "$output"
assert_file_lines "$invocations" 'Projects legacy Back 4'
assert_hardening_count 0
echo 'Projects shared Back 0 and legacy 4 are nonmutating: OK'

# The inner project picker is also a submenu: display 0 Back and exit
# without selecting/mutating, regardless of the collection's current size.
run_menu __unset__ $'3\n1\n0\n0\n0\n' "$output"
assert_file_lines "$invocations" 'Project picker 0 Back'
assert_hardening_count 0
(( $(grep -Fxc '0) Back' "$output") >= 2 ))
echo 'Project picker, Projects menu and main navigation all use 0 Back: OK'

# A blocked project collection must refuse *every* project workflow before
# entering the picker, create prompt or deletion confirmation. The runtime
# checks again, but the menu must not advertise disabled actions and run them.
export REMOTE_DEV_TEST_BLOCK_PROJECTS=1
run_menu __unset__ $'3\n1\n\n2\n\n3\n\n0\n0\n' "$output"
unset REMOTE_DEV_TEST_BLOCK_PROJECTS
assert_file_lines "$invocations" 'blocked project collection'
assert_hardening_count 0
[[ -d "$workdir/workspace/project" ]]
[[ ! -e "$workdir/workspace/blocked-create" ]]
[[ "$(grep -Fc 'Project collection is blocked; selection, creation and deletion are disabled.' "$output")" == 3 ]]
if grep -Fxq 'Create project' "$output" || grep -Fxq 'Select project' "$output" || grep -Fxq 'Delete project' "$output"; then
  echo 'ERROR: blocked project collection entered a project workflow' >&2
  exit 1
fi
grep -Fq 'Project: BLOCKED (collection safety check failed; run diagnostics)' "$output"
echo 'Codex blocked Projects refuses Select/Create/Delete before dispatch: OK'

# Context7 retains its submenu contract; main entry moves from 7 to 6.
export REMOTE_DEV_MENU_CONTEXT7_FIXTURE_STATE=absent
run_menu __unset__ $'6\n1\n1\n\n2\ny\n\n3\n\n4\ny\n\n5\n\n0\n0\n0\n' "$output"
assert_file_lines "$context7_invocations" 'Context7 absent menu actions' \
  'plan' 'test --yes' 'plan' 'install --menu-expect-absent'
assert_hardening_count 2
grep -Fxq 'Remote Dev — Codex — Context7' "$output"
grep -Fq 'Press Enter to return to the Context7 menu...' "$fixture_menu"

export REMOTE_DEV_MENU_CONTEXT7_FIXTURE_STATE=healthy
run_menu __unset__ $'6\n1\n3\n\n4\n\n5\nREMOVE\n\n0\n0\n0\n' "$output"
assert_file_lines "$context7_invocations" 'Context7 healthy menu actions' 'install --menu-expect-healthy' 'remove --expect-healthy --yes'
assert_hardening_count 2
grep -Fq 'no repair or confirmation is necessary' "$output"

export REMOTE_DEV_MENU_CONTEXT7_FIXTURE_STATE=repairable
run_menu __unset__ $'6\n1\n4\nREINSTALL\n\n0\n0\n0\n' "$output"
assert_file_lines "$context7_invocations" 'Context7 repair actions' 'plan' 'reinstall --menu-safe --yes'
assert_hardening_count 1

export REMOTE_DEV_MENU_CONTEXT7_FIXTURE_STATE=blocked
run_menu __unset__ $'6\n1\n4\n\n5\n\n0\n0\n0\n' "$output"
assert_file_lines "$context7_invocations" 'Context7 blocked actions' 'plan'
assert_hardening_count 0
# Initial Context7 installation can be declined before any credential
# prompt or configuration write; a read-only recovery plan is allowed.
export REMOTE_DEV_MENU_CONTEXT7_FIXTURE_STATE=absent
run_menu __unset__ $'6\n1\n4\nn\n\n0\n0\n0\n' "$output"
assert_file_lines "$context7_invocations" 'Context7 installation cancel' 'plan'
assert_hardening_count 0
grep -Fq 'Context7 installation cancelled; no configuration changes were made.' "$output"

# Rejecting the same nonmutating network test must never launch either
# manager or trigger persistent-state hardening.
export REMOTE_DEV_MENU_CONTEXT7_FIXTURE_STATE=healthy
for decision in n TEST ""; do
  run_menu __unset__ "$(printf '6\n1\n2\n%s\n\n0\n0\n0\n' "$decision")" "$output"
  assert_file_lines "$context7_invocations" "Context7 test decline $decision"
  assert_hardening_count 0
  grep -Fq 'Context7 test cancelled; no network request was made.' "$output"
done
# A failed typed removal or repair confirmation must not mutate state.
run_menu __unset__ $'6\n1\n5\nNO\n\n0\n0\n0\n' "$output"
assert_file_lines "$context7_invocations" 'Context7 removal cancellation'
assert_hardening_count 0
export REMOTE_DEV_MENU_CONTEXT7_FIXTURE_STATE=repairable
run_menu __unset__ $'6\n1\n4\nNOT-REINSTALL\n\n0\n0\n0\n' "$output"
assert_file_lines "$context7_invocations" 'Context7 repair cancellation' 'plan'
assert_hardening_count 0
# The same shared y/N helper accepts mixed-case Yes in either role.
run_menu __unset__ $'6\n1\n2\nYes\n\n0\n0\n0\n' "$output"
assert_file_lines "$context7_invocations" 'Codex mixed-case yes test' 'test --yes'
assert_hardening_count 1

# A failing offline status/plan must report both real exit codes without
# triggering test, mutation, credential changes, or hardening.
export REMOTE_DEV_MENU_CONTEXT7_DIAGNOSTIC_FAIL=1
run_menu __unset__ $'6\n1\n1\n\n0\n0\n0\n' "$output"
assert_file_lines "$context7_invocations" 'Codex failed offline plan attempt' 'plan'
assert_hardening_count 0
grep -Fq 'ERROR: Context7 status exited with status 17' "$output"
grep -Fq 'ERROR: Context7 recovery plan exited with status 19' "$output"
unset REMOTE_DEV_MENU_CONTEXT7_DIAGNOSTIC_FAIL

unset REMOTE_DEV_MENU_CONTEXT7_FIXTURE_STATE
echo 'Context7 end-to-end confirmations/cancellation and scoped maintenance: OK'

run_menu __unset__ $'5\n3\n\n0\n7\n\n8\n\n9\n\n0\n' "$output"
assert_file_lines "$codex_cli_invocations" 'Codex device login' '[login][--device-auth]'
assert_file_lines "$github_invocations" 'GitHub CLI setup' \
  '[auth][login][--hostname][github.com][--git-protocol][https][--web]' \
  '[auth][setup-git]'
assert_file_lines "$doctor_invocations" 'Codex diagnostics' doctor
assert_file_lines "$shell_invocations" 'Codex container shell' shell
assert_file_lines "$credential_environment" 'credential action environment' \
  'TMPDIR=/tmp TMP=/tmp TEMP=/tmp UV_CACHE_DIR=<unset> UV_TOOL_DIR=<unset> NPM_CONFIG_CACHE=<unset> PIP_CACHE_DIR=<unset> PRE_COMMIT_HOME=<unset>' \
  'TMPDIR=/tmp TMP=/tmp TEMP=/tmp UV_CACHE_DIR=<unset> UV_TOOL_DIR=<unset> NPM_CONFIG_CACHE=<unset> PIP_CACHE_DIR=<unset> PRE_COMMIT_HOME=<unset>' \
  'TMPDIR=/tmp TMP=/tmp TEMP=/tmp UV_CACHE_DIR=<unset> UV_TOOL_DIR=<unset> NPM_CONFIG_CACHE=<unset> PIP_CACHE_DIR=<unset> PRE_COMMIT_HOME=<unset>'
assert_file_lines "$shell_environment" 'container shell environment' \
  "TMPDIR=$development_root/tmp TMP=$development_root/tmp TEMP=$development_root/tmp UV_CACHE_DIR=$development_root/uv-cache UV_TOOL_DIR=$development_root/uv-tools NPM_CONFIG_CACHE=$development_root/npm-cache PIP_CACHE_DIR=$development_root/pip-cache PRE_COMMIT_HOME=$development_root/pre-commit-cache"
assert_hardening_count 3
echo 'Codex login/GitHub/diagnostics/shell result pauses: OK'

# Approval invalid-input UX must match AGY: redraw the same submenu, never
# treat an invalid selection as Back or arm a hidden agent action.
run_menu __unset__ $'4\ninvalid\n9\n3\n1\n\n0\n' "$output"
assert_file_lines "$invocations" 'Codex approval invalid choices stay in submenu' \
  "[--approval-mode][guarded][--cd][$project_path]"
assert_hardening_count 1
if (( $(grep -Fxc 'Codex approval settings' "$output") != 3 )); then
  echo 'ERROR: Codex approval invalid choices did not redraw the submenu' >&2
  exit 1
fi

run_menu __unset__ $'4\n3\n2\n2\n1\n1\n0\n' "$output"
assert_file_lines "$invocations" 'guarded resume then configured start' \
  "[--approval-mode][guarded][--cd][$project_path][resume]" \
  "[--cd][$project_path]"
assert_hardening_count 2
grep -Fxq 'Next launch mode: guarded (one launch)' "$output"
if [[ "$(grep -Fxc 'Next launch mode: configured (autonomous)' "$output")" -lt 2 ]]; then
  echo "ERROR: the guarded override was not consumed after one launch" >&2
  exit 1
fi

echo 'One-launch guarded selection and reset: OK'

run_menu guarded $'4\n2\n1\n1\n0\n' "$output"
assert_file_lines "$invocations" 'autonomous override of guarded deployment' \
  "[--approval-mode][autonomous][--cd][$project_path]"
assert_hardening_count 1
grep -Fxq 'Next launch mode: configured (guarded)' "$output"
grep -Fxq 'Next launch mode: autonomous (one launch)' "$output"

echo 'One-launch autonomous selection precedence: OK'

run_menu __unset__ $'4\n3\n4\n1\n1\n1\n0\n' "$output"
assert_file_lines "$invocations" 'configured-mode reset before launch' "[--cd][$project_path]"
assert_hardening_count 1

echo 'Configured-mode reset: OK'

fail_once="$workdir/fail-once"
rm -f "$fail_once"
export REMOTE_DEV_MENU_FAIL_ONCE_FILE="$fail_once"
run_menu __unset__ $'4\n3\n1\n1\n1\n1\n0\n' "$output"
unset REMOTE_DEV_MENU_FAIL_ONCE_FILE
assert_file_lines "$invocations" 'failed override then configured retry' \
  "[--approval-mode][guarded][--cd][$project_path]" \
  "[--cd][$project_path]"
assert_hardening_count 2
grep -Fq 'ERROR: Codex (guarded) exited with status 42' "$output"

echo 'Failed and successful action result pauses: OK'

new_project_path="$workdir/workspace/new-project"
run_menu __unset__ $'3\n2\nnew-project\n\n1\n1\n0\n' "$output"
assert_file_lines "$invocations" 'created project immediate start' "[--cd][$new_project_path]"
[[ -d "$new_project_path" ]]
grep -Fq "Created project: $new_project_path" "$output"
grep -Fq 'Press Enter to continue...' "$fixture_menu"
echo 'Successful project create returns to Codex with the new project active: OK'

second_project_path="$workdir/workspace/second-project"
mkdir -p "$second_project_path"
run_menu __unset__ $'3\n1\n3\n1\n1\n0\n' "$output"
assert_file_lines "$invocations" 'selected project immediate start' "[--cd][$second_project_path]"
grep -Fxq 'Project: second-project' "$output"
echo 'Successful project selection returns to Codex for immediate Start: OK'
rm -rf -- "$second_project_path"

run_menu __unset__ $'3\n3\n1\nnew-project\n\n4\n0\n' "$output"
assert_file_lines "$invocations" 'project deletion navigation'
[[ ! -e "$new_project_path" ]]
grep -Fxq 'Deleted project: new-project' "$output"
if (( $(grep -Fxc 'Remote Dev — Projects' "$output") < 2 )); then
  echo 'ERROR: successful deletion did not remain in the Projects menu' >&2
  exit 1
fi
echo 'Successful project deletion remains in Projects: OK'

run_menu __unset__ $'3\n1\n2\n4\n0\n' "$output"
assert_file_lines "$invocations" 'cancelled project selection'
if (( $(grep -Fxc 'Remote Dev — Projects' "$output") < 2 )); then
  echo 'ERROR: cancelled project selection did not remain in Projects' >&2
  exit 1
fi
echo 'Cancelled project selection remains in Projects: OK'

run_menu __unset__ $'3\n1\ninvalid\n4\n0\n' "$output"
assert_file_lines "$invocations" 'invalid project selection'
if (( $(grep -Fxc 'Remote Dev — Projects' "$output") < 2 )); then
  echo 'ERROR: invalid project selection did not remain in Projects' >&2
  exit 1
fi
echo 'Invalid project selection remains in Projects: OK'

run_menu __unset__ $'3\n2\nproject\n\n4\n0\n' "$output"
assert_file_lines "$invocations" 'failed project creation'
if (( $(grep -Fxc 'Remote Dev — Projects' "$output") < 2 )); then
  echo 'ERROR: failed project creation did not remain in Projects' >&2
  exit 1
fi
echo 'Failed project creation remains in Projects: OK'

# A discovery failure on initial render must remain a real menu failure, never
# degrade into the ordinary zero-project state or permit an agent launch.
export REMOTE_DEV_TEST_LIST_PROJECTS_FAIL=1
set +e
run_menu __unset__ $'1\n' "$output"
status=$?
set -e
unset REMOTE_DEV_TEST_LIST_PROJECTS_FAIL
[[ "$status" == 7 ]] || {
  echo "ERROR: synthetic project discovery failure returned status $status instead of 7" >&2
  exit 1
}
assert_file_lines "$invocations" 'project discovery failure'
grep -Fq 'ERROR: synthetic project listing failure' "$output"
if grep -Fq 'Project: none (create one in Projects...)' "$output"; then
  echo 'ERROR: project discovery failure was presented as an ordinary empty workspace' >&2
  exit 1
fi
echo 'Project discovery failures remain fail-closed during menu render: OK'

# The first render succeeds and persists the sole active project. Fail exactly
# the second listing, which occurs when Start refreshes that selection. The
# action must surface the producer error and must not invoke Codex using stale
# menu-session state.
rm -f "$list_counter"
export REMOTE_DEV_TEST_LIST_PROJECTS_COUNTER="$list_counter"
export REMOTE_DEV_TEST_LIST_PROJECTS_FAIL_ON_CALL=2
run_menu __unset__ $'1\n\n0\n' "$output"
unset REMOTE_DEV_TEST_LIST_PROJECTS_FAIL_ON_CALL REMOTE_DEV_TEST_LIST_PROJECTS_COUNTER
assert_file_lines "$invocations" 'mid-menu project discovery failure'
grep -Fq 'ERROR: synthetic project listing failure during action' "$output"
if grep -Fq 'ERROR: no projects are available under' "$output"; then
  echo 'ERROR: action-time project discovery failure was reinterpreted as zero projects' >&2
  exit 1
fi
echo 'Action-time project discovery failures block stale-project launches: OK'

run_menu __unset__ $'1\n1\n2\n2\n3\n3\n0\n' "$output" shell
assert_file_lines "$shell_invocations" 'Shell container shell' shell
assert_file_lines "$github_invocations" 'Shell GitHub CLI setup' \
  '[auth][login][--hostname][github.com][--git-protocol][https][--web]' \
  '[auth][setup-git]'
assert_file_lines "$doctor_invocations" 'Shell diagnostics' doctor
assert_hardening_count 2
grep -Fxq 'Remote Dev — Shell' "$output"
grep -Fxq '1) Open container shell' "$output"
grep -Fxq '2) Sign in to GitHub CLI' "$output"
grep -Fxq '3) Run diagnostics' "$output"
grep -Fxq '0) Exit this tmux session' "$output"

echo 'Shell menu result pauses: OK'

# Historical 4 Exit remains accepted without appearing on the screen.
run_menu __unset__ $'4\n' "$output" shell
assert_file_lines "$shell_invocations" 'Legacy Shell exit 4'
assert_hardening_count 0
grep -Fxq '0) Exit this tmux session' "$output"
echo 'Shell 0 Exit and 4 legacy alias: OK'