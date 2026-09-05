#!/usr/bin/env bash
set -euo pipefail

workdir="$(mktemp -d)"
launcher_source=/usr/local/bin/run-codex
pinned_codex=/usr/local/bin/codex
runtime_manager_source=/usr/local/bin/remote-dev-codex-runtime
validator_source=/usr/local/bin/validate-codex-project-boundary
test_bundled_codex="$workdir/bundled-codex"
test_runtime_codex="$workdir/runtime-codex"
test_runtime_manager="$workdir/remote-dev-codex-runtime"
test_validator="$workdir/validate-codex-project-boundary"
test_launcher="$workdir/run-codex"
args_file="$workdir/args"
identity_file="$workdir/identity"
env_file="$workdir/env"
validator_file="$workdir/validator"
workspace="$workdir/workspace"
default_project="$workspace/default"
project_a="$workspace/project-a"
project_b="$workspace/project-b"
mkdir -p "$default_project" "$project_a" "$project_b"

cleanup() {
  rm -rf "$workdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for required in "$launcher_source" "$pinned_codex" "$runtime_manager_source" "$validator_source"; do
  [[ -x "$required" ]] || { echo "ERROR: missing executable: $required" >&2; exit 1; }
done

grep -Fxq 'readonly bundled_codex_binary=/usr/local/bin/codex' "$launcher_source" \
  || { echo "ERROR: run-codex does not retain bundled fallback" >&2; exit 1; }
grep -Fxq 'readonly runtime_manager=/usr/local/bin/remote-dev-codex-runtime' "$launcher_source" \
  || { echo "ERROR: run-codex does not use runtime resolver" >&2; exit 1; }
grep -Fxq 'readonly project_boundary_validator=/usr/local/bin/validate-codex-project-boundary' "$launcher_source" \
  || { echo "ERROR: run-codex does not own the project-boundary validator" >&2; exit 1; }

cat >"$test_bundled_codex" <<'FAKE_CODEX'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' bundled >"$REMOTE_DEV_CODEX_IDENTITY_FILE"
printf '%s\n' "$@" >"$REMOTE_DEV_CODEX_ARGS_FILE"
printf '%s\n' "${GIT_CEILING_DIRECTORIES:-}" >"$REMOTE_DEV_CODEX_ENV_FILE"
FAKE_CODEX
chmod 0755 "$test_bundled_codex"

cat >"$test_runtime_codex" <<'FAKE_CODEX'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' runtime >"$REMOTE_DEV_CODEX_IDENTITY_FILE"
printf '%s\n' "$@" >"$REMOTE_DEV_CODEX_ARGS_FILE"
printf '%s\n' "${GIT_CEILING_DIRECTORIES:-}" >"$REMOTE_DEV_CODEX_ENV_FILE"
FAKE_CODEX
chmod 0755 "$test_runtime_codex"

cat >"$test_runtime_manager" <<'FAKE_MANAGER'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == resolve ]] || exit 98
[[ "${REMOTE_DEV_TEST_RESOLVER_FAIL:-0}" != 1 ]] || exit 97
printf '%s\n' "$REMOTE_DEV_TEST_RUNTIME_CODEX"
FAKE_MANAGER
chmod 0755 "$test_runtime_manager"

cat >"$test_validator" <<'FAKE_VALIDATOR'
#!/usr/bin/env bash
set -euo pipefail
: >"$REMOTE_DEV_CODEX_VALIDATOR_FILE"
printf '%s\n' "$@" >"$REMOTE_DEV_CODEX_VALIDATOR_FILE"
printf 'ceiling=%s\n' "${GIT_CEILING_DIRECTORIES:-}" >>"$REMOTE_DEV_CODEX_VALIDATOR_FILE"
[[ "${REMOTE_DEV_TEST_VALIDATOR_FAIL:-0}" != 1 ]] || exit 2
FAKE_VALIDATOR
chmod 0755 "$test_validator"

sed \
  -e "s|^readonly codex_binary=/usr/local/bin/codex$|readonly codex_binary=$test_bundled_codex|" \
  -e "s|^readonly bundled_codex_binary=/usr/local/bin/codex$|readonly bundled_codex_binary=$test_bundled_codex|" \
  -e "s|^readonly runtime_manager=/usr/local/bin/remote-dev-codex-runtime$|readonly runtime_manager=$test_runtime_manager|" \
  -e "s|^readonly project_boundary_validator=/usr/local/bin/validate-codex-project-boundary$|readonly project_boundary_validator=$test_validator|" \
  "$launcher_source" >"$test_launcher"
chmod 0755 "$test_launcher"

run_launcher_at() {
  local root="$1"
  local cwd="$2"
  local deployment_mode="$3"
  shift 3

  rm -f "$args_file" "$identity_file" "$env_file" "$validator_file"
  common_env=(
    WORKSPACE="$root"
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file"
    REMOTE_DEV_CODEX_IDENTITY_FILE="$identity_file"
    REMOTE_DEV_CODEX_ENV_FILE="$env_file"
    REMOTE_DEV_CODEX_VALIDATOR_FILE="$validator_file"
    REMOTE_DEV_TEST_RUNTIME_CODEX="$test_runtime_codex"
  )
  if [[ "$deployment_mode" == __unset__ ]]; then
    (cd "$cwd" && env -u REMOTE_DEV_CODEX_APPROVAL_MODE "${common_env[@]}" "$test_launcher" "$@")
  else
    (cd "$cwd" && env REMOTE_DEV_CODEX_APPROVAL_MODE="$deployment_mode" "${common_env[@]}" "$test_launcher" "$@")
  fi
}

run_launcher() {
  local deployment_mode="$1"
  shift
  run_launcher_at "$workspace" "$default_project" "$deployment_mode" "$@"
}

assert_args() {
  local label="$1"
  shift
  local -a expected=("$@") actual=()
  [[ -f "$args_file" ]] || { echo "ERROR: $label did not invoke Codex" >&2; exit 1; }
  mapfile -t actual <"$args_file"
  (( ${#actual[@]} == ${#expected[@]} )) || {
    printf 'ERROR: %s argument count differs\nActual: %q\nExpected: %q\n' "$label" "${actual[*]}" "${expected[*]}" >&2
    exit 1
  }
  for index in "${!expected[@]}"; do
    [[ "${actual[$index]}" == "${expected[$index]}" ]] || {
      printf 'ERROR: %s argument %d is %q, expected %q\n' "$label" "$index" "${actual[$index]}" "${expected[$index]}" >&2
      exit 1
    }
  done
}

assert_identity() {
  local expected="$1" label="$2"
  [[ -f "$identity_file" ]] || { echo "ERROR: $label did not record executable" >&2; exit 1; }
  [[ "$(<"$identity_file")" == "$expected" ]] || { echo "ERROR: $label used wrong executable" >&2; exit 1; }
}

assert_validator() {
  local project="$1"
  [[ -f "$validator_file" ]] || { echo "ERROR: boundary validator did not run" >&2; exit 1; }
  grep -Fxq -- '--codex-binary' "$validator_file"
  grep -Fxq -- "$test_runtime_codex" "$validator_file"
  grep -Fxq -- '--cwd' "$validator_file"
  grep -Fxq -- "$project" "$validator_file"
  grep -Fxq -- '--ceiling' "$validator_file"
  grep -Fxq -- "$workspace" "$validator_file"
  grep -Fxq -- "ceiling=$workspace" "$validator_file"
}

ceiling_arg="shell_environment_policy.set.GIT_CEILING_DIRECTORIES=\"$workspace\""

autonomous_expected=(--sandbox danger-full-access -c "$ceiling_arg" --ask-for-approval never)
run_launcher __unset__ resume --last
assert_args 'default autonomous mode' "${autonomous_expected[@]}" resume --last
assert_identity runtime 'default autonomous mode'
assert_validator "$default_project"
[[ "$(<"$env_file")" == "$workspace" ]] || { echo 'ERROR: Codex process missed Git ceiling' >&2; exit 1; }

run_launcher guarded --cd "$project_a" resume --last
assert_args 'guarded project A' \
  --sandbox danger-full-access \
  -c "$ceiling_arg" \
  -c "projects={\"$project_a\"={trust_level=\"untrusted\"}}" \
  --cd "$project_a" resume --last
assert_validator "$project_a"

run_launcher guarded --approval-mode autonomous --cd "$project_b"
assert_args 'per-launch autonomous override' \
  --sandbox danger-full-access \
  -c "$ceiling_arg" \
  --ask-for-approval never \
  --cd "$project_b"
assert_validator "$project_b"

echo 'Codex managed Git ceiling: autonomous, guarded and selected-project launches OK'

# Resolver failure still uses immutable bundled fallback and validates that
# exact executable before launch.
rm -f "$args_file" "$identity_file" "$env_file" "$validator_file"
(
  cd "$default_project"
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE \
    WORKSPACE="$workspace" \
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
    REMOTE_DEV_CODEX_IDENTITY_FILE="$identity_file" \
    REMOTE_DEV_CODEX_ENV_FILE="$env_file" \
    REMOTE_DEV_CODEX_VALIDATOR_FILE="$validator_file" \
    REMOTE_DEV_TEST_RUNTIME_CODEX="$test_runtime_codex" \
    REMOTE_DEV_TEST_RESOLVER_FAIL=1 \
    "$test_launcher" resume --last 2>"$workdir/fallback-error"
)
assert_identity bundled 'resolver fallback'
grep -Fq 'using immutable bundled fallback' "$workdir/fallback-error"
grep -Fxq -- "$test_bundled_codex" "$validator_file"

# Informational top-level commands remain usable without a project/collection
# and do not invoke the project-boundary validator.
info_root="$workdir/no-workspace"
mkdir -p "$info_root"
run_launcher_at "$info_root/missing" "$info_root" __unset__ --version
assert_args 'top-level version' --sandbox danger-full-access --ask-for-approval never --version
[[ ! -e "$validator_file" ]] || { echo 'ERROR: informational command invoked boundary validator' >&2; exit 1; }

echo 'Codex informational commands remain project-independent'

assert_policy_output() {
  local label="$1" expected_mode="$2" expected_source="$3"
  shift 3
  local output expected_output
  output="$("$@")"
  expected_output="$(printf '%s\n' \
    'Inner sandbox: disabled explicitly' \
    'Isolation boundary: outer container' \
    "Codex approval mode: $expected_mode")"
  if [[ "$expected_mode" == guarded ]]; then
    expected_output+=$'\nProject trust: untrusted (launch-scoped)\nApproval behavior: prompt for commands except explicit exec-policy allows'
  else
    expected_output+=$'\nCodex approval policy: never'
  fi
  expected_output+=$'\n'"Mode source: $expected_source"
  [[ "$output" == "$expected_output" ]] || {
    printf 'ERROR: %s policy output differs\nExpected:\n%s\nActual:\n%s\n' "$label" "$expected_output" "$output" >&2
    exit 1
  }
}

assert_policy_output 'default policy report' autonomous default \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --print-policy
assert_policy_output 'deployment policy report' guarded deployment \
  env REMOTE_DEV_CODEX_APPROVAL_MODE=guarded "$test_launcher" --print-policy
assert_policy_output 'per-launch policy report' autonomous per-launch \
  env REMOTE_DEV_CODEX_APPROVAL_MODE=guarded "$test_launcher" --approval-mode autonomous --print-policy

assert_rejected() {
  local label="$1"
  shift
  local status=0 error_file="$workdir/rejected-error"
  rm -f "$args_file" "$identity_file" "$env_file" "$validator_file" "$error_file"
  run_launcher __unset__ "$@" >/dev/null 2>"$error_file" || status=$?
  (( status == 2 )) || { echo "ERROR: $label returned $status, expected 2" >&2; cat "$error_file" >&2; exit 1; }
  [[ ! -e "$args_file" ]] || { echo "ERROR: $label invoked Codex" >&2; exit 1; }
  grep -Fq 'refusing argument:' "$error_file" || { echo "ERROR: $label lacked refusal diagnostic" >&2; cat "$error_file" >&2; exit 1; }
}

assert_rejected 'sandbox override' --sandbox read-only
assert_rejected 'approval override' --ask-for-approval never
assert_rejected 'dangerous bypass' --dangerously-bypass-approvals-and-sandbox
assert_rejected 'profile selection' --profile test
assert_rejected 'project trust override' -c 'projects={"/workspace"={trust_level="trusted"}}'
assert_rejected 'shell policy set override' -c 'shell_environment_policy.set.GIT_CEILING_DIRECTORIES="/tmp"'
assert_rejected 'shell include override' --config 'shell_environment_policy.include_only=["PATH"]'

echo 'Direct Codex policy/project-boundary overrides: rejected'

assert_invalid_mode() {
  local label="$1" expected_text="$2"
  shift 2
  local status=0 error_file="$workdir/mode-error"
  rm -f "$args_file" "$identity_file" "$error_file"
  (cd "$default_project" && WORKSPACE="$workspace" "$@") >/dev/null 2>"$error_file" || status=$?
  (( status == 2 )) || { echo "ERROR: $label returned $status, expected 2" >&2; cat "$error_file" >&2; exit 1; }
  grep -Fq -- "$expected_text" "$error_file" || { echo "ERROR: $label lacked expected diagnostic" >&2; cat "$error_file" >&2; exit 1; }
}

assert_invalid_mode 'invalid deployment mode' 'unsupported deployment approval mode' \
  env REMOTE_DEV_CODEX_APPROVAL_MODE='guarded;id' "$test_launcher"
assert_invalid_mode 'invalid explicit mode' 'unsupported per-launch approval mode' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --approval-mode 'autonomous;id'
assert_invalid_mode 'missing explicit mode' '--approval-mode requires autonomous or guarded' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --approval-mode
assert_invalid_mode 'missing config value' '--config requires a value' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --config

echo 'Invalid Codex launch-owned policy input: rejected without execution'

# If the effective-policy validator fails, the resolved Codex binary is never
# launched even though the collection itself is healthy.
rm -f "$args_file" "$identity_file" "$env_file" "$validator_file"
status=0
(
  cd "$default_project"
  env WORKSPACE="$workspace" \
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
    REMOTE_DEV_CODEX_IDENTITY_FILE="$identity_file" \
    REMOTE_DEV_CODEX_ENV_FILE="$env_file" \
    REMOTE_DEV_CODEX_VALIDATOR_FILE="$validator_file" \
    REMOTE_DEV_TEST_RUNTIME_CODEX="$test_runtime_codex" \
    REMOTE_DEV_TEST_VALIDATOR_FAIL=1 \
    "$test_launcher"
) >/dev/null 2>"$workdir/validator-error" || status=$?
(( status == 2 )) || { echo "ERROR: validator failure returned $status" >&2; exit 1; }
[[ -e "$validator_file" && ! -e "$args_file" ]] || { echo 'ERROR: failed validator did not block Codex execution' >&2; exit 1; }
grep -Fq 'cannot preserve the required project Git boundary' "$workdir/validator-error"

# A contaminated collection blocks before the validator or vendor binary runs.
contaminated="$workdir/contaminated"
mkdir -p "$contaminated/project"
git -C "$contaminated" init -q
rm -f "$args_file" "$identity_file" "$env_file" "$validator_file"
status=0
run_launcher_at "$contaminated" "$contaminated/project" __unset__ >/dev/null 2>"$workdir/contamination-error" || status=$?
(( status == 2 )) || { echo "ERROR: contaminated collection returned $status" >&2; exit 1; }
[[ ! -e "$args_file" && ! -e "$validator_file" ]] || { echo 'ERROR: contaminated collection reached validator/vendor' >&2; exit 1; }
grep -Fq 'CRITICAL: project collection root contains .git' "$workdir/contamination-error"

echo 'Codex collection contamination and incompatible effective policy: fail closed'

run_launcher guarded -- --approval-mode autonomous --sandbox-is-prompt-text
assert_args 'option separator preservation' \
  --sandbox danger-full-access \
  -c "$ceiling_arg" \
  -c "projects={\"$default_project\"={trust_level=\"untrusted\"}}" \
  -- --approval-mode autonomous --sandbox-is-prompt-text

echo 'Codex launcher option separator and managed boundary: preserved'
