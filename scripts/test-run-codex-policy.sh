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
cwd_identity_file="$workdir/cwd-identity"
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
stat -Lc '%d:%i' -- . >"$REMOTE_DEV_CODEX_CWD_IDENTITY_FILE"
FAKE_CODEX
chmod 0755 "$test_bundled_codex"

cat >"$test_runtime_codex" <<'FAKE_CODEX'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' runtime >"$REMOTE_DEV_CODEX_IDENTITY_FILE"
printf '%s\n' "$@" >"$REMOTE_DEV_CODEX_ARGS_FILE"
printf '%s\n' "${GIT_CEILING_DIRECTORIES:-}" >"$REMOTE_DEV_CODEX_ENV_FILE"
stat -Lc '%d:%i' -- . >"$REMOTE_DEV_CODEX_CWD_IDENTITY_FILE"
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

case "${REMOTE_DEV_TEST_POST_VALIDATOR_SWAP:-none}" in
  none) ;;
  replace)
    mv -- "$REMOTE_DEV_TEST_SWAP_PROJECT" "$REMOTE_DEV_TEST_SWAP_ORIGINAL"
    mv -- "$REMOTE_DEV_TEST_SWAP_REPLACEMENT" "$REMOTE_DEV_TEST_SWAP_PROJECT"
    ;;
  symlink)
    mv -- "$REMOTE_DEV_TEST_SWAP_PROJECT" "$REMOTE_DEV_TEST_SWAP_ORIGINAL"
    ln -s -- "$REMOTE_DEV_TEST_SWAP_ORIGINAL" "$REMOTE_DEV_TEST_SWAP_PROJECT"
    ;;
  *) exit 96 ;;
esac
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

  rm -f "$args_file" "$identity_file" "$env_file" "$cwd_identity_file" "$validator_file"
  common_env=(
    WORKSPACE="$root"
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file"
    REMOTE_DEV_CODEX_IDENTITY_FILE="$identity_file"
    REMOTE_DEV_CODEX_ENV_FILE="$env_file"
    REMOTE_DEV_CODEX_CWD_IDENTITY_FILE="$cwd_identity_file"
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

# Remote Dev's default remains the explicit equivalent of upstream Codex
# --yolo: danger-full-access plus approval=never. The Git ceiling and managed
# --cd are project-selection invariants, not an inner sandbox.
autonomous_expected=(--sandbox danger-full-access -c "$ceiling_arg" --cd "$default_project" --ask-for-approval never)
run_launcher __unset__ resume --last
assert_args 'default autonomous mode' "${autonomous_expected[@]}" resume --last
assert_identity runtime 'default autonomous mode'
assert_validator "$default_project"
[[ "$(<"$env_file")" == "$workspace" ]] || { echo 'ERROR: Codex process missed Git ceiling' >&2; exit 1; }
[[ "$(<"$cwd_identity_file")" == "$(stat -Lc '%d:%i' -- "$default_project")" ]] \
  || { echo 'ERROR: default Codex launch inherited the wrong project inode' >&2; exit 1; }

# If the caller's cwd is renamed before run-codex starts, its physical renamed
# direct child is the current project. Do not silently jump to a newly-created
# replacement at the old pathname; keep validation and inherited cwd on the same
# inode/path instead.
stale_workspace="$workdir/stale-workspace"
stale_project="$stale_workspace/project"
stale_original="$stale_workspace/project-old"
stale_replacement="$workdir/stale-replacement"
mkdir -p "$stale_project" "$stale_replacement"
stale_original_identity="$(stat -Lc '%d:%i' -- "$stale_project")"
rm -f "$args_file" "$identity_file" "$env_file" "$cwd_identity_file" "$validator_file"
(
  cd "$stale_project"
  mv -- "$stale_project" "$stale_original"
  mv -- "$stale_replacement" "$stale_project"
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE \
    WORKSPACE="$stale_workspace" \
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
    REMOTE_DEV_CODEX_IDENTITY_FILE="$identity_file" \
    REMOTE_DEV_CODEX_ENV_FILE="$env_file" \
    REMOTE_DEV_CODEX_CWD_IDENTITY_FILE="$cwd_identity_file" \
    REMOTE_DEV_CODEX_VALIDATOR_FILE="$validator_file" \
    REMOTE_DEV_TEST_RUNTIME_CODEX="$test_runtime_codex" \
    "$test_launcher" resume --last
)
stale_replacement_identity="$(stat -Lc '%d:%i' -- "$stale_project")"
[[ "$stale_replacement_identity" != "$stale_original_identity" ]] \
  || { echo 'ERROR: stale-cwd fixture did not replace the old project pathname' >&2; exit 1; }
[[ "$(<"$cwd_identity_file")" == "$stale_original_identity" ]] \
  || { echo 'ERROR: Codex did not preserve the physical current project inode' >&2; exit 1; }
[[ "$(<"$env_file")" == "$stale_workspace" ]] \
  || { echo 'ERROR: stale-cwd launch missed its Git ceiling' >&2; exit 1; }
grep -Fxq -- "$stale_original" "$validator_file"
grep -Fxq -- "ceiling=$stale_workspace" "$validator_file"
grep -Fxq -- "$stale_original" "$args_file"

echo 'Codex pre-launch cwd rename: physical current project preserved and pinned for resume'

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

# Explicit project selectors are rewritten to the same canonical direct-child
# pathname that the preflight validated. This closes alias-retarget races and
# keeps validation/execution semantics identical without changing the selected
# project or Codex's full-access default.
project_a_alias="$workdir/project-a-alias"
ln -s -- "$project_a" "$project_a_alias"
run_launcher guarded --cd "$project_a_alias" resume --last
assert_args 'symlink alias canonicalization' \
  --sandbox danger-full-access \
  -c "$ceiling_arg" \
  -c "projects={\"$project_a\"={trust_level=\"untrusted\"}}" \
  --cd "$project_a" resume --last
assert_validator "$project_a"

run_launcher guarded --cd=../project-a resume --last
assert_args 'relative inline project canonicalization' \
  --sandbox danger-full-access \
  -c "$ceiling_arg" \
  -c "projects={\"$project_a\"={trust_level=\"untrusted\"}}" \
  --cd="$project_a" resume --last
assert_validator "$project_a"

# A plain relative selector is eligible for Bash CDPATH lookup. The wrapper
# must resolve it relative to the caller's cwd, not a matching external CDPATH
# entry, and must not capture cd's informational stdout into active_project.
cdpath_decoy="$workdir/cdpath-decoy"
mkdir -p "$cdpath_decoy/project-a"
CDPATH="$cdpath_decoy" \
  run_launcher_at "$workspace" "$workspace" guarded --cd project-a resume --last
assert_args 'relative project ignores inherited CDPATH' \
  --sandbox danger-full-access \
  -c "$ceiling_arg" \
  -c "projects={\"$project_a\"={trust_level=\"untrusted\"}}" \
  --cd "$project_a" resume --last
assert_validator "$project_a"

echo 'Codex explicit project selectors: canonicalized before vendor execution'

# Swap the selected pathname only after run-codex has captured its identity and
# the effective-policy validator has run. This is the actual TOCTOU boundary:
# the vendor must not execute when validation and inherited cwd/path diverge.
swap_workspace="$workdir/post-validator-workspace"
swap_project="$swap_workspace/project"
swap_original="$swap_workspace/project-old"
swap_replacement="$workdir/post-validator-replacement"
mkdir -p "$swap_project" "$swap_replacement"
printf 'original\n' >"$swap_project/canary"
printf 'replacement\n' >"$swap_replacement/canary"
rm -f "$args_file" "$identity_file" "$env_file" "$cwd_identity_file" "$validator_file"
status=0
(
  cd "$swap_project"
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE \
    WORKSPACE="$swap_workspace" \
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
    REMOTE_DEV_CODEX_IDENTITY_FILE="$identity_file" \
    REMOTE_DEV_CODEX_ENV_FILE="$env_file" \
    REMOTE_DEV_CODEX_CWD_IDENTITY_FILE="$cwd_identity_file" \
    REMOTE_DEV_CODEX_VALIDATOR_FILE="$validator_file" \
    REMOTE_DEV_TEST_RUNTIME_CODEX="$test_runtime_codex" \
    REMOTE_DEV_TEST_POST_VALIDATOR_SWAP=replace \
    REMOTE_DEV_TEST_SWAP_PROJECT="$swap_project" \
    REMOTE_DEV_TEST_SWAP_ORIGINAL="$swap_original" \
    REMOTE_DEV_TEST_SWAP_REPLACEMENT="$swap_replacement" \
    "$test_launcher" resume --last
) >/dev/null 2>"$workdir/post-validator-swap-error" || status=$?
(( status == 2 )) || { echo "ERROR: post-validator project swap returned $status, expected 2" >&2; cat "$workdir/post-validator-swap-error" >&2; exit 1; }
[[ -e "$validator_file" && ! -e "$args_file" ]] || { echo 'ERROR: post-validator project swap reached Codex' >&2; exit 1; }
[[ "$(<"$swap_original/canary")" == original && "$(<"$swap_project/canary")" == replacement ]] \
  || { echo 'ERROR: post-validator replacement fixture was modified unexpectedly' >&2; exit 1; }

grep -Fq 'project path changed during Codex configuration validation' "$workdir/post-validator-swap-error"

echo 'Codex post-validator project replacement: blocked before vendor exec'

# A symlink to the original inode defeats stat -L identity checks by itself.
# The full direct-child/Git-boundary assertion must still reject that swap.
symlink_workspace="$workdir/post-validator-symlink-workspace"
symlink_project="$symlink_workspace/project"
symlink_original="$symlink_workspace/project-old"
mkdir -p "$symlink_project"
printf 'original\n' >"$symlink_project/canary"
rm -f "$args_file" "$identity_file" "$env_file" "$cwd_identity_file" "$validator_file"
status=0
(
  cd "$symlink_project"
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE \
    WORKSPACE="$symlink_workspace" \
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
    REMOTE_DEV_CODEX_IDENTITY_FILE="$identity_file" \
    REMOTE_DEV_CODEX_ENV_FILE="$env_file" \
    REMOTE_DEV_CODEX_CWD_IDENTITY_FILE="$cwd_identity_file" \
    REMOTE_DEV_CODEX_VALIDATOR_FILE="$validator_file" \
    REMOTE_DEV_TEST_RUNTIME_CODEX="$test_runtime_codex" \
    REMOTE_DEV_TEST_POST_VALIDATOR_SWAP=symlink \
    REMOTE_DEV_TEST_SWAP_PROJECT="$symlink_project" \
    REMOTE_DEV_TEST_SWAP_ORIGINAL="$symlink_original" \
    "$test_launcher" resume --last
) >/dev/null 2>"$workdir/post-validator-symlink-error" || status=$?
(( status == 2 )) || { echo "ERROR: post-validator project symlink returned $status, expected 2" >&2; cat "$workdir/post-validator-symlink-error" >&2; exit 1; }
[[ -L "$symlink_project" && -e "$validator_file" && ! -e "$args_file" ]] \
  || { echo 'ERROR: post-validator symlink swap reached Codex or fixture is invalid' >&2; exit 1; }
grep -Fq 'project must not be a symlink' "$workdir/post-validator-symlink-error"

echo 'Codex post-validator symlink-to-original swap: blocked before vendor exec'

# Resolver failure still uses immutable bundled fallback and validates that
# exact executable before launch.
rm -f "$args_file" "$identity_file" "$env_file" "$cwd_identity_file" "$validator_file"
(
  cd "$default_project"
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE \
    WORKSPACE="$workspace" \
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
    REMOTE_DEV_CODEX_IDENTITY_FILE="$identity_file" \
    REMOTE_DEV_CODEX_ENV_FILE="$env_file" \
    REMOTE_DEV_CODEX_CWD_IDENTITY_FILE="$cwd_identity_file" \
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
  rm -f "$args_file" "$identity_file" "$env_file" "$cwd_identity_file" "$validator_file" "$error_file"
  run_launcher __unset__ "$@" >/dev/null 2>"$error_file" || status=$?
  (( status == 2 )) || { echo "ERROR: $label returned $status, expected 2" >&2; cat "$error_file" >&2; exit 1; }
  [[ ! -e "$args_file" ]] || { echo "ERROR: $label invoked Codex" >&2; exit 1; }
  grep -Fq 'refusing argument:' "$error_file" || { echo "ERROR: $label lacked refusal diagnostic" >&2; cat "$error_file" >&2; exit 1; }
}

assert_rejected 'sandbox override' --sandbox read-only
assert_rejected 'short sandbox override' -s read-only
assert_rejected 'joined short sandbox override' -sread-only
assert_rejected 'approval override' --ask-for-approval never
assert_rejected 'short approval override' -a never
assert_rejected 'joined short approval override' -anever
assert_rejected 'automatic-review override' --approve-for-me
assert_rejected 'not-so-yolo alias' --not-so-yolo
assert_rejected 'dangerous bypass' --dangerously-bypass-approvals-and-sandbox
assert_rejected 'legacy dangerous auto approve' --dangerously-auto-approve-everything
assert_rejected 'yolo alias' --yolo
assert_rejected 'full-auto alias' --full-auto
assert_rejected 'profile selection' --profile test
assert_rejected 'short profile selection' -p test
assert_rejected 'config profile selector' -c 'profile="test"'
assert_rejected 'project trust override' -c 'projects={"/workspace"={trust_level="trusted"}}'
assert_rejected 'sandbox config override' -c 'sandbox_mode="read-only"'
assert_rejected 'approval config override' --config 'approval_policy="never"'
assert_rejected 'spaced config override' -c ' sandbox_mode = "read-only" '
assert_rejected 'inline config override' -c=sandbox_mode=read-only
assert_rejected 'profile sandbox config override' -c 'profiles.test.sandbox_mode="read-only"'
assert_rejected 'profile project config override' -c 'profiles.test.projects.foo.trust_level="trusted"'
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
assert_invalid_mode 'empty inline explicit mode' '--approval-mode requires autonomous or guarded' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --approval-mode=
assert_invalid_mode 'duplicate explicit mode' '--approval-mode may be specified only once' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --approval-mode autonomous --approval-mode guarded
assert_invalid_mode 'print policy with Codex arguments' '--print-policy cannot be combined with Codex arguments' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --print-policy resume
assert_invalid_mode 'missing config value' '--config requires a value' \
  env -u REMOTE_DEV_CODEX_APPROVAL_MODE "$test_launcher" --config

# Duplicate project selectors are ambiguous at the wrapper boundary and must be
# rejected before Codex can choose a different effective cwd than the one that
# Remote Dev validated.
rm -f "$args_file" "$identity_file" "$env_file" "$cwd_identity_file" "$validator_file"
status=0
run_launcher __unset__ --cd "$project_a" -C "$project_b" >/dev/null 2>"$workdir/duplicate-cd-error" || status=$?
(( status == 2 )) || { echo "ERROR: duplicate --cd/-C returned $status, expected 2" >&2; cat "$workdir/duplicate-cd-error" >&2; exit 1; }
[[ ! -e "$args_file" ]] || { echo 'ERROR: duplicate --cd/-C invoked Codex' >&2; exit 1; }
grep -Fq -- '--cd/-C may be specified only once' "$workdir/duplicate-cd-error"

echo 'Invalid Codex launch-owned policy/project selector input: rejected without execution'

# Empty explicit project selectors are usage errors rather than a request to
# silently fall back to the inherited cwd.
rm -f "$args_file" "$identity_file" "$env_file" "$cwd_identity_file" "$validator_file"
status=0
run_launcher __unset__ --cd= >/dev/null 2>"$workdir/empty-cd-error" || status=$?
(( status == 2 )) || { echo "ERROR: empty --cd returned $status, expected 2" >&2; cat "$workdir/empty-cd-error" >&2; exit 1; }
[[ ! -e "$args_file" ]] || { echo 'ERROR: empty --cd invoked Codex' >&2; exit 1; }
grep -Fq -- '--cd requires a project directory' "$workdir/empty-cd-error"

# If the effective-policy validator fails, the resolved Codex binary is never
# launched even though the collection itself is healthy.
rm -f "$args_file" "$identity_file" "$env_file" "$cwd_identity_file" "$validator_file"
status=0
(
  cd "$default_project"
  env WORKSPACE="$workspace" \
    REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
    REMOTE_DEV_CODEX_IDENTITY_FILE="$identity_file" \
    REMOTE_DEV_CODEX_ENV_FILE="$env_file" \
    REMOTE_DEV_CODEX_CWD_IDENTITY_FILE="$cwd_identity_file" \
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
rm -f "$args_file" "$identity_file" "$env_file" "$cwd_identity_file" "$validator_file"
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
  --cd "$default_project" \
  -c "projects={\"$default_project\"={trust_level=\"untrusted\"}}" \
  -- --approval-mode autonomous --sandbox-is-prompt-text

echo 'Codex launcher option separator and managed boundary: preserved'
