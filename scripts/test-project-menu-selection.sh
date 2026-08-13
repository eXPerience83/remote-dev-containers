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
if [[ ! -e "$REMOTE_DEV_TEST_ADD_MARKER" ]]; then
  mkdir -- "$WORKSPACE/second-project"
  : >"$REMOTE_DEV_TEST_ADD_MARKER"
fi
CLEAR

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

printf '1\n\n12\n' | env \
  PATH="$bin_dir:$PATH" \
  WORKSPACE="$workspace" \
  REMOTE_DEV_ROLE=codex \
  REMOTE_DEV_TEST_INVOCATIONS="$invocations" \
  REMOTE_DEV_TEST_ADD_MARKER="$add_marker" \
  "$fixture_menu" >/dev/null 2>&1

[[ -d "$workspace/second-project" ]] || {
  echo 'ERROR: race fixture did not add the second project after initial menu selection' >&2
  exit 1
}
expected="[--cd][$workspace/project]"
actual="$(<"$invocations")"
[[ "$actual" == "$expected" ]] || {
  printf 'ERROR: auto-selected project was not retained after a second project appeared: expected %q, got %q\n' \
    "$expected" "$actual" >&2
  exit 1
}

echo 'Menu-session single-project auto-selection persistence: OK'
