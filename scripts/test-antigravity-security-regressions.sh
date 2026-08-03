#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANAGER_SOURCE="$ROOT/scripts/remote-dev-antigravity.sh"
RUNNER_SOURCE="$ROOT/scripts/run-antigravity.sh"
RUNTIME_SOURCE="$ROOT/scripts/lib/remote-dev-runtime.sh"

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT

harness="$temporary/harness"
test_bin="$temporary/bin"
MANAGER="$harness/remote-dev-antigravity"
RUNNER="$harness/run-antigravity"
RUNTIME_LIB="$harness/remote-dev-runtime.sh"
PATHS_LIB="$harness/antigravity-paths.sh"
SECURE_SCRIPT="$harness/secure-persistent-state"
mkdir -p "$harness" "$test_bin"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

expect_failure() {
  if "$@"; then
    fail "command unexpectedly succeeded: $*"
  fi
}

cp -- "$RUNTIME_SOURCE" "$RUNTIME_LIB"
chmod 0644 "$RUNTIME_LIB"
python3 - "$MANAGER_SOURCE" "$MANAGER" "$PATHS_LIB" "$RUNTIME_LIB" <<'PY'
from pathlib import Path
import shlex
import sys
source, destination, paths_lib, runtime_lib = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
for old, new in {
    "readonly paths_lib=/usr/local/lib/remote-dev/antigravity-paths.sh":
        f"readonly paths_lib={shlex.quote(str(paths_lib))}",
    "readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh":
        f"readonly runtime_lib={shlex.quote(str(runtime_lib))}",
}.items():
    if text.count(old) != 1:
        raise SystemExit(f"missing manager fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
python3 - "$RUNNER_SOURCE" "$RUNNER" "$MANAGER" "$SECURE_SCRIPT" "$RUNTIME_LIB" <<'PY'
from pathlib import Path
import shlex
import sys
source, destination, manager, secure_state, runtime_lib = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
for old, new in {
    "readonly manager=/usr/local/bin/remote-dev-antigravity":
        f"readonly manager={shlex.quote(str(manager))}",
    "readonly secure_state=/usr/local/bin/secure-persistent-state":
        f"readonly secure_state={shlex.quote(str(secure_state))}",
    "readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh":
        f"readonly runtime_lib={shlex.quote(str(runtime_lib))}",
}.items():
    if text.count(old) != 1:
        raise SystemExit(f"missing runner fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$MANAGER" "$RUNNER"

cat >"$test_bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
output=""
while (( $# )); do
  case "$1" in
    --output|-o) output="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$output" ]] || exit 2
cp -- "${REMOTE_DEV_TEST_INSTALLER_FIXTURE:?}" "$output"
EOF
chmod 0755 "$test_bin/curl"

cat >"$SECURE_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
: >"${REMOTE_DEV_TEST_SECURE_MARKER:?}"
EOF
chmod 0755 "$SECURE_SCRIPT"

export PATH="$test_bin:$PATH"
export REMOTE_DEV_ROLE=antigravity
export REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1

reset_runtime() {
  rm -rf -- "$temporary/runtime"
  mkdir -p "$temporary/runtime/workspace"
  EVIDENCE="$temporary/runtime/evidence.json"
  BIN_DIR="$temporary/runtime/bin"
  BINARY="$BIN_DIR/agy"
  STATE_DIR="$temporary/runtime/state"
  MANIFEST="$STATE_DIR/install.json"
  VENDOR_STATE_DIR="$temporary/runtime/vendor"
  export WORKSPACE="$temporary/runtime/workspace"

  rm -f -- "$PATHS_LIB"
  printf 'readonly ANTIGRAVITY_EVIDENCE=%q\n' "$EVIDENCE" >"$PATHS_LIB"
  printf 'readonly ANTIGRAVITY_BIN_DIR=%q\n' "$BIN_DIR" >>"$PATHS_LIB"
  printf 'readonly ANTIGRAVITY_BINARY=%q\n' "$BINARY" >>"$PATHS_LIB"
  printf 'readonly ANTIGRAVITY_STATE_DIR=%q\n' "$STATE_DIR" >>"$PATHS_LIB"
  printf 'readonly ANTIGRAVITY_MANIFEST=%q\n' "$MANIFEST" >>"$PATHS_LIB"
  printf 'readonly ANTIGRAVITY_VENDOR_STATE_DIR=%q\n' "$VENDOR_STATE_DIR" >>"$PATHS_LIB"
  chmod 0444 "$PATHS_LIB"
}

make_payload() {
  local path="$1" version="$2" side_effect="${3:-}"
  cat >"$path" <<EOF
#!/usr/bin/env bash
set -euo pipefail
${side_effect}
case "\${1:-}" in
  --version) printf '%s\\n' '$version' ;;
  --read-stdin)
    IFS= read -r line
    printf '%s\\n' "\$line" >"\${REMOTE_DEV_TEST_STDIN_FILE:?}"
    ;;
  --signal-loop)
    : >"\${REMOTE_DEV_TEST_READY_MARKER:?}"
    trap ': >"\${REMOTE_DEV_TEST_SIGNAL_MARKER:?}"; exit 130' INT
    while :; do sleep 1; done
    ;;
  *) exit 0 ;;
esac
EOF
  chmod 0755 "$path"
}

make_installer() {
  local path="$1" payload="$2" help_mode="${3:-good}"
  local help_line='Usage: install.sh --dir <path>'
  [[ "$help_mode" == good ]] || help_line='Usage: install.sh --prefix <path>'
  local encoded
  encoded="$(base64 -w0 "$payload")"
  cat >"$path" <<EOF
#!/usr/bin/env bash
set -euo pipefail
install_dir=""
while ((\$#)); do
  case "\$1" in
    -d|--dir) install_dir="\$2"; shift 2 ;;
    -h|--help) printf '%s\\n' '$help_line'; exit 0 ;;
    *) exit 2 ;;
  esac
done
[[ -n "\$install_dir" ]] || exit 3
mkdir -p "\$install_dir"
printf '%s' '$encoded' | base64 -d >"\$install_dir/agy"
chmod 0755 "\$install_dir/agy"
EOF
  chmod 0755 "$path"
}

write_evidence() {
  local installer="$1" payload="$2" version="$3"
  jq -n \
    --arg installer_sha "$(sha256sum "$installer" | awk '{print $1}')" \
    --arg binary_sha "$(sha256sum "$payload" | awk '{print $1}')" \
    --arg version "$version" \
    --argjson installer_size "$(stat -c '%s' "$installer")" \
    --argjson binary_size "$(stat -c '%s' "$payload")" \
    '{schema_version:2,
      installer:{official_url:"https://antigravity.google/cli/install.sh",sha256:$installer_sha,size:$installer_size},
      installed_binary:{sha256:$binary_sha,size:$binary_size,version:$version},
      blocking_findings:[]}' >"$EVIDENCE"
}

install_fixture() {
  export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$1"
  bash "$MANAGER" install --yes >/dev/null
}

assert_signal_forwarding() {
  local signal_marker="$1" secure_marker="$2"
  python3 - "$RUNNER" "$signal_marker" "$secure_marker" <<'PY'
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
runner = sys.argv[1]
signal_marker = Path(sys.argv[2])
secure_marker = Path(sys.argv[3])
ready_marker = signal_marker.with_suffix(".ready")
env = os.environ.copy()
env["REMOTE_DEV_TEST_SIGNAL_MARKER"] = str(signal_marker)
env["REMOTE_DEV_TEST_READY_MARKER"] = str(ready_marker)
env["REMOTE_DEV_TEST_SECURE_MARKER"] = str(secure_marker)
proc = subprocess.Popen(["/bin/bash", runner, "--signal-loop"], env=env,
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, start_new_session=True)
deadline = time.monotonic() + 6
while not ready_marker.exists() and time.monotonic() < deadline:
    if proc.poll() is not None:
        out, err = proc.communicate()
        raise SystemExit(f"runner exited before readiness: {proc.returncode}\n{out}\n{err}")
    time.sleep(0.05)
if not ready_marker.exists():
    os.killpg(proc.pid, signal.SIGKILL)
    raise SystemExit("vendor child did not become ready")
os.kill(proc.pid, signal.SIGINT)
try:
    out, err = proc.communicate(timeout=6)
except subprocess.TimeoutExpired:
    os.killpg(proc.pid, signal.SIGKILL)
    out, err = proc.communicate()
    raise SystemExit(f"runner hung after SIGINT\n{out}\n{err}")
if proc.returncode != 130 or not signal_marker.exists() or not secure_marker.exists():
    raise SystemExit(f"SIGINT contract failed: rc={proc.returncode}\n{out}\n{err}")
PY
}

# The live installer contract must still advertise --dir before installation.
reset_runtime
payload="$temporary/payload"
bad_installer="$temporary/bad-installer"
make_payload "$payload" '1.0.0-fixture'
make_installer "$bad_installer" "$payload" bad
write_evidence "$bad_installer" "$payload" '1.0.0-fixture'
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$bad_installer"
expect_failure bash "$MANAGER" install --yes >/dev/null 2>&1
test ! -e "$BINARY" || fail "contract-drift installer published a binary"

# A valid installation keeps terminal stdin and forwarded SIGINT operational.
good_installer="$temporary/good-installer"
make_installer "$good_installer" "$payload" good
write_evidence "$good_installer" "$payload" '1.0.0-fixture'
install_fixture "$good_installer"
export REMOTE_DEV_TEST_SECURE_MARKER="$temporary/stdin-secure"
export REMOTE_DEV_TEST_STDIN_FILE="$temporary/stdin"
printf 'terminal input\n' | bash "$RUNNER" --read-stdin
test "$(<"$REMOTE_DEV_TEST_STDIN_FILE")" = 'terminal input' || fail "vendor stdin was detached"
assert_signal_forwarding "$temporary/signal" "$temporary/signal-secure"

# A writable manifest never authorizes execution of an unreviewed binary.
reset_runtime
untrusted_marker="$temporary/untrusted-ran"
untrusted="$temporary/untrusted"
make_payload "$untrusted" '9.9.9-fixture' "touch '$untrusted_marker'"
install -d -m 0700 "$BIN_DIR" "$STATE_DIR"
install -m 0700 "$untrusted" "$BINARY"
jq -n \
  --arg version '9.9.9-fixture' \
  --arg sha "$(sha256sum "$untrusted" | awk '{print $1}')" \
  --argjson size "$(stat -c '%s' "$untrusted")" \
  '{schema_version:1,version:$version,binary_sha256:$sha,binary_size:$size,runtime_installed:true,bundled_in_image:false}' \
  >"$MANIFEST"
chmod 0600 "$MANIFEST"
reviewed="$temporary/reviewed"
reviewed_installer="$temporary/reviewed-installer"
make_payload "$reviewed" '2.0.0-fixture'
make_installer "$reviewed_installer" "$reviewed" good
write_evidence "$reviewed_installer" "$reviewed" '2.0.0-fixture'
status=0
output="$(bash "$MANAGER" status --menu 2>&1)" || status=$?
test "$status" = 3 || fail "unverified status returned $status"
grep -Fq 'unverified installation' <<<"$output" || fail "unverified status was not explicit"
test ! -e "$untrusted_marker" || fail "status executed a manifest-authorized binary"
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$reviewed_installer"
bash "$MANAGER" update --yes >/dev/null
test ! -e "$untrusted_marker" || fail "update executed the previous unreviewed binary"
test "$(bash "$MANAGER" status)" = '2.0.0-fixture' || fail "reviewed update did not replace unverified binary"

printf 'Antigravity security regressions: OK\n'
