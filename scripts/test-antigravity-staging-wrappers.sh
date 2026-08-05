#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_SOURCE="$ROOT/scripts/remote-dev-install-antigravity.sh"
UPDATE_SOURCE="$ROOT/scripts/remote-dev-update-antigravity.sh"

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT

staging_parent="$temporary/state"
manager="$temporary/remote-dev-antigravity"
install_wrapper="$temporary/remote-dev-install-antigravity"
update_wrapper="$temporary/remote-dev-update-antigravity"
record="$temporary/manager-record"
manager_entered="$temporary/manager-entered"
mkdir -p "$staging_parent"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

expect_failure() {
  if "$@"; then
    fail "command unexpectedly succeeded: $*"
  fi
}

cat >"$manager" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
: "${REMOTE_DEV_TEST_RECORD:?}"
: "${REMOTE_DEV_TEST_MANAGER_ENTERED:?}"
: "${TMPDIR:?}"
: >"$REMOTE_DEV_TEST_MANAGER_ENTERED"
staged="$(mktemp -d "$TMPDIR/remote-dev-antigravity.XXXXXXXX")"
{
  printf 'tmpdir=%s\n' "$TMPDIR"
  printf 'staged=%s\n' "$staged"
  printf 'arg=%s\n' "$@"
} >"$REMOTE_DEV_TEST_RECORD"
rm -rf -- "$staged"
EOF
chmod 0755 "$manager"

prepare_wrapper() {
  local source="$1"
  local destination="$2"
  python3 - "$source" "$destination" "$staging_parent" "$manager" <<'PY'
from pathlib import Path
import shlex
import sys

source, destination = map(Path, sys.argv[1:3])
staging_parent, manager = sys.argv[3:5]
text = source.read_text(encoding="utf-8")
replacements = {
    "readonly staging_parent=/root/.local/share/remote-dev/antigravity":
        f"readonly staging_parent={shlex.quote(staging_parent)}",
    "/usr/local/bin/remote-dev-antigravity": shlex.quote(manager),
}
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one wrapper fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
  chmod 0755 "$destination"
}

prepare_wrapper "$INSTALL_SOURCE" "$install_wrapper"
prepare_wrapper "$UPDATE_SOURCE" "$update_wrapper"
export REMOTE_DEV_TEST_RECORD="$record"
export REMOTE_DEV_TEST_MANAGER_ENTERED="$manager_entered"

"$install_wrapper" --yes 'literal space'
test -f "$manager_entered" || fail "install wrapper did not invoke the manager"
grep -Fx "tmpdir=$staging_parent" "$record" >/dev/null || fail "install wrapper used the wrong TMPDIR"
grep -E "^staged=${staging_parent}/remote-dev-antigravity[.]" "$record" >/dev/null \
  || fail "install wrapper staged outside the role-scoped state directory"
mapfile -t install_args < <(grep '^arg=' "$record" | sed 's/^arg=//')
test "${install_args[0]}" = install || fail "install wrapper changed the manager action"
test "${install_args[1]}" = --yes || fail "install wrapper changed the first argument"
test "${install_args[2]}" = 'literal space' || fail "install wrapper changed a literal argument"
test -z "$(find "$staging_parent" -mindepth 1 -maxdepth 1 -name 'remote-dev-antigravity.*' -print -quit)" \
  || fail "install wrapper left staging data behind"

rm -f -- "$manager_entered"
"$update_wrapper" --yes
test -f "$manager_entered" || fail "update wrapper did not invoke the manager"
grep -Fx "tmpdir=$staging_parent" "$record" >/dev/null || fail "update wrapper used the wrong TMPDIR"
mapfile -t update_args < <(grep '^arg=' "$record" | sed 's/^arg=//')
test "${update_args[0]}" = update || fail "update wrapper changed the manager action"
test "${update_args[1]}" = --yes || fail "update wrapper changed the update argument"

rm -rf -- "$staging_parent"
rm -f -- "$manager_entered"
expect_failure "$install_wrapper" --yes >/dev/null 2>&1
test ! -e "$manager_entered" || fail "missing staging path reached the manager"

outside="$temporary/outside"
mkdir -p "$outside"
ln -s "$outside" "$staging_parent"
rm -f -- "$manager_entered"
expect_failure "$update_wrapper" --yes >/dev/null 2>&1
test ! -e "$manager_entered" || fail "symlinked staging path reached the manager"

echo 'Antigravity staging wrapper regressions: OK'
