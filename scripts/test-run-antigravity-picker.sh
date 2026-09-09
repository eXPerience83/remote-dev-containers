#!/usr/bin/env bash
set -euo pipefail

source_file="${REMOTE_DEV_RUN_ANTIGRAVITY:-$(dirname "$0")/run-antigravity.sh}"
workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT

runner="$workdir/run-antigravity"
manager="$workdir/remote-dev-antigravity"
picker="$workdir/remote-dev-antigravity-picker"
secure_state="$workdir/secure-persistent-state"
runtime_lib="$workdir/remote-dev-runtime.sh"
binary="$workdir/agy"
workspace="$workdir/workspace"
project="$workspace/project"
tool_bin="$workdir/tool-bin"
real_stat="$(command -v stat)"
mkdir -p "$project" "$tool_bin"

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
  local before="" entered="" after=""
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

remote_dev_assert_project_git_boundary() {
  local root="$1"
  local project="$2"
  if [[ "$project" != "$root/project" || ! -d "$project" || -L "$project" ]]; then
    remote_dev_runtime_error "project path changed during launch: $project"
    return 2
  fi
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

cat >"$picker" <<'PICKER'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  snapshot)
    [[ "$#" == 3 && "$2" == --pane ]]
    : >"$REMOTE_DEV_TEST_PICKER_SNAPSHOT"
    if [[ "${REMOTE_DEV_TEST_PICKER_SWAP:-0}" == 1 ]]; then
      mv -- "$REMOTE_DEV_TEST_SWAP_PROJECT" "$REMOTE_DEV_TEST_ORIGINAL_PROJECT"
      mv -- "$REMOTE_DEV_TEST_REPLACEMENT_PROJECT" "$REMOTE_DEV_TEST_SWAP_PROJECT"
    fi
    if [[ "${REMOTE_DEV_TEST_PICKER_SNAPSHOT_FAIL:-0}" == 1 ]]; then
      exit 1
    fi
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
chmod 0755 "$manager" "$binary" "$picker" "$secure_state" "$tool_bin/stat"

python3 - "$source_file" "$runner" "$manager" "$picker" "$secure_state" "$runtime_lib" <<'PY'
from pathlib import Path
import shlex
import sys

source, destination, manager, picker, secure_state, runtime_lib = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
replacements = {
    "readonly manager=/usr/local/bin/remote-dev-antigravity":
        f"readonly manager={shlex.quote(str(manager))}",
    "readonly picker_helper=/usr/local/bin/remote-dev-antigravity-picker":
        f"readonly picker_helper={shlex.quote(str(picker))}",
    "readonly secure_state=/usr/local/bin/secure-persistent-state":
        f"readonly secure_state={shlex.quote(str(secure_state))}",
    "readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh":
        f"readonly runtime_lib={shlex.quote(str(runtime_lib))}",
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
export REMOTE_DEV_TEST_PICKER_ARGS="$workdir/picker-args"
export REMOTE_DEV_TEST_PICKER_SNAPSHOT="$workdir/picker-snapshot"
export REMOTE_DEV_TEST_HARDENING="$workdir/hardening"
export REMOTE_DEV_TEST_EXPECT_PICKER=1
export REMOTE_DEV_TEST_REAL_STAT="$real_stat"

"$runner" --remote-dev-open-resume-picker 'literal space' ';not evaluated'
[[ "$(<"$REMOTE_DEV_TEST_VENDOR_CWD")" == "$project" ]]
[[ "$(<"$REMOTE_DEV_TEST_VENDOR_CEILING")" == "$workspace" ]]
mapfile -t vendor_args <"$REMOTE_DEV_TEST_VENDOR_ARGS"
[[ "${vendor_args[*]}" == 'literal space ;not evaluated' ]]
mapfile -t picker_args <"$REMOTE_DEV_TEST_PICKER_ARGS"
[[ "${picker_args[0]}" == watch ]]
[[ "${picker_args[1]}" == --pane ]]
[[ "${picker_args[2]}" == %4 ]]
[[ "${picker_args[3]}" == --pid ]]
[[ "${picker_args[4]}" =~ ^[0-9]+$ ]]
[[ "${picker_args[5]}" == --baseline-sha256 ]]
[[ "${picker_args[6]}" == "$(printf '%064d' 0)" ]]
[[ "$(wc -l <"$REMOTE_DEV_TEST_HARDENING")" == 1 ]]
[[ "$(<"$REMOTE_DEV_TEST_HARDENING")" == 'cwd=/' ]]

rm -f "$REMOTE_DEV_TEST_PICKER_ARGS" "$REMOTE_DEV_TEST_VENDOR_ARGS" "$REMOTE_DEV_TEST_VENDOR_CWD"
unset REMOTE_DEV_TEST_EXPECT_PICKER
"$runner" normal
[[ ! -e "$REMOTE_DEV_TEST_PICKER_ARGS" ]]
[[ "$(<"$REMOTE_DEV_TEST_VENDOR_ARGS")" == normal ]]
[[ "$(<"$REMOTE_DEV_TEST_VENDOR_CWD")" == "$project" ]]
[[ "$(<"$REMOTE_DEV_TEST_VENDOR_CEILING")" == "$workspace" ]]
[[ "$(wc -l <"$REMOTE_DEV_TEST_HARDENING")" == 2 ]]

# Replace the selected project with an outside-workspace symlink after the
# resolver returns it but before the common project-entry helper accepts it.
rm -f "$REMOTE_DEV_TEST_PICKER_ARGS" "$REMOTE_DEV_TEST_PICKER_SNAPSHOT" \
  "$REMOTE_DEV_TEST_VENDOR_ARGS" "$REMOTE_DEV_TEST_VENDOR_CWD"
outside_project="$workdir/outside-project"
mkdir -p "$outside_project"
export REMOTE_DEV_TEST_SWAP_TARGET="$outside_project"
status=0
"$runner" --remote-dev-open-resume-picker normal >"$workdir/project-swap-output" 2>&1 || status=$?
unset REMOTE_DEV_TEST_SWAP_TARGET
[[ "$status" == 2 ]]
grep -Fq "ERROR: project path changed during launch: $project" "$workdir/project-swap-output"
[[ ! -e "$REMOTE_DEV_TEST_PICKER_ARGS" ]]
[[ ! -e "$REMOTE_DEV_TEST_VENDOR_ARGS" ]]
[[ -L "$project" ]]
rm -f -- "$project"
mkdir -p "$project"

# Replace the selected project with another ordinary directory between the
# common helper's inode checks. Path equality alone must not admit it.
rm -f "$REMOTE_DEV_TEST_PICKER_ARGS" "$REMOTE_DEV_TEST_PICKER_SNAPSHOT" \
  "$REMOTE_DEV_TEST_VENDOR_ARGS" "$REMOTE_DEV_TEST_VENDOR_CWD"
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
PATH="$tool_bin:$PATH" "$runner" --remote-dev-open-resume-picker normal >"$workdir/directory-swap-output" 2>&1 || status=$?
unset REMOTE_DEV_TEST_DIRECTORY_SWAP REMOTE_DEV_TEST_DIRECTORY_SWAP_MARKER \
  REMOTE_DEV_TEST_SWAP_PROJECT REMOTE_DEV_TEST_ORIGINAL_PROJECT \
  REMOTE_DEV_TEST_REPLACEMENT_PROJECT
[[ "$status" == 2 ]]
grep -Fq "ERROR: project path changed during launch: $project" "$workdir/directory-swap-output"
[[ -e "$directory_swap_marker" ]]
[[ ! -e "$REMOTE_DEV_TEST_PICKER_ARGS" ]]
[[ ! -e "$REMOTE_DEV_TEST_VENDOR_ARGS" ]]
rm -rf -- "$project"
mv -- "$original_project" "$project"

# The picker is a real prelaunch helper. If the selected pathname is replaced
# while that helper runs, the final boundary recheck must stop the vendor.
rm -f "$REMOTE_DEV_TEST_PICKER_ARGS" "$REMOTE_DEV_TEST_PICKER_SNAPSHOT" \
  "$REMOTE_DEV_TEST_VENDOR_ARGS" "$REMOTE_DEV_TEST_VENDOR_CWD"
picker_replacement="$workdir/picker-replacement"
picker_original="$workdir/picker-original"
mkdir -p "$picker_replacement"
export REMOTE_DEV_TEST_PICKER_SWAP=1
export REMOTE_DEV_TEST_SWAP_PROJECT="$project"
export REMOTE_DEV_TEST_ORIGINAL_PROJECT="$picker_original"
export REMOTE_DEV_TEST_REPLACEMENT_PROJECT="$picker_replacement"
status=0
"$runner" --remote-dev-open-resume-picker normal >"$workdir/picker-swap-output" 2>&1 || status=$?
unset REMOTE_DEV_TEST_PICKER_SWAP REMOTE_DEV_TEST_SWAP_PROJECT \
  REMOTE_DEV_TEST_ORIGINAL_PROJECT REMOTE_DEV_TEST_REPLACEMENT_PROJECT
[[ "$status" == 2 ]]
grep -Fq "ERROR: project path changed before Antigravity vendor launch: $project" "$workdir/picker-swap-output"
[[ ! -e "$REMOTE_DEV_TEST_VENDOR_ARGS" ]]
tail -n 1 "$REMOTE_DEV_TEST_HARDENING" | grep -Fx 'cwd=/'
rm -rf -- "$project"
mv -- "$picker_original" "$project"

status=0
TMUX_PANE=invalid "$runner" --remote-dev-open-resume-picker >/dev/null 2>&1 || status=$?
[[ "$status" == 2 ]]

rm -f "$REMOTE_DEV_TEST_PICKER_ARGS" "$REMOTE_DEV_TEST_PICKER_SNAPSHOT" \
  "$REMOTE_DEV_TEST_VENDOR_ARGS" "$REMOTE_DEV_TEST_VENDOR_CWD"
export REMOTE_DEV_TEST_PICKER_SNAPSHOT_FAIL=1
status=0
"$runner" --remote-dev-open-resume-picker >/dev/null 2>&1 || status=$?
unset REMOTE_DEV_TEST_PICKER_SNAPSHOT_FAIL
[[ "$status" == 1 ]]
[[ -e "$REMOTE_DEV_TEST_PICKER_SNAPSHOT" ]]
[[ ! -e "$REMOTE_DEV_TEST_VENDOR_ARGS" ]]
tail -n 1 "$REMOTE_DEV_TEST_HARDENING" | grep -Fx 'cwd=/'

echo 'Project-scoped Antigravity picker and common Git boundary: OK'
