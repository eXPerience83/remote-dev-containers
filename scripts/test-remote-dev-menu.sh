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

mkdir -p "$bin_dir" "$workdir/workspace"

cat > "$runtime_lib" <<'RUNTIME'
remote_dev_resolve_role() {
  printf '%s\n' codex
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
    [[ "${2:-}" == --menu ]] || exit 2
    printf '%s\n' 'Context7: not configured'
    ;;
  install|test|update|remove)
    printf '%s\n' "$1" >> "$REMOTE_DEV_MENU_CONTEXT7_INVOCATIONS"
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
chmod 0755 "$bin_dir/remote-dev-version"

cat > "$bin_dir/clear" <<'CLEAR'
#!/usr/bin/env bash
exit 0
CLEAR
chmod 0755 "$bin_dir/clear"

sed \
  -e "s|^runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh$|runtime_lib=$runtime_lib|" \
  -e "s|/usr/local/bin/run-codex|$run_codex|g" \
  -e "s|/usr/local/bin/remote-dev-codex-runtime|$codex_runtime|g" \
  -e "s|/usr/local/bin/remote-dev-context7|$context7_manager|g" \
  -e "s|/usr/local/bin/secure-persistent-state|$secure_state|g" \
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
  local deployment_mode="$1" input="$2" output_file="$3"
  rm -f "$invocations" "$runtime_invocations" "$context7_invocations" "$hardening_calls"
  common_env=(
    PATH="$bin_dir:$PATH"
    WORKSPACE="$workdir/workspace"
    REMOTE_DEV_MENU_INVOCATIONS="$invocations"
    REMOTE_DEV_MENU_RUNTIME_INVOCATIONS="$runtime_invocations"
    REMOTE_DEV_MENU_CONTEXT7_INVOCATIONS="$context7_invocations"
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

output="$workdir/output"
run_menu __unset__ $'1\n11\n' "$output"
assert_file_lines "$invocations" 'configured start' '[]'
assert_hardening_count 1
grep -Fxq 'Codex: bundled 0.147.0' "$output"
grep -Fxq 'Context7: not configured' "$output"
grep -Fxq '1) Start Codex' "$output"
grep -Fxq '2) Resume a Codex session' "$output"
grep -Fxq '3) Approval mode for next launch...' "$output"
grep -Fxq '4) Update optional Codex runtime from official OpenAI release' "$output"
grep -Fxq '5) Remove optional Codex runtime (use bundled fallback)' "$output"
grep -Fxq '6) Context7 integration...' "$output"
grep -Fxq 'Next launch mode: configured (autonomous)' "$output"

echo 'Configured Codex menu actions: OK'

run_menu __unset__ $'4\n5\n11\n' "$output"
assert_file_lines "$runtime_invocations" 'runtime menu actions' update remove
assert_hardening_count 2
echo 'Codex runtime update/remove menu actions: OK'

run_menu __unset__ $'6\n1\n\n2\n\n3\n\n4\n\n5\n11\n' "$output"
assert_file_lines "$context7_invocations" 'Context7 menu actions' install test update remove
assert_hardening_count 4
grep -Fxq 'Remote Dev — Codex — Context7' "$output"
grep -Fxq 'Configuration/status are offline; only Test performs an explicit network check.' "$output"
grep -Fq 'Press Enter to return to the Context7 menu...' "$fixture_menu"
echo 'Context7 explicit menu actions: OK'

run_menu __unset__ $'3\n3\n2\n1\n11\n' "$output"
assert_file_lines "$invocations" 'guarded resume then configured start' \
  '[--approval-mode][guarded][resume]' \
  '[]'
assert_hardening_count 2
grep -Fxq 'Next launch mode: guarded (one launch)' "$output"
if [[ "$(grep -Fxc 'Next launch mode: configured (autonomous)' "$output")" -lt 2 ]]; then
  echo "ERROR: the guarded override was not consumed after one launch" >&2
  exit 1
fi

echo 'One-launch guarded selection and reset: OK'

run_menu guarded $'3\n2\n1\n11\n' "$output"
assert_file_lines "$invocations" 'autonomous override of guarded deployment' '[--approval-mode][autonomous]'
assert_hardening_count 1
grep -Fxq 'Next launch mode: configured (guarded)' "$output"
grep -Fxq 'Next launch mode: autonomous (one launch)' "$output"

echo 'One-launch autonomous selection precedence: OK'

run_menu __unset__ $'3\n3\n3\n1\n1\n11\n' "$output"
assert_file_lines "$invocations" 'configured-mode reset before launch' '[]'
assert_hardening_count 1

echo 'Configured-mode reset: OK'

fail_once="$workdir/fail-once"
rm -f "$fail_once"
export REMOTE_DEV_MENU_FAIL_ONCE_FILE="$fail_once"
run_menu __unset__ $'3\n3\n1\n\n1\n11\n' "$output"
unset REMOTE_DEV_MENU_FAIL_ONCE_FILE
assert_file_lines "$invocations" 'failed override then configured retry' \
  '[--approval-mode][guarded]' \
  '[]'
assert_hardening_count 2
grep -Fq 'ERROR: Codex (guarded) exited with status 42' "$output"

echo 'Failed one-launch override consumption: OK'
