#!/usr/bin/env bash
set -euo pipefail

menu_source="${REMOTE_DEV_MENU:-/usr/local/bin/remote-dev-menu}"
workdir="$(mktemp -d)"
fixture_menu="$workdir/remote-dev-menu"
runtime_lib="$workdir/remote-dev-runtime.sh"
run_codex="$workdir/run-codex"
secure_state="$workdir/secure-persistent-state"
bin_dir="$workdir/bin"
invocations="$workdir/invocations"
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
RUN_CODEX
chmod 0755 "$run_codex"

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
  -e "s|/usr/local/bin/secure-persistent-state|$secure_state|g" \
  "$menu_source" > "$fixture_menu"
chmod 0755 "$fixture_menu"

assert_file_lines() {
  local label="$1"
  shift
  local -a expected=("$@")
  local -a actual=()

  if [[ -f "$invocations" ]]; then
    mapfile -t actual < "$invocations"
  fi
  if (( ${#actual[@]} != ${#expected[@]} )); then
    printf 'ERROR: %s recorded %d invocations, expected %d\n' \
      "$label" "${#actual[@]}" "${#expected[@]}" >&2
    printf 'Actual: %s\n' "${actual[*]:-<none>}" >&2
    exit 1
  fi
  for index in "${!expected[@]}"; do
    if [[ "${actual[$index]}" != "${expected[$index]}" ]]; then
      printf 'ERROR: %s invocation %d is %q, expected %q\n' \
        "$label" "$index" "${actual[$index]}" "${expected[$index]}" >&2
      exit 1
    fi
  done
}

run_menu() {
  local deployment_mode="$1"
  local input="$2"
  local output_file="$3"

  rm -f "$invocations" "$hardening_calls"
  if [[ "$deployment_mode" == __unset__ ]]; then
    printf '%s' "$input" | env -u REMOTE_DEV_CODEX_APPROVAL_MODE \
      PATH="$bin_dir:$PATH" \
      WORKSPACE="$workdir/workspace" \
      REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
      REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
      "$fixture_menu" > "$output_file"
  else
    printf '%s' "$input" | env REMOTE_DEV_CODEX_APPROVAL_MODE="$deployment_mode" \
      PATH="$bin_dir:$PATH" \
      WORKSPACE="$workdir/workspace" \
      REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
      REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
      "$fixture_menu" > "$output_file"
  fi
}

assert_hardening_count() {
  local expected="$1"
  local actual=0
  if [[ -f "$hardening_calls" ]]; then
    actual="$(wc -l < "$hardening_calls")"
  fi
  if (( actual != expected )); then
    echo "ERROR: persistent-state hardening ran $actual times, expected $expected" >&2
    exit 1
  fi
}

output="$workdir/output"
run_menu __unset__ $'1\n8\n' "$output"
assert_file_lines 'configured start' '[]'
assert_hardening_count 1
grep -Fxq '1) Start Codex' "$output"
grep -Fxq '2) Resume a Codex session' "$output"
grep -Fxq '3) Approval mode for next launch...' "$output"
grep -Fxq 'Next launch mode: configured (autonomous)' "$output"
if grep -Fq 'Start Codex with a one-time mode' "$output"; then
  echo "ERROR: the duplicate one-time start action remains in the menu" >&2
  exit 1
fi

echo 'Configured Codex menu actions: OK'

run_menu __unset__ $'3\n3\n2\n1\n8\n' "$output"
assert_file_lines 'guarded resume then configured start' \
  '[--approval-mode][guarded][resume]' \
  '[]'
assert_hardening_count 2
grep -Fxq 'Next launch mode: guarded (one launch)' "$output"
if [[ "$(grep -Fxc 'Next launch mode: configured (autonomous)' "$output")" -lt 2 ]]; then
  echo "ERROR: the guarded override was not consumed after one launch" >&2
  exit 1
fi

echo 'One-launch guarded selection and reset: OK'

run_menu guarded $'3\n2\n1\n8\n' "$output"
assert_file_lines 'autonomous override of guarded deployment' \
  '[--approval-mode][autonomous]'
assert_hardening_count 1
grep -Fxq 'Next launch mode: configured (guarded)' "$output"
grep -Fxq 'Next launch mode: autonomous (one launch)' "$output"

echo 'One-launch autonomous selection precedence: OK'

run_menu __unset__ $'3\n3\n3\n1\n1\n8\n' "$output"
assert_file_lines 'configured-mode reset before launch' '[]'
assert_hardening_count 1

echo 'Configured-mode reset: OK'
