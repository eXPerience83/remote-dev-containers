#!/usr/bin/env bash
set -euo pipefail

source_file="${REMOTE_DEV_RUN_ANTIGRAVITY:-$(dirname "$0")/run-antigravity.sh}"
workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT

runner="$workdir/run-antigravity"
manager="$workdir/remote-dev-antigravity"
picker="$workdir/remote-dev-antigravity-picker"
validator="$workdir/validate-antigravity-project-boundary"
settings="$workdir/settings.json"
secure_state="$workdir/secure-persistent-state"
runtime_lib="$workdir/remote-dev-runtime.sh"
binary="$workdir/agy"
workspace="$workdir/workspace"
project="$workspace/project"
tool_bin="$workdir/tool-bin"
real_stat="$(command -v stat)"
mkdir -p "$project" "$tool_bin"
printf '{}\n' >"$settings"
chmod 0600 "$settings"

cat >"$runtime_lib" <<'RUNTIME'
remote_dev_resolve_role() {
  printf '%s\n' antigravity
}

remote_dev_runtime_error() {
  printf 'ERROR: %s\n' "$*" >&2
}

remote_dev_workspace_root() {
  [[ -d "${WORKSPACE:-}" && ! -L "${WORKSPACE:-}" ]] || return 2
  printf '%s\n' "$WORKSPACE"
}

remote_dev_resolve_project() {
  local root="$1"
  local project="$root/project"
  [[ "${REMOTE_DEV_PROJECT:-}" == project ]] || return 2
  [[ -d "$project" && ! -L "$project" ]] || return 2
  if [[ -n "${REMOTE_DEV_TEST_SWAP_TARGET:-}" ]]; then
    rm -rf -- "$project"
    ln -s -- "$REMOTE_DEV_TEST_SWAP_TARGET" "$project"
  fi
  printf '%s\n' "$project"
}

remote_dev_enter_project() {
  local root="$1"
  local project="$2"
  local before entered after
  [[ "$project" == "$root/project" && -d "$project" && ! -L "$project" ]] || {
    remote_dev_runtime_error "project path changed during launch: $project"
    return 2
  }
  before="$(stat -Lc '%d:%i' -- "$project" 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed during launch: $project"
    return 2
  }
  if ! cd -P -- "$project" || [[ "$PWD" != "$project" ]]; then
    remote_dev_runtime_error "project path changed during launch: $project"
    return 2
  fi
  entered="$(stat -Lc '%d:%i' -- . 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed during launch: $project"
    builtin cd -P -- / || true
    return 2
  }
  after="$(stat -Lc '%d:%i' -- "$project" 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed during launch: $project"
    builtin cd -P -- / || true
    return 2
  }
  if [[ "$before" != "$entered" || "$before" != "$after" ]]; then
    remote_dev_runtime_error "project path changed during launch: $project"
    builtin cd -P -- / || true
    return 2
  fi
  export GIT_CEILING_DIRECTORIES="$root"
}

remote_dev_recover_safe_cwd() {
  builtin cd -P -- /
}
RUNTIME

cat >"$manager" <<MANAGER
#!/usr/bin/env bash
set -euo pipefail
case "\${1:-}" in
  path) printf '%s\\n' '$binary' ;;
  verify) printf '%s\\n' 'Antigravity runtime full integrity: OK (1.1.27)' ;;
  *) exit 2 ;;
esac
MANAGER

cat >"$binary" <<'BINARY'
#!/usr/bin/env bash
set -euo pipefail
pwd >"$REMOTE_DEV_TEST_VENDOR_CWD"
printf '%s\n' "${GIT_CEILING_DIRECTORIES:-}" >"$REMOTE_DEV_TEST_VENDOR_CEILING"
: >"$REMOTE_DEV_TEST_VENDOR_ARGS"
for argument in "$@"; do
  printf '%s\n' "$argument" >>"$REMOTE_DEV_TEST_VENDOR_ARGS"
done
if [[ "${REMOTE_DEV_TEST_EXPECT_PICKER:-0}" == 1 ]]; then
  for _ in {1..100}; do
    [[ -e "$REMOTE_DEV_TEST_PICKER_ARGS" ]] && break
    sleep 0.01
  done
fi
BINARY

cat >"$validator" <<'VALIDATOR'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" >"$REMOTE_DEV_TEST_VALIDATOR_ARGS"
[[ "${REMOTE_DEV_TEST_VALIDATOR_FAIL:-0}" != 1 ]] || exit 2
VALIDATOR

cat >"$picker" <<'PICKER'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  snapshot)
    [[ "$#" == 3 && "$2" == --pane ]]
    : >"$REMOTE_DEV_TEST_PICKER_SNAPSHOT"
    [[ "${REMOTE_DEV_TEST_PICKER_SNAPSHOT_FAIL:-0}" != 1 ]] || exit 1
    printf '%064d\n' 0
    ;;
  watch)
    printf '%s\n' "$@" >"$REMOTE_DEV_TEST_PICKER_ARGS"
    ;;
  *) exit 2 ;;
esac
PICKER

cat >"$secure_state" <<'SECURE'
#!/usr/bin/env bash
set -euo pipefail
printf 'cwd=%s\n' "$PWD" >>"$REMOTE_DEV_TEST_HARDENING"
SECURE

cat >"$tool_bin/stat" <<'STAT'
#!/usr/bin/env bash
set -euo pipefail
output="$("$REMOTE_DEV_TEST_REAL_STAT" "$@")"
printf '%s\n' "$output"
if [[ "${REMOTE_DEV_TEST_DIRECTORY_SWAP:-0}" == 1 && ! -e "$REMOTE_DEV_TEST_DIRECTORY_SWAP_MARKER" ]]; then
  : >"$REMOTE_DEV_TEST_DIRECTORY_SWAP_MARKER"
  mv -- "$REMOTE_DEV_TEST_SWAP_PROJECT" "$REMOTE_DEV_TEST_ORIGINAL_PROJECT"
  mv -- "$REMOTE_DEV_TEST_REPLACEMENT_PROJECT" "$REMOTE_DEV_TEST_SWAP_PROJECT"
fi
STAT
chmod 0755 "$manager" "$binary" "$validator" "$picker" "$secure_state" "$tool_bin/stat"

python3 - "$source_file" "$runner" "$manager" "$picker" "$validator" "$settings" "$secure_state" "$runtime_lib" <<'PY'
from pathlib import Path
import shlex
import sys

source, destination, manager, picker, validator, settings, secure_state, runtime_lib = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
replacements = {
    "readonly manager=/usr/local/bin/remote-dev-antigravity": f"readonly manager={shlex.quote(str(manager))}",
    "readonly picker_helper=/usr/local/bin/remote-dev-antigravity-picker": f"readonly picker_helper={shlex.quote(str(picker))}",
    "readonly project_boundary_validator=/usr/local/bin/validate-antigravity-project-boundary": f"readonly project_boundary_validator={shlex.quote(str(validator))}",
    "readonly antigravity_settings=/root/.gemini/antigravity-cli/settings.json": f"readonly antigravity_settings={shlex.quote(str(settings))}",
    "readonly secure_state=/usr/local/bin/secure-persistent-state": f"readonly secure_state={shlex.quote(str(secure_state))}",
    "readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh": f"readonly runtime_lib={shlex.quote(str(runtime_lib))}",
}
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$runner"

export REMOTE_DEV_ROLE=antigravity
export REMOTE_DEV_ANTIGRAVITY_OAUTH_HELPER=0
export REMOTE_DEV_PROJECT=project
export WORKSPACE="$workspace"
export TMUX_PANE=%4
export REMOTE_DEV_TEST_VENDOR_ARGS="$workdir/vendor-args"
export REMOTE_DEV_TEST_VENDOR_CWD="$workdir/vendor-cwd"
export REMOTE_DEV_TEST_VENDOR_CEILING="$workdir/vendor-ceiling"
export REMOTE_DEV_TEST_VALIDATOR_ARGS="$workdir/validator-args"
export REMOTE_DEV_TEST_PICKER_ARGS="$workdir/picker-args"
export REMOTE_DEV_TEST_PICKER_SNAPSHOT="$workdir/picker-snapshot"
export REMOTE_DEV_TEST_HARDENING="$workdir/hardening"
export REMOTE_DEV_TEST_EXPECT_PICKER=1
export REMOTE_DEV_TEST_REAL_STAT="$real_stat"

"$runner" --remote-dev-open-resume-picker 'literal space' ';not evaluated'
[[ "$(<"$REMOTE_DEV_TEST_VENDOR_CWD")" == "$project" ]]
[[ "$(<"$REMOTE_DEV_TEST_VENDOR_CEILING")" == "$workspace" ]]
mapfile -t vendor_args <"$REMOTE_DEV_TEST_VENDOR_ARGS"
[[ "${vendor_args[*]}" == '--sandbox literal space ;not evaluated' ]]
mapfile -t validator_args <"$REMOTE_DEV_TEST_VALIDATOR_ARGS"
[[ "${validator_args[*]}" == "--settings $settings --project $project" ]]
mapfile -t picker_args <"$REMOTE_DEV_TEST_PICKER_ARGS"
[[ "${picker_args[0]}" == watch && "${picker_args[1]}" == --pane && "${picker_args[2]}" == %4 ]]
[[ "${picker_args[3]}" == --pid && "${picker_args[4]}" =~ ^[0-9]+$ ]]
[[ "${picker_args[5]}" == --baseline-sha256 && "${picker_args[6]}" == "$(printf '%064d' 0)" ]]
[[ "$(wc -l <"$REMOTE_DEV_TEST_HARDENING")" == 1 ]]
[[ "$(<"$REMOTE_DEV_TEST_HARDENING")" == 'cwd=/' ]]

rm -f "$REMOTE_DEV_TEST_PICKER_ARGS" "$REMOTE_DEV_TEST_VENDOR_ARGS" "$REMOTE_DEV_TEST_VENDOR_CWD"
unset REMOTE_DEV_TEST_EXPECT_PICKER
"$runner" normal
[[ ! -e "$REMOTE_DEV_TEST_PICKER_ARGS" ]]
mapfile -t vendor_args <"$REMOTE_DEV_TEST_VENDOR_ARGS"
[[ "${vendor_args[*]}" == '--sandbox normal' ]]
[[ "$(<"$REMOTE_DEV_TEST_VENDOR_CWD")" == "$project" ]]
[[ "$(wc -l <"$REMOTE_DEV_TEST_HARDENING")" == 2 ]]

# Managed sessions own the sandbox/bypass flags; caller overrides never reach
# the validator or vendor executable.
for unsafe in --sandbox --no-sandbox --dangerously-skip-permissions; do
  rm -f "$REMOTE_DEV_TEST_VALIDATOR_ARGS" "$REMOTE_DEV_TEST_VENDOR_ARGS"
  status=0
  "$runner" "$unsafe" >/dev/null 2>"$workdir/unsafe-error" || status=$?
  [[ "$status" == 2 ]]
  grep -Fq 'owns Antigravity sandbox and permission-bypass policy' "$workdir/unsafe-error"
  [[ ! -e "$REMOTE_DEV_TEST_VALIDATOR_ARGS" && ! -e "$REMOTE_DEV_TEST_VENDOR_ARGS" ]]
done

# An incompatible persistent safety policy fails closed before vendor startup.
rm -f "$REMOTE_DEV_TEST_VALIDATOR_ARGS" "$REMOTE_DEV_TEST_VENDOR_ARGS"
export REMOTE_DEV_TEST_VALIDATOR_FAIL=1
status=0
"$runner" normal >/dev/null 2>"$workdir/validator-error" || status=$?
unset REMOTE_DEV_TEST_VALIDATOR_FAIL
[[ "$status" == 2 ]]
[[ -e "$REMOTE_DEV_TEST_VALIDATOR_ARGS" && ! -e "$REMOTE_DEV_TEST_VENDOR_ARGS" ]]
grep -Fq 'settings do not satisfy the managed project-confinement contract' "$workdir/validator-error"

# Replace the validated project with an outside-workspace symlink inside the
# resolver fixture. The vendor process and settings validator must not start.
rm -f "$REMOTE_DEV_TEST_PICKER_ARGS" "$REMOTE_DEV_TEST_PICKER_SNAPSHOT" \
  "$REMOTE_DEV_TEST_VENDOR_ARGS" "$REMOTE_DEV_TEST_VENDOR_CWD" "$REMOTE_DEV_TEST_VALIDATOR_ARGS"
outside_project="$workdir/outside-project"
mkdir -p "$outside_project"
export REMOTE_DEV_TEST_SWAP_TARGET="$outside_project"
status=0
"$runner" --remote-dev-open-resume-picker normal >"$workdir/project-swap-output" 2>&1 || status=$?
unset REMOTE_DEV_TEST_SWAP_TARGET
[[ "$status" == 2 ]]
grep -Fq "ERROR: project path changed during launch: $project" "$workdir/project-swap-output"
[[ ! -e "$REMOTE_DEV_TEST_VALIDATOR_ARGS" && ! -e "$REMOTE_DEV_TEST_VENDOR_ARGS" ]]
[[ -L "$project" ]]
rm -f -- "$project"
mkdir -p "$project"

# Replace the selected directory between identity checks. Path-string equality
# alone must not admit the replacement.
rm -f "$REMOTE_DEV_TEST_VENDOR_ARGS" "$REMOTE_DEV_TEST_VALIDATOR_ARGS"
replacement_project="$workdir/replacement-project"
original_project="$workdir/original-project"
directory_swap_marker="$workdir/directory-swap-marker"
mkdir -p "$replacement_project"
export REMOTE_DEV_TEST_DIRECTORY_SWAP=1
export REMOTE_DEV_TEST_DIRECTORY_SWAP_MARKER="$directory_swap_marker"
export REMOTE_DEV_TEST_SWAP_PROJECT="$project"
export REMOTE_DEV_TEST_ORIGINAL_PROJECT="$original_project"
export REMOTE_DEV_TEST_REPLACEMENT_PROJECT="$replacement_project"
status=0
PATH="$tool_bin:$PATH" "$runner" normal >"$workdir/directory-swap-output" 2>&1 || status=$?
unset REMOTE_DEV_TEST_DIRECTORY_SWAP REMOTE_DEV_TEST_DIRECTORY_SWAP_MARKER \
  REMOTE_DEV_TEST_SWAP_PROJECT REMOTE_DEV_TEST_ORIGINAL_PROJECT REMOTE_DEV_TEST_REPLACEMENT_PROJECT
[[ "$status" == 2 ]]
grep -Fq "ERROR: project path changed during launch: $project" "$workdir/directory-swap-output"
[[ -e "$directory_swap_marker" && ! -e "$REMOTE_DEV_TEST_VALIDATOR_ARGS" && ! -e "$REMOTE_DEV_TEST_VENDOR_ARGS" ]]
rm -rf -- "$project"
mv -- "$original_project" "$project"

status=0
TMUX_PANE=invalid "$runner" --remote-dev-open-resume-picker >/dev/null 2>&1 || status=$?
[[ "$status" == 2 ]]

# Picker setup failure happens after the cleanup trap is installed. Hardening
# therefore still runs from the safe recovered cwd.
rm -f "$REMOTE_DEV_TEST_PICKER_ARGS" "$REMOTE_DEV_TEST_PICKER_SNAPSHOT" \
  "$REMOTE_DEV_TEST_VENDOR_ARGS" "$REMOTE_DEV_TEST_VENDOR_CWD"
export REMOTE_DEV_TEST_PICKER_SNAPSHOT_FAIL=1
status=0
"$runner" --remote-dev-open-resume-picker >/dev/null 2>&1 || status=$?
unset REMOTE_DEV_TEST_PICKER_SNAPSHOT_FAIL
[[ "$status" == 1 ]]
[[ -e "$REMOTE_DEV_TEST_PICKER_SNAPSHOT" && ! -e "$REMOTE_DEV_TEST_VENDOR_ARGS" ]]
tail -n 1 "$REMOTE_DEV_TEST_HARDENING" | grep -Fx 'cwd=/'

echo 'Project-scoped Antigravity sandbox/boundary launcher: OK'
