#!/usr/bin/env bash
set -euo pipefail

launcher_source=/usr/local/bin/run-codex
workdir="$(mktemp -d)"
test_launcher="$workdir/run-codex"
test_codex="$workdir/codex"
test_runtime_manager="$workdir/remote-dev-codex-runtime"
test_context7_manager="$workdir/remote-dev-context7"
key_file="$workdir/.remote-dev-context7/api-key"
env_file="$workdir/context7-env"
args_file="$workdir/args"
readonly synthetic_key='ctx7-test-key-do-not-use'

cleanup() {
  rm -rf "$workdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for expected in \
  'readonly runtime_manager=/usr/local/bin/remote-dev-codex-runtime' \
  'readonly context7_manager=/usr/local/bin/remote-dev-context7'; do
  if ! grep -Fxq "$expected" "$launcher_source"; then
    echo "ERROR: run-codex is missing expected managed dependency: $expected" >&2
    exit 1
  fi
done

cat > "$test_codex" <<'CODEX'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${CONTEXT7_API_KEY-__unset__}" > "$REMOTE_DEV_TEST_CONTEXT7_ENV_FILE"
printf '%s\n' "$@" > "$REMOTE_DEV_TEST_CODEX_ARGS_FILE"
CODEX
chmod 0755 "$test_codex"

cat > "$test_runtime_manager" <<'RUNTIME'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == resolve ]] || exit 98
printf '%s\n' "$REMOTE_DEV_TEST_CODEX"
RUNTIME
chmod 0755 "$test_runtime_manager"

cat > "$test_context7_manager" <<'CONTEXT7'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == key-file && "${2:-}" == --active ]] || exit 97
case "${REMOTE_DEV_TEST_CONTEXT7_STATE:-unmanaged}" in
  key)
    printf '%s\n' "$REMOTE_DEV_TEST_CONTEXT7_KEY_FILE"
    ;;
  wrong-path)
    printf '%s\n' "${REMOTE_DEV_TEST_CONTEXT7_KEY_FILE}.wrong"
    ;;
  unmanaged)
    exit 4
    ;;
  anonymous)
    exit 5
    ;;
  unsafe)
    exit 3
    ;;
  *)
    exit 96
    ;;
esac
CONTEXT7
chmod 0755 "$test_context7_manager"

sed \
  -e "s|^readonly runtime_manager=/usr/local/bin/remote-dev-codex-runtime$|readonly runtime_manager=$test_runtime_manager|" \
  -e "s|^readonly context7_manager=/usr/local/bin/remote-dev-context7$|readonly context7_manager=$test_context7_manager|" \
  "$launcher_source" > "$test_launcher"
chmod 0755 "$test_launcher"

mkdir -p "$(dirname "$key_file")"
printf '%s' "$synthetic_key" > "$key_file"
chmod 0600 "$key_file"

run_case() {
  local state="$1" inherited="$2" output="$3"
  rm -f "$env_file" "$args_file" "$output"
  common_env=(
    REMOTE_DEV_TEST_CODEX="$test_codex"
    REMOTE_DEV_TEST_CONTEXT7_STATE="$state"
    REMOTE_DEV_TEST_CONTEXT7_KEY_FILE="$key_file"
    REMOTE_DEV_TEST_CONTEXT7_ENV_FILE="$env_file"
    REMOTE_DEV_TEST_CODEX_ARGS_FILE="$args_file"
    CODEX_HOME="$workdir"
  )
  if [[ "$inherited" == __unset__ ]]; then
    env -u CONTEXT7_API_KEY "${common_env[@]}" "$test_launcher" resume --last >"$output" 2>&1
  else
    env CONTEXT7_API_KEY="$inherited" "${common_env[@]}" "$test_launcher" resume --last >"$output" 2>&1
  fi
}

read_env() {
  local value=""
  IFS= read -r value < "$env_file"
  printf '%s\n' "$value"
}

assert_rejected_key() {
  local label="$1" state="$2" warning="$3"
  run_case "$state" stale-inherited-key "$output"
  if [[ "$(read_env)" != __unset__ ]]; then
    echo "ERROR: $label exposed a Context7 API key" >&2
    exit 1
  fi
  if ! grep -Fq "$warning" "$output"; then
    echo "ERROR: $label did not emit the expected bounded warning" >&2
    exit 1
  fi
  if grep -Fq 'stale-inherited-key' "$output"; then
    echo "ERROR: $label leaked an inherited Context7 API key" >&2
    exit 1
  fi
}

restore_valid_key() {
  rm -f "$key_file"
  printf '%s' "$synthetic_key" > "$key_file"
  chmod 0600 "$key_file"
}

output="$workdir/output"
run_case key __unset__ "$output"
if [[ "$(read_env)" != "$synthetic_key" ]]; then
  echo 'ERROR: managed Context7 key was not exported only into the Codex process' >&2
  exit 1
fi
if grep -Fq "$synthetic_key" "$output"; then
  echo 'ERROR: managed Context7 key leaked into launcher output' >&2
  exit 1
fi

echo 'Managed Context7 key injection: OK'

assert_rejected_key \
  'wrong managed key path' \
  wrong-path \
  'managed Context7 credential path failed validation'

real_key_file="$workdir/real-context7-key"
printf '%s' "$synthetic_key" > "$real_key_file"
chmod 0600 "$real_key_file"
rm -f "$key_file"
ln -s "$real_key_file" "$key_file"
assert_rejected_key \
  'symlinked managed key file' \
  key \
  'managed Context7 credential path failed validation'
restore_valid_key

: > "$key_file"
chmod 0600 "$key_file"
assert_rejected_key \
  'empty managed key file' \
  key \
  'managed Context7 credential could not be read safely'
restore_valid_key

printf '%s' 'ctx7 key with whitespace' > "$key_file"
chmod 0600 "$key_file"
assert_rejected_key \
  'whitespace-containing managed key file' \
  key \
  'managed Context7 credential could not be read safely'
restore_valid_key

python3 -c 'print("x" * 16385, end="")' > "$key_file"
chmod 0600 "$key_file"
assert_rejected_key \
  'oversized managed key file' \
  key \
  'managed Context7 credential could not be read safely'
restore_valid_key

echo 'Managed Context7 local key-file rejection cases: OK'

run_case anonymous stale-inherited-key "$output"
if [[ "$(read_env)" != __unset__ ]]; then
  echo 'ERROR: managed anonymous Context7 state inherited an unrelated API key' >&2
  exit 1
fi
if grep -Fq 'stale-inherited-key' "$output"; then
  echo 'ERROR: inherited Context7 key leaked into launcher output' >&2
  exit 1
fi
if grep -Fq 'WARNING:' "$output"; then
  echo 'ERROR: healthy anonymous Context7 state produced an unexpected warning' >&2
  exit 1
fi

echo 'Managed anonymous Context7 launch: inherited key suppressed'

run_case unsafe stale-inherited-key "$output"
if [[ "$(read_env)" != __unset__ ]]; then
  echo 'ERROR: unsafe managed Context7 state exposed an inherited API key' >&2
  exit 1
fi
if ! grep -Fq 'managed Context7 state is unavailable or unsafe' "$output"; then
  echo 'ERROR: unsafe managed Context7 state did not produce a bounded warning' >&2
  exit 1
fi

echo 'Unsafe managed Context7 credential state: key suppressed'

run_case unmanaged user-owned-key "$output"
if [[ "$(read_env)" != user-owned-key ]]; then
  echo 'ERROR: run-codex modified an unmanaged user-owned Context7 environment' >&2
  exit 1
fi

echo 'Unmanaged Context7 environment: preserved'

mapfile -t actual_args < "$args_file"
expected_args=(
  --sandbox danger-full-access
  --ask-for-approval never
  resume --last
)
if (( ${#actual_args[@]} != ${#expected_args[@]} )); then
  echo 'ERROR: Context7 integration changed Codex argument count' >&2
  exit 1
fi
for index in "${!expected_args[@]}"; do
  if [[ "${actual_args[$index]}" != "${expected_args[$index]}" ]]; then
    echo "ERROR: Context7 integration changed Codex argument $index" >&2
    exit 1
  fi
done

echo 'Context7 credential injection leaves Codex policy arguments unchanged: OK'