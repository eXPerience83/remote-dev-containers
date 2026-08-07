#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANAGER_SOURCE="$ROOT/scripts/remote-dev-antigravity.sh"
RUNNER_SOURCE="$ROOT/scripts/run-antigravity.sh"
RUNTIME_SOURCE="$ROOT/scripts/lib/remote-dev-runtime.sh"
ANTIGRAVITY_LIB_SOURCE="$ROOT/scripts/lib/antigravity-runtime"

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
harness="$temporary/harness"
test_bin="$temporary/test-bin"
MANAGER="$harness/remote-dev-antigravity"
RUNNER="$harness/run-antigravity"
RUNTIME_LIB="$harness/remote-dev-runtime.sh"
PATHS_LIB="$harness/antigravity-paths.sh"
ANTIGRAVITY_LIB_DIR="$harness/antigravity-runtime"
SECURE_SCRIPT="$harness/secure-persistent-state"
mkdir -p "$harness" "$test_bin"
cp -R -- "$ANTIGRAVITY_LIB_SOURCE" "$ANTIGRAVITY_LIB_DIR"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
expect_failure() { if "$@"; then fail "command unexpectedly succeeded: $*"; fi; }

cp -- "$RUNTIME_SOURCE" "$RUNTIME_LIB"
chmod 0444 "$RUNTIME_LIB"
python3 - "$MANAGER_SOURCE" "$MANAGER" "$PATHS_LIB" "$RUNTIME_LIB" "$ANTIGRAVITY_LIB_DIR" <<'PY'
from pathlib import Path
import shlex
import sys
source, destination, paths_lib, runtime_lib, antigravity_lib_dir = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
for old, new in {
    "/usr/local/lib/remote-dev/antigravity-paths.sh": shlex.quote(str(paths_lib)),
    "/usr/local/lib/remote-dev/remote-dev-runtime.sh": shlex.quote(str(runtime_lib)),
    "/usr/local/lib/remote-dev/antigravity-runtime": shlex.quote(str(antigravity_lib_dir)),
}.items():
    if text.count(old) != 1:
        raise SystemExit(f"expected one canonical manager path: {old}")
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

cat >"$test_bin/curl" <<'CURL_FIXTURE'
#!/usr/bin/env bash
set -euo pipefail
output=""
while (( $# )); do
  case "$1" in
    --output|-o) output="$2"; shift 2 ;;
    --write-out) shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$output" ]] || { echo 'fixture curl received no output path' >&2; exit 2; }
[[ -z "${REMOTE_DEV_TEST_CURL_MARKER:-}" ]] || : >"$REMOTE_DEV_TEST_CURL_MARKER"
cp -- "${REMOTE_DEV_TEST_INSTALLER_FIXTURE:?fixture installer is required}" "$output"
printf '%s\n%s\n%s\n%s\n' \
  '200' \
  "${REMOTE_DEV_TEST_FINAL_URL:-https://antigravity.google/cli/install.sh}" \
  'application/x-sh' \
  ''
CURL_FIXTURE
chmod 0755 "$test_bin/curl"

cat >"$test_bin/readelf" <<'READELF_FIXTURE'
#!/usr/bin/env bash
printf '%s\n' \
  'ELF Header:' \
  '  Class:                             ELF64' \
  '  Machine:                           Advanced Micro Devices X86-64'
READELF_FIXTURE
chmod 0755 "$test_bin/readelf"

cat >"$SECURE_SCRIPT" <<'SECURE_FIXTURE'
#!/usr/bin/env bash
set -euo pipefail
: >"${REMOTE_DEV_TEST_SECURE_MARKER:?secure marker is required}"
SECURE_FIXTURE
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
  {
    printf 'readonly ANTIGRAVITY_EVIDENCE=%q\n' "$EVIDENCE"
    printf 'readonly ANTIGRAVITY_BIN_DIR=%q\n' "$BIN_DIR"
    printf 'readonly ANTIGRAVITY_BINARY=%q\n' "$BINARY"
    printf 'readonly ANTIGRAVITY_STATE_DIR=%q\n' "$STATE_DIR"
    printf 'readonly ANTIGRAVITY_MANIFEST=%q\n' "$MANIFEST"
    printf 'readonly ANTIGRAVITY_VENDOR_STATE_DIR=%q\n' "$VENDOR_STATE_DIR"
  } >"$PATHS_LIB"
  chmod 0444 "$PATHS_LIB"
}

make_payload() {
  local path="$1" version="$2" side_effect="${3:-}"
  cat >"$path" <<EOF_PAYLOAD
#!/usr/bin/env bash
set -euo pipefail
$side_effect
case "\${1:-}" in
  --version) printf '%s\\n' '$version' ;;
  --help) printf '%s\\n' 'Usage: agy [args...]' ;;
  *)
    if [[ -n "\${REMOTE_DEV_TEST_ARGS_FILE:-}" ]]; then
      : >"\$REMOTE_DEV_TEST_ARGS_FILE"
      for argument in "\$@"; do printf '%s\\n' "\$argument" >>"\$REMOTE_DEV_TEST_ARGS_FILE"; done
    fi
    if [[ -n "\${REMOTE_DEV_TEST_AUTO_UPDATE_FILE:-}" ]]; then
      printf '%s\\n' "\${AGY_CLI_DISABLE_AUTO_UPDATE:-unset}" >"\$REMOTE_DEV_TEST_AUTO_UPDATE_FILE"
    fi
    exit "\${REMOTE_DEV_TEST_EXIT_CODE:-0}"
    ;;
esac
EOF_PAYLOAD
  chmod 0755 "$path"
}

make_installer() {
  local path="$1" payload="$2" mode="${3:-good}" execution_marker="${4:-}"
  local encoded
  encoded="$(base64 -w0 "$payload")"
  cat >"$path" <<EOF_INSTALLER
#!/usr/bin/env bash
set -euo pipefail
${execution_marker:+touch '$execution_marker'}
if [[ "\${1:-}" == --help ]]; then
EOF_INSTALLER
  if [[ "$mode" == incompatible ]]; then
    echo "  printf '%s\\n' 'Usage: install.sh --prefix <path>'" >>"$path"
  else
    echo "  printf '%s\\n' 'Usage: install.sh --dir <path>'" >>"$path"
  fi
  cat >>"$path" <<'EOF_INSTALLER'
  exit 0
fi
[[ "${1:-}" == --dir && -n "${2:-}" ]] || exit 2
EOF_INSTALLER
  case "$mode" in
    good)
      cat >>"$path" <<EOF_INSTALLER
mkdir -p "\$2"
printf '%s' '$encoded' | base64 -d >"\$2/agy"
chmod 0700 "\$2/agy"
EOF_INSTALLER
      ;;
    fail) echo 'exit 42' >>"$path" ;;
    wrong-location)
      cat >>"$path" <<EOF_INSTALLER
mkdir -p "\$2"
printf '%s' '$encoded' | base64 -d >"\$2/not-agy"
chmod 0700 "\$2/not-agy"
EOF_INSTALLER
      ;;
    incompatible) echo 'exit 2' >>"$path" ;;
    *) fail "unsupported installer fixture mode: $mode" ;;
  esac
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
    '{
      schema_version: 2,
      installer: {
        official_url: "https://antigravity.google/cli/install.sh",
        sha256: $installer_sha,
        size: $installer_size
      },
      installed_binary: {
        sha256: $binary_sha,
        size: $binary_size,
        version: $version
      },
      blocking_findings: []
    }' >"$EVIDENCE"
}

cancel_install_in_pty() {
  python3 - "$MANAGER" <<'PY'
import os
import pty
import select
import signal
import sys
import time
pid, fd = pty.fork()
if pid == 0:
    os.execv("/bin/bash", ["bash", sys.argv[1], "install"])
os.write(fd, b"n\n")
deadline = time.monotonic() + 30
while True:
    if time.monotonic() >= deadline:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        raise SystemExit("cancelled installation timed out")
    readable, _, _ = select.select([fd], [], [], 1)
    if not readable:
        continue
    try:
        chunk = os.read(fd, 4096)
    except OSError:
        break
    if not chunk:
        break
_, status = os.waitpid(pid, 0)
raise SystemExit(os.waitstatus_to_exitcode(status))
PY
}

reset_runtime
payload_v1="$temporary/payload-v1"
installer_v1="$temporary/installer-v1.sh"
make_payload "$payload_v1" '1.0.0'
make_installer "$installer_v1" "$payload_v1"
write_evidence "$installer_v1" "$payload_v1" '1.0.0'

export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$temporary/does-not-exist"
export REMOTE_DEV_TEST_CURL_MARKER="$temporary/cancelled-curl"
cancel_install_in_pty
test ! -e "$REMOTE_DEV_TEST_CURL_MARKER" || fail "cancelled install used the network"
test ! -e "$BINARY" || fail "cancelled install created an executable"
unset REMOTE_DEV_TEST_CURL_MARKER

export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_v1"
bash "$MANAGER" install --yes >/dev/null
test -x "$BINARY" || fail "installation did not publish the executable"
test "$(stat -c '%a' "$BINARY")" = 700 || fail "executable mode is not 700"
test "$(stat -c '%a' "$MANIFEST")" = 600 || fail "manifest mode is not 600"
test "$(jq -r '.schema_version' "$MANIFEST")" = 2 || fail "new install did not write manifest schema 2"
test "$(bash "$MANAGER" status --menu)" = 'Antigravity: 1.0.0 (official and reviewed)' \
  || fail "reviewed status is incorrect"

# The launcher preserves literal arguments, disables vendor self-update and preserves exit status.
export REMOTE_DEV_TEST_SECURE_MARKER="$temporary/secure-called"
export REMOTE_DEV_TEST_ARGS_FILE="$temporary/args.log"
export REMOTE_DEV_TEST_AUTO_UPDATE_FILE="$temporary/auto-update.log"
export REMOTE_DEV_TEST_EXIT_CODE=0
pwned="$temporary/pwned"
bash "$RUNNER" 'literal space' "\$(touch $pwned)" ';echo injected'
test -f "$REMOTE_DEV_TEST_SECURE_MARKER" || fail "runner did not harden state"
test ! -e "$pwned" || fail "runner evaluated a literal argument"
mapfile -t recorded_args <"$REMOTE_DEV_TEST_ARGS_FILE"
test "${recorded_args[0]}" = 'literal space' || fail "runner changed argument one"
test "${recorded_args[1]}" = "\$(touch $pwned)" || fail "runner changed argument two"
test "${recorded_args[2]}" = ';echo injected' || fail "runner changed argument three"
test "$(<"$REMOTE_DEV_TEST_AUTO_UPDATE_FILE")" = true || fail "runner did not disable auto-update"
export REMOTE_DEV_TEST_EXIT_CODE=23
runner_status=0
bash "$RUNNER" >/dev/null 2>&1 || runner_status=$?
test "$runner_status" = 23 || fail "runner did not preserve exit status"
unset REMOTE_DEV_TEST_EXIT_CODE

# A newer reviewed target in the image does not invalidate an intact older installation.
payload_v2="$temporary/payload-v2"
installer_v2="$temporary/installer-v2.sh"
make_payload "$payload_v2" '2.0.0'
make_installer "$installer_v2" "$payload_v2"
write_evidence "$installer_v2" "$payload_v2" '2.0.0'
test "$(bash "$MANAGER" status --menu)" = \
  'Antigravity: 1.0.0 (official source; Remote Dev review pending)' \
  || fail "older intact installation was not admitted as review pending"
bash "$RUNNER" >/dev/null || fail "review-pending installation did not launch"

# Explicit update installs a compatible official-source payload even when image evidence is stale.
payload_v3="$temporary/payload-v3"
installer_v3="$temporary/installer-v3.sh"
make_payload "$payload_v3" '3.0.0'
make_installer "$installer_v3" "$payload_v3"
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_v3"
bash "$MANAGER" update --yes >/dev/null
test "$(bash "$MANAGER" status --menu)" = \
  'Antigravity: 3.0.0 (official source; Remote Dev review pending)' \
  || fail "official-source candidate was not admitted as review pending"

# Status and normal launch never download or update.
export REMOTE_DEV_TEST_CURL_MARKER="$temporary/status-curl"
rm -f "$REMOTE_DEV_TEST_CURL_MARKER"
bash "$MANAGER" status >/dev/null
bash "$RUNNER" >/dev/null
test ! -e "$REMOTE_DEV_TEST_CURL_MARKER" || fail "status or launch called the installer endpoint"
unset REMOTE_DEV_TEST_CURL_MARKER

# Failed and incompatible updates leave the previous binary and manifest untouched.
old_binary_sha="$(sha256sum "$BINARY" | awk '{print $1}')"
old_manifest_sha="$(sha256sum "$MANIFEST" | awk '{print $1}')"
installer_fail="$temporary/installer-fail.sh"
make_installer "$installer_fail" "$payload_v2" fail
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_fail"
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
test "$(sha256sum "$BINARY" | awk '{print $1}')" = "$old_binary_sha" || fail "failed update replaced executable"
test "$(sha256sum "$MANIFEST" | awk '{print $1}')" = "$old_manifest_sha" || fail "failed update replaced manifest"
installer_incompatible="$temporary/installer-incompatible.sh"
make_installer "$installer_incompatible" "$payload_v2" incompatible
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_incompatible"
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
test "$(sha256sum "$BINARY" | awk '{print $1}')" = "$old_binary_sha" || fail "incompatible update replaced executable"

# Redirects outside the fixed Google origin and unexpected layouts fail before publication.
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_v2"
export REMOTE_DEV_TEST_FINAL_URL='https://example.invalid/install.sh'
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
unset REMOTE_DEV_TEST_FINAL_URL
test "$(sha256sum "$BINARY" | awk '{print $1}')" = "$old_binary_sha" || fail "external redirect changed executable"
installer_wrong="$temporary/installer-wrong.sh"
make_installer "$installer_wrong" "$payload_v2" wrong-location
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_wrong"
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
test "$(sha256sum "$BINARY" | awk '{print $1}')" = "$old_binary_sha" || fail "wrong package layout changed executable"

# Malformed version output is incompatible and preserves the old installation.
payload_bad="$temporary/payload-bad"
installer_bad="$temporary/installer-bad.sh"
make_payload "$payload_bad" 'not-a-version'
make_installer "$installer_bad" "$payload_bad"
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_bad"
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
test "$(sha256sum "$BINARY" | awk '{print $1}')" = "$old_binary_sha" || fail "malformed payload changed executable"

# A missing installation never causes an implicit download from the runner.
mv "$BINARY" "$temporary/saved-agy"
export REMOTE_DEV_TEST_CURL_MARKER="$temporary/missing-curl"
expect_failure bash "$RUNNER" >/dev/null 2>&1
test ! -e "$REMOTE_DEV_TEST_CURL_MARKER" || fail "missing installation triggered a download"
mv "$temporary/saved-agy" "$BINARY"
unset REMOTE_DEV_TEST_CURL_MARKER

printf 'Optional Antigravity review-state and lifecycle regressions: OK\n'
