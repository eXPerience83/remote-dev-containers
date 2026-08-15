#!/usr/bin/env bash
set -euo pipefail

menu_source="${REMOTE_DEV_MENU:-$(dirname "$0")/remote-dev-menu.sh}"
runtime_lib="${REMOTE_DEV_RUNTIME_LIB:-$(dirname "$0")/lib/remote-dev-runtime.sh}"
workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT

fixture_menu="$workdir/remote-dev-menu"
bin_dir="$workdir/bin"
workspace="$workdir/workspace"
invocations="$workdir/invocations"
add_marker="$workdir/second-project-added"
mkdir -p "$bin_dir" "$workspace/project"

cat >"$bin_dir/run-codex" <<'RUN_CODEX'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --print-policy ]]; then
  printf '%s\n' \
    'Codex approval mode: autonomous' \
    'Codex approval policy: never' \
    'Mode source: default'
  exit 0
fi
printf '[' >>"$REMOTE_DEV_TEST_INVOCATIONS"
separator=""
for argument in "$@"; do
  printf '%s%s' "$separator" "$argument" >>"$REMOTE_DEV_TEST_INVOCATIONS"
  separator=']['
done
printf ']\n' >>"$REMOTE_DEV_TEST_INVOCATIONS"
if [[ "${REMOTE_DEV_TEST_ADD_AFTER_LAUNCH:-0}" == 1 && ! -e "$REMOTE_DEV_TEST_ADD_MARKER" ]]; then
  mkdir -- "$WORKSPACE/second-project"
  : >"$REMOTE_DEV_TEST_ADD_MARKER"
fi
RUN_CODEX

cat >"$bin_dir/remote-dev-codex-runtime" <<'RUNTIME_STATUS'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == status && "${2:-}" == --menu ]]
printf '%s\n' 'Codex runtime: test'
RUNTIME_STATUS

cat >"$bin_dir/remote-dev-context7" <<'CONTEXT7_STATUS'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == status && "${2:-}" == --menu ]]
printf '%s\n' 'Context7: test'
CONTEXT7_STATUS

cat >"$bin_dir/secure-persistent-state" <<'SECURE'
#!/usr/bin/env bash
exit 0
SECURE

cat >"$bin_dir/remote-dev-version" <<'VERSION'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --check) exit 0 ;;
  --menu) printf '%s\n' 'Image: test' ;;
  *) exit 2 ;;
esac
VERSION

cat >"$bin_dir/clear" <<'CLEAR'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${REMOTE_DEV_TEST_ADD_ON_CLEAR:-0}" == 1 && ! -e "$REMOTE_DEV_TEST_ADD_MARKER" ]]; then
  mkdir -- "$WORKSPACE/second-project"
  : >"$REMOTE_DEV_TEST_ADD_MARKER"
fi
CLEAR

cat >"$bin_dir/rm" <<'RM'
#!/usr/bin/env bash
set -euo pipefail
/bin/rm "$@"
if [[ "${REMOTE_DEV_TEST_INVALIDATE_WORKSPACE_AFTER_RM:-0}" == 1 ]]; then
  marker="${REMOTE_DEV_TEST_INVALIDATE_MARKER:-}"
  [[ -n "$marker" ]] || exit 8
  if [[ ! -e "$marker" ]]; then
    moved="${WORKSPACE}.moved"
    mv -- "$WORKSPACE" "$moved"
    ln -s -- "$moved" "$WORKSPACE"
    : >"$marker"
  fi
fi
RM

chmod 0755 "$bin_dir"/*

python3 - "$menu_source" "$fixture_menu" "$runtime_lib" "$bin_dir" <<'PY'
from pathlib import Path
import sys

source, destination, runtime_lib, bin_dir = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
replacements = {
    "runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh": f"runtime_lib={runtime_lib}",
    "/usr/local/bin/run-codex": str(bin_dir / "run-codex"),
    "/usr/local/bin/remote-dev-codex-runtime": str(bin_dir / "remote-dev-codex-runtime"),
    "/usr/local/bin/remote-dev-context7": str(bin_dir / "remote-dev-context7"),
    "/usr/local/bin/secure-persistent-state": str(bin_dir / "secure-persistent-state"),
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"missing fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$fixture_menu"

# show_codex_menu refreshes the project selection in the parent shell before
# invoking clear. Inject the second project from clear so it appears after the
# sole project has been persisted in menu-session state but before Start input.
printf '1\n\n12\n' | env \
  PATH="$bin_dir:$PATH" \
  WORKSPACE="$workspace" \
  REMOTE_DEV_ROLE=codex \
  REMOTE_DEV_TEST_INVOCATIONS="$invocations" \
  REMOTE_DEV_TEST_ADD_MARKER="$add_marker" \
  REMOTE_DEV_TEST_ADD_ON_CLEAR=1 \
  "$fixture_menu" >/dev/null 2>&1

[[ -d "$workspace/second-project" ]] || {
  echo 'ERROR: race fixture did not add the second project after initial menu selection' >&2
  exit 1
}
expected="[--cd][$workspace/project]"
actual="$(<"$invocations")"
[[ "$actual" == "$expected" ]] || {
  printf 'ERROR: auto-selected project was not retained after a second project appeared before Start: expected %q, got %q\n' \
    "$expected" "$actual" >&2
  exit 1
}

echo 'Menu-session auto-selection survives a project appearing before Start: OK'

# Complement the render-to-Start regression with a second timing window: add a
# sibling only after the first Codex invocation has been recorded, then launch
# again from the same live menu session. Both launches must retain the original
# auto-selected project instead of becoming ambiguous.
rm -rf -- "$workspace/second-project"
rm -f "$invocations" "$add_marker"
post_launch_output="$workdir/post-launch-output"
printf '1\n\n1\n\n12\n' | env \
  PATH="$bin_dir:$PATH" \
  WORKSPACE="$workspace" \
  REMOTE_DEV_ROLE=codex \
  REMOTE_DEV_TEST_INVOCATIONS="$invocations" \
  REMOTE_DEV_TEST_ADD_MARKER="$add_marker" \
  REMOTE_DEV_TEST_ADD_AFTER_LAUNCH=1 \
  "$fixture_menu" >"$post_launch_output" 2>&1

[[ -d "$workspace/second-project" ]] || {
  echo 'ERROR: post-launch fixture did not add the second project after the first Codex invocation' >&2
  exit 1
}
expected_two="$expected
$expected"
actual="$(<"$invocations")"
[[ "$actual" == "$expected_two" ]] || {
  printf 'ERROR: active project was not retained across launches after a sibling appeared: expected %q, got %q\n' \
    "$expected_two" "$actual" >&2
  exit 1
}
if grep -Fq \
  'ERROR: multiple projects are available; select one in Projects... before starting an agent' \
  "$post_launch_output"; then
  echo 'ERROR: post-launch sibling incorrectly made the active menu project ambiguous' >&2
  exit 1
fi

echo 'Menu-session auto-selection persists across launches after a sibling appears: OK'

rm -f "$invocations"
oversized_output="$workdir/oversized-output"
printf '3\n1\n18446744073709551617\n4\n1\n\n12\n' | env \
  PATH="$bin_dir:$PATH" \
  WORKSPACE="$workspace" \
  REMOTE_DEV_ROLE=codex \
  REMOTE_DEV_TEST_INVOCATIONS="$invocations" \
  REMOTE_DEV_TEST_ADD_MARKER="$add_marker" \
  "$fixture_menu" >"$oversized_output" 2>&1

if [[ -s "$invocations" ]]; then
  echo 'ERROR: oversized numeric project choice selected a project after integer wraparound' >&2
  cat "$invocations" >&2
  exit 1
fi
if ! grep -Fq \
  'ERROR: multiple projects are available; select one in Projects... before starting an agent' \
  "$oversized_output"; then
  echo 'ERROR: oversized numeric project choice did not remain rejected' >&2
  exit 1
fi

echo 'Oversized numeric project choices are rejected before arithmetic conversion: OK'

# If the project collection becomes invalid immediately after a confirmed
# deletion, the deletion itself may have succeeded but its refresh must remain
# an action failure. Never print a normal success message from stale menu state.
delete_refresh_output="$workdir/delete-refresh-output"
invalidate_marker="$workdir/workspace-invalidated"
set +e
printf '3\n3\n2\nsecond-project\n\n' | env \
  PATH="$bin_dir:$PATH" \
  WORKSPACE="$workspace" \
  REMOTE_DEV_ROLE=codex \
  REMOTE_DEV_TEST_INVOCATIONS="$invocations" \
  REMOTE_DEV_TEST_ADD_MARKER="$add_marker" \
  REMOTE_DEV_TEST_INVALIDATE_WORKSPACE_AFTER_RM=1 \
  REMOTE_DEV_TEST_INVALIDATE_MARKER="$invalidate_marker" \
  "$fixture_menu" >"$delete_refresh_output" 2>&1
status=$?
set -e

[[ "$status" == 2 ]] || {
  echo "ERROR: post-delete workspace invalidation returned status $status instead of 2" >&2
  cat "$delete_refresh_output" >&2
  exit 1
}
[[ -e "$invalidate_marker" ]] || {
  echo 'ERROR: delete-refresh fixture did not invalidate the workspace after rm' >&2
  exit 1
}
[[ ! -e "$workspace.moved/second-project" ]] || {
  echo 'ERROR: confirmed project deletion did not remove the selected project' >&2
  exit 1
}
grep -Fq 'WORKSPACE contains a symlinked path component' "$delete_refresh_output"
if grep -Fxq 'Deleted project: second-project' "$delete_refresh_output"; then
  echo 'ERROR: post-delete refresh failure was reported as an ordinary successful deletion action' >&2
  exit 1
fi

echo 'Post-delete project refresh failures remain visible to the menu: OK'
