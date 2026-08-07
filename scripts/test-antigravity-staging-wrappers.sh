#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_SOURCE="$ROOT/scripts/remote-dev-install-antigravity.sh"
UPDATE_SOURCE="$ROOT/scripts/remote-dev-update-antigravity.sh"
COMMANDS_SOURCE="$ROOT/scripts/lib/antigravity-runtime/commands.sh"

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT

manager="$temporary/remote-dev-antigravity"
install_wrapper="$temporary/remote-dev-install-antigravity"
update_wrapper="$temporary/remote-dev-update-antigravity"
record="$temporary/manager-record"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

cat >"$manager" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
: "${REMOTE_DEV_TEST_RECORD:?}"
printf '%s\n' "$@" >"$REMOTE_DEV_TEST_RECORD"
EOF
chmod 0755 "$manager"

prepare_wrapper() {
  local source="$1"
  local destination="$2"
  python3 - "$source" "$destination" "$manager" <<'PYINNER'
from pathlib import Path
import shlex
import sys

source, destination = map(Path, sys.argv[1:3])
manager = sys.argv[3]
text = source.read_text(encoding="utf-8")
old = "/usr/local/bin/remote-dev-antigravity"
if text.count(old) != 1:
    raise SystemExit("expected one manager wrapper anchor")
destination.write_text(text.replace(old, shlex.quote(manager)), encoding="utf-8")
PYINNER
  chmod 0755 "$destination"
}

prepare_wrapper "$INSTALL_SOURCE" "$install_wrapper"
prepare_wrapper "$UPDATE_SOURCE" "$update_wrapper"
export REMOTE_DEV_TEST_RECORD="$record"

"$install_wrapper" --yes 'literal space'
mapfile -t install_args <"$record"
test "${install_args[0]}" = install || fail "install wrapper changed the action"
test "${install_args[1]}" = --yes || fail "install wrapper changed the first argument"
test "${install_args[2]}" = 'literal space' || fail "install wrapper changed a literal argument"

"$update_wrapper" --yes
mapfile -t update_args <"$record"
test "${update_args[0]}" = update || fail "update wrapper changed the action"
test "${update_args[1]}" = --yes || fail "update wrapper changed the argument"

grep -Fq 'mktemp -d "$state_dir/remote-dev-antigravity.XXXXXXXX"' "$COMMANDS_SOURCE" \
  || fail "canonical Antigravity commands library does not own the staging path"
! grep -Fq '${TMPDIR:-/tmp}/remote-dev-antigravity' "$COMMANDS_SOURCE" \
  || fail "canonical Antigravity commands library still honors caller-controlled TMPDIR"

echo 'Antigravity canonical staging and wrapper regressions: OK'
