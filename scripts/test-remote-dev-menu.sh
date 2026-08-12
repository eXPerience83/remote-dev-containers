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
hardening_calls="$workdir/hardening-calls"

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

mkdir -p "$bin_dir" "$workdir/workspace/project"

cat > "$runtime_lib" <<'RUNTIME'
remote_dev_resolve_role() {
  printf '%s\n' "${REMOTE_DEV_TEST_ROLE:-codex}"
}

remote_dev_validate_workspace_root() {
  [[ "$1" == /* && -d "$1" && ! -L "$1" ]] || return 2
  printf '%s\n' "$1"
}

remote_dev_validate_project_name() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || return 2
  printf '%s\n' "$1"
}

remote_dev_list_projects() {
  local path name
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
    guarded) policy=untrusted ;;
    *) exit 2 ;;
  esac
  printf '%s\n' \
    'Inner sandbox: disabled explicitly' \
    'Isolation boundary: outer container' \
    "Codex approval mode: $mode" \
    "Codex approval policy: $policy" \
    "Mode source: $source"
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
    printf '%s\n' 'Context7: not configured'
    ;;
  install|test|update|remove)
    # Production deliberately omits --yes here so the real manager owns the
    # disclosure/confirmation prompt. Reject any accidental extra arguments.
    [[ "$#" == 1 ]] || exit 2
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
    REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls"
  )
  if [[ "$deployment_mode" == __unset__ ]]; then
    printf '%s' "$input" | env -u REMOTE_DEV_CODEX_APPROVAL_MODE "${common_env[@]}" "$fixture_menu" > "$output_file" 2>&1
  else
    printf '%s' "$input" | env REMOTE_DEV_CODEX_APPROVAL_MODE="$deployment_mode" "${common_env[@]}" "$fixture_menu" > "$output_file" 2>&1
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
run_menu __unset__ $'1\n1\n12\n' "$output"
assert_file_lines "$invocations" 'configured start' "[--cd][$project_path]"
assert_hardening_count 1
grep -Fxq 'Codex: bundled 0.147.0' "$output"
grep -Fxq 'Context7: not configured' "$output"
grep -Fxq 'Project: project' "$output"
grep -Fxq '1) Start Codex' "$output"
grep -Fxq '2) Resume a Codex session' "$output"
grep -Fxq '3) Projects...' "$output"
grep -Fxq '4) Approval mode for next launch...' "$output"
grep -Fxq '5) Update optional Codex runtime from official OpenAI release' "$output"
grep -Fxq '6) Remove optional Codex runtime (use bundled fallback)' "$output"
grep -Fxq '7) Context7 integration...' "$output"
grep -Fxq '12) Exit this tmux session' "$output"
grep -Fxq 'Next launch mode: configured (autonomous)' "$output"

echo 'Configured project-scoped Codex menu actions: OK'

run_menu __unset__ $'5\n5\n6\n6\n12\n' "$output"
assert_file_lines "$runtime_invocations" 'runtime menu actions' update remove
assert_hardening_count 2
echo 'Codex runtime update/remove result pauses: OK'

# Each successful Context7 action must consume its duplicate choice at the pause.
# If a pause disappears, the duplicate becomes an extra lifecycle invocation and this test fails.
run_menu __unset__ $'7\n1\n1\n2\n2\n3\n3\n4\n4\n5\n12\n' "$output"
assert_file_lines "$context7_invocations" 'Context7 menu actions' \
  'install' \
  'test' \
  'update' \
  'remove'
assert_hardening_count 4
grep -Fxq 'Remote Dev — Codex — Context7' "$output"
grep -Fxq 'Configuration/status are offline; only Test performs an explicit network check.' "$output"
grep -Fq 'Press Enter to return to the Context7 menu...' "$fixture_menu"
echo 'Context7 explicit menu actions: OK'

run_menu __unset__ $'8\n8\n9\n9\n10\n10\n11\n11\n12\n' "$output"
assert_file_lines "$codex_cli_invocations" 'Codex device login' '[login][--device-auth]'
assert_file_lines "$github_invocations" 'GitHub CLI setup' \
  '[auth][login][--hostname][github.com][--git-protocol][https][--web]' \
  '[auth][setup-git]'
assert_file_lines "$doctor_invocations" 'Codex diagnostics' doctor
assert_file_lines "$shell_invocations" 'Codex login shell' shell
assert_hardening_count 3
echo 'Codex login/GitHub/diagnostics/shell result pauses: OK'

run_menu __unset__ $'4\n3\n2\n2\n1\n1\n12\n' "$output"
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

run_menu guarded $'4\n2\n1\n1\n12\n' "$output"
assert_file_lines "$invocations" 'autonomous override of guarded deployment' \
  "[--approval-mode][autonomous][--cd][$project_path]"
assert_hardening_count 1
grep -Fxq 'Next launch mode: configured (guarded)' "$output"
grep -Fxq 'Next launch mode: autonomous (one launch)' "$output"

echo 'One-launch autonomous selection precedence: OK'

run_menu __unset__ $'4\n3\n4\n1\n1\n1\n12\n' "$output"
assert_file_lines "$invocations" 'configured-mode reset before launch' "[--cd][$project_path]"
assert_hardening_count 1

echo 'Configured-mode reset: OK'

fail_once="$workdir/fail-once"
rm -f "$fail_once"
export REMOTE_DEV_MENU_FAIL_ONCE_FILE="$fail_once"
run_menu __unset__ $'4\n3\n1\n1\n1\n1\n12\n' "$output"
unset REMOTE_DEV_MENU_FAIL_ONCE_FILE
assert_file_lines "$invocations" 'failed override then configured retry' \
  "[--approval-mode][guarded][--cd][$project_path]" \
  "[--cd][$project_path]"
assert_hardening_count 2
grep -Fq 'ERROR: Codex (guarded) exited with status 42' "$output"

echo 'Failed and successful action result pauses: OK'

# Exercise create, explicit selection, and exact-name deletion through the shared
# Projects menu without changing the persistent active-project contract.
run_menu __unset__ $'3\n2\nnew-project\n\n1\n2\n4\n1\n1\n12\n' "$output"
assert_file_lines "$invocations" 'selected existing project after create' "[--cd][$project_path]"
[[ -d "$workdir/workspace/new-project" ]]
grep -Fq "Created project: $workdir/workspace/new-project" "$output"

run_menu __unset__ $'3\n3\n1\nnew-project\n\n4\n12\n' "$output"
[[ ! -e "$workdir/workspace/new-project" ]]
grep -Fxq 'Deleted project: new-project' "$output"
echo 'Projects menu create/select/delete flow: OK'

run_menu __unset__ $'1\n1\n2\n2\n3\n3\n4\n' "$output" shell
assert_file_lines "$shell_invocations" 'Shell login shell' shell
assert_file_lines "$github_invocations" 'Shell GitHub CLI setup' \
  '[auth][login][--hostname][github.com][--git-protocol][https][--web]' \
  '[auth][setup-git]'
assert_file_lines "$doctor_invocations" 'Shell diagnostics' doctor
assert_hardening_count 2
grep -Fxq 'Remote Dev — Shell' "$output"
grep -Fxq '1) Open a login shell' "$output"
grep -Fxq '2) Sign in to GitHub CLI' "$output"
grep -Fxq '3) Run diagnostics' "$output"
grep -Fxq '4) Exit this tmux session' "$output"

echo 'Shell menu result pauses: OK'
