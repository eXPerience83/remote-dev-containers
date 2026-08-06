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
mkdir -p "$workspace"

cat >"$runtime_lib" <<'RUNTIME'
remote_dev_resolve_role() {
  printf '%s\n' antigravity
}
RUNTIME

cat >"$manager" <<MANAGER
#!/usr/bin/env bash
set -euo pipefail
case "\${1:-}" in
  path) printf '%s\\n' '$binary' ;;
  status) printf '%s\\n' '1.1.10' ;;
  *) exit 2 ;;
esac
MANAGER

cat >"$binary" <<'BINARY'
#!/usr/bin/env bash
set -euo pipefail
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
printf 'hardened\n' >>"$REMOTE_DEV_TEST_HARDENING"
SECURE
chmod 0755 "$manager" "$binary" "$picker" "$secure_state"

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
export WORKSPACE="$workspace"
export TMUX_PANE=%4
export REMOTE_DEV_TEST_VENDOR_ARGS="$workdir/vendor-args"
export REMOTE_DEV_TEST_PICKER_ARGS="$workdir/picker-args"
export REMOTE_DEV_TEST_HARDENING="$workdir/hardening"
export REMOTE_DEV_TEST_EXPECT_PICKER=1

"$runner" --remote-dev-open-resume-picker 'literal space' ';not evaluated'
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

rm -f "$REMOTE_DEV_TEST_PICKER_ARGS" "$REMOTE_DEV_TEST_VENDOR_ARGS"
unset REMOTE_DEV_TEST_EXPECT_PICKER
"$runner" normal
[[ ! -e "$REMOTE_DEV_TEST_PICKER_ARGS" ]]
[[ "$(<"$REMOTE_DEV_TEST_VENDOR_ARGS")" == normal ]]
[[ "$(wc -l <"$REMOTE_DEV_TEST_HARDENING")" == 2 ]]

set +e
TMUX_PANE=invalid "$runner" --remote-dev-open-resume-picker >/dev/null 2>&1
status=$?
set -e
[[ "$status" == 2 ]]

rm -f "$REMOTE_DEV_TEST_VENDOR_ARGS"
export REMOTE_DEV_TEST_PICKER_SNAPSHOT_FAIL=1
set +e
"$runner" --remote-dev-open-resume-picker >/dev/null 2>&1
status=$?
set -e
unset REMOTE_DEV_TEST_PICKER_SNAPSHOT_FAIL
[[ "$status" == 1 ]]
[[ ! -e "$REMOTE_DEV_TEST_VENDOR_ARGS" ]]
[[ "$(wc -l <"$REMOTE_DEV_TEST_HARDENING")" == 3 ]]

echo 'Antigravity picker launcher: OK'
