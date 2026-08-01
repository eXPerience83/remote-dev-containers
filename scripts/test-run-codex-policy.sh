#!/usr/bin/env bash
set -euo pipefail

workdir="$(mktemp -d)"
launcher_source=/usr/local/bin/run-codex
pinned_codex=/usr/local/bin/codex
test_codex="$workdir/codex"
test_launcher="$workdir/run-codex"
args_file="$workdir/args"

cleanup() {
  rm -rf "$workdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ ! -x "$launcher_source" ]]; then
  echo "ERROR: missing executable launcher: $launcher_source" >&2
  exit 1
fi
if [[ ! -x "$pinned_codex" ]]; then
  echo "ERROR: missing pinned Codex binary: $pinned_codex" >&2
  exit 1
fi
if ! grep -Fxq 'readonly codex_binary=/usr/local/bin/codex' "$launcher_source"; then
  echo "ERROR: run-codex does not pin /usr/local/bin/codex" >&2
  exit 1
fi

cat > "$test_codex" <<'FAKE_PINNED_CODEX'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" > "$REMOTE_DEV_CODEX_ARGS_FILE"
FAKE_PINNED_CODEX
chmod 0755 "$test_codex"

sed \
  "s|^readonly codex_binary=/usr/local/bin/codex$|readonly codex_binary=$test_codex|" \
  "$launcher_source" > "$test_launcher"
chmod 0755 "$test_launcher"

if ! grep -Fq "readonly codex_binary=$test_codex" "$test_launcher"; then
  echo "ERROR: failed to create an isolated run-codex test launcher" >&2
  exit 1
fi

mkdir -p "$workdir/path-bin"
cat > "$workdir/path-bin/codex" <<'FAKE_PATH_CODEX'
#!/usr/bin/env bash
echo 'ERROR: run-codex resolved Codex through PATH' >&2
exit 99
FAKE_PATH_CODEX
chmod 0755 "$workdir/path-bin/codex"

run_launcher() {
  local deployment_mode="$1"
  shift

  rm -f "$args_file"
  if [[ "$deployment_mode" == __unset__ ]]; then
    env -u REMOTE_DEV_CODEX_APPROVAL_MODE \
      PATH="$workdir/path-bin:$PATH" \
      REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
      "$test_launcher" "$@"
  else
    env REMOTE_DEV_CODEX_APPROVAL_MODE="$deployment_mode" \
      PATH="$workdir/path-bin:$PATH" \
      REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
      "$test_launcher" "$@"
  fi
}

assert_args() {
  local label="$1"
  shift
  local -a expected=("$@")
  local -a actual=()

  if [[ ! -f "$args_file" ]]; then
    echo "ERROR: $label did not invoke the pinned Codex fixture" >&2
    exit 1
  fi
  mapfile -t actual < "$args_file"

  if (( ${#actual[@]} != ${#expected[@]} )); then
    printf 'ERROR: %s passed %d arguments, expected %d\n' \
      "$label" "${#actual[@]}" "${#expected[@]}" >&2
    printf 'Actual: %q\n' "${actual[@]}" >&2
    printf 'Expected: %q\n' "${expected[@]}" >&2
    exit 1
  fi

  for index in "${!expected[@]}"; do
    if [[ "${actual[$index]}" != "${expected[$index]}" ]]; then
      printf 'ERROR: %s argument %d is %q, expected %q\n' \
        "$label" "$index" "${actual[$index]}" "${expected[$index]}" >&2
      exit 1
    fi
  done
}

run_launcher __unset__ resume --last
assert_args 'default autonomous mode' \
  --sandbox danger-full-access \
  --ask-for-approval never \
  resume --last

echo 'Codex default approval mode: autonomous'

run_launcher autonomous resume --last
assert_args 'deployment autonomous mode' \
  --sandbox danger-full-access \
  --ask-for-approval never \
  resume --last

run_launcher guarded resume --last
assert_args 'deployment guarded mode' \
  --sandbox danger-full-access \
  --ask-for-approval untrusted \
  resume --last

run_launcher guarded resume --approval-mode autonomous --last
assert_args 'per-launch override precedence' \
  --sandbox danger-full-access \
  --ask-for-approval never \
  resume --last

run_launcher autonomous --approval-mode=guarded resume
assert_args 'inline per-launch guarded mode' \
  --sandbox danger-full-access \
  --ask-for-approval untrusted \
  resume

echo 'Codex deployment and per-launch approval modes: OK'

assert_policy_output() {
  local label="$1"
  local expected_mode="$2"
  local expected_policy="$3"
  local expected_source="$4"
  shift 4
  local output=""

  output="$("$@")"
  expected_output="$(printf '%s\n' \
    'Inner sandbox: disabled explicitly' \
    'Isolation boundary: outer container' \
    "Codex approval mode: $expected_mode" \
    "Codex approval policy: $expected_policy" \
    "Mode source: $expected_source")"
  if [[ "$output" != "$expected_output" ]]; then
    printf 'ERROR: %s policy output differs\nExpected:\n%s\nActual:\n%s\n' \
      "$label" "$expected_output" "$output" >&2
    exit 1
  fi
}

assert_policy_output 'default policy report' autonomous never default \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --print-policy
assert_policy_output 'deployment policy report' guarded untrusted deployment \
  env REMOTE_DEV_CODEX_APPROVAL_MODE=guarded "$test_launcher" --print-policy
assert_policy_output 'per-launch policy report' autonomous never per-launch \
  env REMOTE_DEV_CODEX_APPROVAL_MODE=guarded "$test_launcher" --approval-mode autonomous --print-policy

echo 'Codex approval diagnostics: exact mode, policy and source'

assert_rejected() {
  local label="$1"
  shift
  local error_file="$workdir/rejected-error"
  local status=0

  rm -f "$args_file" "$error_file"
  if env -u REMOTE_DEV_CODEX_APPROVAL_MODE \
    PATH="$workdir/path-bin:$PATH" \
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
      "$test_launcher" "$@" >/dev/null 2>"$error_file"; then
    status=0
  else
    status=$?
  fi

  if (( status != 2 )); then
    echo "ERROR: $label returned status $status, expected 2" >&2
    cat "$error_file" >&2 || true
    exit 1
  fi
  if [[ -e "$args_file" ]]; then
    echo "ERROR: $label invoked Codex despite the rejected policy override" >&2
    exit 1
  fi
  if ! grep -Fq 'refusing argument:' "$error_file"; then
    echo "ERROR: $label did not explain the rejected policy override" >&2
    cat "$error_file" >&2 || true
    exit 1
  fi
}

assert_rejected 'long sandbox flag' --sandbox read-only
assert_rejected 'short sandbox flag' -s read-only
assert_rejected 'long approval flag' --ask-for-approval never
assert_rejected 'short approval flag' -a never
assert_rejected 'dangerous bypass flag' --dangerously-bypass-approvals-and-sandbox
assert_rejected 'yolo alias' --yolo
assert_rejected 'full-auto shortcut' --full-auto
assert_rejected 'short config sandbox override' -c 'sandbox_mode="read-only"'
assert_rejected 'long config approval override' --config 'approval_policy="never"'
assert_rejected 'spaced config approval override' --config ' approval_policy = "never" '
assert_rejected 'inline config sandbox override' '--config=sandbox_mode="workspace-write"'
assert_rejected 'profile config approval override' -c 'profiles.test.approval_policy="never"'

echo 'Direct upstream Codex policy overrides: rejected'

assert_invalid_mode() {
  local label="$1"
  local expected_text="$2"
  shift 2
  local error_file="$workdir/mode-error"
  local status=0

  rm -f "$args_file" "$error_file"
  if PATH="$workdir/path-bin:$PATH" \
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
      "$@" >/dev/null 2>"$error_file"; then
    status=0
  else
    status=$?
  fi

  if (( status != 2 )); then
    echo "ERROR: $label returned status $status, expected 2" >&2
    cat "$error_file" >&2 || true
    exit 1
  fi
  if [[ -e "$args_file" ]]; then
    echo "ERROR: $label invoked Codex despite invalid project-owned policy input" >&2
    exit 1
  fi
  if ! grep -Fq -- "$expected_text" "$error_file"; then
    printf 'ERROR: %s did not report %q\n' "$label" "$expected_text" >&2
    cat "$error_file" >&2 || true
    exit 1
  fi
}

assert_invalid_mode 'invalid deployment mode' 'unsupported deployment approval mode' \
  env REMOTE_DEV_CODEX_APPROVAL_MODE='guarded;id' "$test_launcher"
assert_invalid_mode 'invalid explicit mode' 'unsupported per-launch approval mode' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --approval-mode 'autonomous;id'
assert_invalid_mode 'missing explicit mode' '--approval-mode requires autonomous or guarded' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --approval-mode
assert_invalid_mode 'empty inline explicit mode' '--approval-mode requires autonomous or guarded' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --approval-mode=
assert_invalid_mode 'duplicate explicit mode' '--approval-mode may be specified only once' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --approval-mode autonomous --approval-mode guarded
assert_invalid_mode 'policy report with Codex arguments' '--print-policy cannot be combined with Codex arguments' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --print-policy resume

echo 'Invalid Codex approval modes: rejected without execution'

run_launcher guarded -- --approval-mode autonomous --sandbox-is-prompt-text
assert_args 'option separator preservation' \
  --sandbox danger-full-access \
  --ask-for-approval untrusted \
  -- --approval-mode autonomous --sandbox-is-prompt-text

echo 'Codex launcher option separator: preserved'
