#!/usr/bin/env bash
set -euo pipefail

source_file="${REMOTE_DEV_RUN_DIRECT_SESSION:-$(dirname "$0")/run-direct-session.sh}"
workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT

fixture="$workdir/run-direct-session"
runtime_lib="$workdir/remote-dev-runtime.sh"
secure_state="$workdir/secure-persistent-state"
command_fixture="$workdir/delete-cwd"
marker="$workdir/hardening-marker"

cat >"$runtime_lib" <<'RUNTIME'
remote_dev_recover_safe_cwd() {
  builtin cd -P -- /
}
RUNTIME

cat >"$secure_state" <<'SECURE'
#!/usr/bin/env bash
set -euo pipefail
printf 'cwd=%s\n' "$PWD" >"$REMOTE_DEV_TEST_HARDENING_MARKER"
[[ "${REMOTE_DEV_TEST_HARDENING_FAIL:-0}" != 1 ]] || exit 9
SECURE
chmod 0755 "$secure_state"

cat >"$command_fixture" <<'COMMAND'
#!/usr/bin/env bash
set -euo pipefail
cwd="$PWD"
builtin cd -P -- "$cwd"
rmdir -- "$cwd"
exit 23
COMMAND
chmod 0755 "$command_fixture"

python3 - "$source_file" "$fixture" "$runtime_lib" "$secure_state" <<'PY'
from pathlib import Path
import shlex
import sys

source, destination, runtime_lib, secure_state = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
replacements = {
    "readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh":
        f"readonly runtime_lib={shlex.quote(str(runtime_lib))}",
    "readonly secure_state=/usr/local/bin/secure-persistent-state":
        f"readonly secure_state={shlex.quote(str(secure_state))}",
}
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$fixture"

project="$workdir/project"
mkdir "$project"
status=0
(
  cd "$project"
  REMOTE_DEV_TEST_HARDENING_MARKER="$marker" "$fixture" "$command_fixture"
) >"$workdir/out" 2>"$workdir/err" || status=$?

[[ "$status" == 23 ]] || {
  echo "ERROR: deleted-cwd session returned $status instead of 23" >&2
  cat "$workdir/err" >&2
  exit 1
}
[[ -f "$marker" && "$(<"$marker")" == 'cwd=/' ]] || {
  echo "ERROR: persistent-state hardening did not run from safe cwd" >&2
  exit 1
}
if grep -Eqi 'getcwd|shell-init|current directory' "$workdir/err"; then
  echo "ERROR: deleted-cwd cleanup emitted cwd initialization noise" >&2
  cat "$workdir/err" >&2
  exit 1
fi

# Hardening failure remains stronger than the original command status.
project="$workdir/project-hardening-fail"
mkdir "$project"
status=0
(
  cd "$project"
  REMOTE_DEV_TEST_HARDENING_MARKER="$marker" \
    REMOTE_DEV_TEST_HARDENING_FAIL=1 \
    "$fixture" "$command_fixture"
) >"$workdir/out-fail" 2>"$workdir/err-fail" || status=$?
[[ "$status" == 1 ]] || {
  echo "ERROR: hardening failure returned $status instead of 1" >&2
  cat "$workdir/err-fail" >&2
  exit 1
}
grep -Fq 'failed to secure persistent credential state after direct session' "$workdir/err-fail"

echo 'Direct-session deleted-cwd recovery and exit-status contract: OK'
