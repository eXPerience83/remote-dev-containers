#!/usr/bin/env bash
set -euo pipefail

source_file="${REMOTE_DEV_ATTACH_TMUX:-$(dirname "$0")/attach-remote-dev-tmux.sh}"
workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT

fixture="$workdir/attach-remote-dev-tmux"
runtime_lib="$workdir/remote-dev-runtime.sh"
run_codex="$workdir/run-codex"
run_direct_session="$workdir/run-direct-session"
bin_dir="$workdir/bin"
tmux_stub="$bin_dir/tmux"
workspace="$workdir/workspace"
project="$workspace/project"
mkdir -p "$project" "$bin_dir"

cat >"$runtime_lib" <<'RUNTIME'
remote_dev_resolve_role() {
  printf '%s\n' codex
}

remote_dev_resolve_start_mode() {
  [[ "$1" == codex ]] || return 2
  printf '%s\n' agent
}

remote_dev_default_tmux_session() {
  [[ "$1" == codex ]] || return 2
  printf '%s\n' direct-codex
}

remote_dev_resolve_project() {
  local root="$1"
  local name="${REMOTE_DEV_PROJECT:-}"
  [[ "$name" == project ]] || return 2
  [[ -d "$root/$name" && ! -L "$root/$name" ]] || return 2
  printf '%s/%s\n' "$root" "$name"
}
RUNTIME

cat >"$run_direct_session" <<'DIRECT'
#!/usr/bin/env bash
set -euo pipefail
: >"$REMOTE_DEV_TEST_DIRECT_SESSION_MARKER"
exec "$@"
DIRECT

cat >"$run_codex" <<'CODEX'
#!/usr/bin/env bash
set -euo pipefail
pwd >"$REMOTE_DEV_TEST_CODEX_CWD"
printf '%s\n' "$@" >"$REMOTE_DEV_TEST_CODEX_ARGS"
CODEX

cat >"$tmux_stub" <<'TMUX'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == -L ]]; then
  shift 2
fi

case "${1:-}" in
  new-session)
    command="${!#}"
    case "${REMOTE_DEV_TEST_SWAP_MODE:-none}" in
      none)
        ;;
      directory)
        mv -- "$REMOTE_DEV_TEST_PROJECT" "$REMOTE_DEV_TEST_ORIGINAL_PROJECT"
        mv -- "$REMOTE_DEV_TEST_REPLACEMENT_PROJECT" "$REMOTE_DEV_TEST_PROJECT"
        ;;
      symlink)
        mv -- "$REMOTE_DEV_TEST_PROJECT" "$REMOTE_DEV_TEST_ORIGINAL_PROJECT"
        ln -s -- "$REMOTE_DEV_TEST_SYMLINK_TARGET" "$REMOTE_DEV_TEST_PROJECT"
        ;;
      *)
        exit 2
        ;;
    esac

    status=0
    bash -c "$command" >"$REMOTE_DEV_TEST_SESSION_OUTPUT" 2>&1 || status=$?
    printf '%s\n' "$status" >"$REMOTE_DEV_TEST_SESSION_STATUS"
    ;;
  display-message)
    printf '%s\n' '@1'
    ;;
  rename-window|has-session)
    ;;
  attach-session)
    exit 2
    ;;
  *)
    exit 2
    ;;
esac
TMUX
chmod 0755 "$run_direct_session" "$run_codex" "$tmux_stub"

python3 - "$source_file" "$fixture" "$runtime_lib" "$run_codex" "$run_direct_session" <<'PY'
from pathlib import Path
import shlex
import sys

source, destination, runtime_lib, run_codex, run_direct_session = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
replacements = {
    "runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh":
        f"runtime_lib={shlex.quote(str(runtime_lib))}",
    "readonly run_codex_binary=/usr/local/bin/run-codex":
        f"readonly run_codex_binary={shlex.quote(str(run_codex))}",
}
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one fixture anchor: {old}")
    text = text.replace(old, new)

anchor = "/usr/local/bin/run-direct-session"
if text.count(anchor) != 2:
    raise SystemExit(f"expected exactly two direct-session anchors, got {text.count(anchor)}")
text = text.replace(anchor, shlex.quote(str(run_direct_session)))
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$fixture"

export REMOTE_DEV_PROJECT=project
export WORKSPACE="$workspace"
export REMOTE_DEV_TMUX_DETACHED=1
export TMUX_SOCKET_NAME=test-direct-codex
export TMUX_SESSION=direct-codex
export REMOTE_DEV_TEST_DIRECT_SESSION_MARKER="$workdir/direct-session-marker"
export REMOTE_DEV_TEST_CODEX_CWD="$workdir/codex-cwd"
export REMOTE_DEV_TEST_CODEX_ARGS="$workdir/codex-args"
export REMOTE_DEV_TEST_SESSION_STATUS="$workdir/session-status"
export REMOTE_DEV_TEST_SESSION_OUTPUT="$workdir/session-output"
export REMOTE_DEV_TEST_PROJECT="$project"

run_attach() {
  rm -f \
    "$REMOTE_DEV_TEST_DIRECT_SESSION_MARKER" \
    "$REMOTE_DEV_TEST_CODEX_CWD" \
    "$REMOTE_DEV_TEST_CODEX_ARGS" \
    "$REMOTE_DEV_TEST_SESSION_STATUS" \
    "$REMOTE_DEV_TEST_SESSION_OUTPUT"
  PATH="$bin_dir:$PATH" "$fixture"
}

run_attach
[[ "$(<"$REMOTE_DEV_TEST_SESSION_STATUS")" == 0 ]]
[[ -e "$REMOTE_DEV_TEST_DIRECT_SESSION_MARKER" ]]
[[ "$(<"$REMOTE_DEV_TEST_CODEX_CWD")" == "$project" ]]
mapfile -t baseline_args <"$REMOTE_DEV_TEST_CODEX_ARGS"
[[ "${#baseline_args[@]}" == 2 ]]
[[ "${baseline_args[0]}" == --cd ]]
[[ "${baseline_args[1]}" == "$project" ]]

replacement_project="$workdir/replacement-project"
original_project="$workdir/original-project"
mkdir -p "$replacement_project"
export REMOTE_DEV_TEST_SWAP_MODE=directory
export REMOTE_DEV_TEST_ORIGINAL_PROJECT="$original_project"
export REMOTE_DEV_TEST_REPLACEMENT_PROJECT="$replacement_project"
run_attach
unset REMOTE_DEV_TEST_SWAP_MODE REMOTE_DEV_TEST_ORIGINAL_PROJECT REMOTE_DEV_TEST_REPLACEMENT_PROJECT
[[ "$(<"$REMOTE_DEV_TEST_SESSION_STATUS")" == 2 ]]
grep -Fq "ERROR: project path changed during direct launch: $project" "$REMOTE_DEV_TEST_SESSION_OUTPUT"
[[ ! -e "$REMOTE_DEV_TEST_DIRECT_SESSION_MARKER" ]]
[[ ! -e "$REMOTE_DEV_TEST_CODEX_CWD" ]]
[[ ! -e "$REMOTE_DEV_TEST_CODEX_ARGS" ]]
[[ -d "$project" && ! -L "$project" ]]
rm -rf -- "$project"
mv -- "$original_project" "$project"

outside_project="$workdir/outside-project"
original_project="$workdir/original-project"
mkdir -p "$outside_project"
export REMOTE_DEV_TEST_SWAP_MODE=symlink
export REMOTE_DEV_TEST_ORIGINAL_PROJECT="$original_project"
export REMOTE_DEV_TEST_SYMLINK_TARGET="$outside_project"
run_attach
unset REMOTE_DEV_TEST_SWAP_MODE REMOTE_DEV_TEST_ORIGINAL_PROJECT REMOTE_DEV_TEST_SYMLINK_TARGET
[[ "$(<"$REMOTE_DEV_TEST_SESSION_STATUS")" == 2 ]]
grep -Fq "ERROR: project path changed during direct launch: $project" "$REMOTE_DEV_TEST_SESSION_OUTPUT"
[[ ! -e "$REMOTE_DEV_TEST_DIRECT_SESSION_MARKER" ]]
[[ ! -e "$REMOTE_DEV_TEST_CODEX_CWD" ]]
[[ ! -e "$REMOTE_DEV_TEST_CODEX_ARGS" ]]
[[ -L "$project" ]]
rm -f -- "$project"
mv -- "$original_project" "$project"

echo 'Direct Codex project identity entry guard: OK'
