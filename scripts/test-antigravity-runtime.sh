#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANAGER="$ROOT/scripts/remote-dev-antigravity.sh"
RUNNER="$ROOT/scripts/run-antigravity.sh"

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

expect_failure() {
  if "$@"; then
    fail "command unexpectedly succeeded: $*"
  fi
}

reset_runtime() {
  rm -rf -- "$temporary/runtime"
  mkdir -p "$temporary/runtime"
  export REMOTE_DEV_ANTIGRAVITY_TESTING=1
  export REMOTE_DEV_ANTIGRAVITY_EVIDENCE="$temporary/runtime/evidence.json"
  export REMOTE_DEV_ANTIGRAVITY_BIN_DIR="$temporary/runtime/bin"
  export REMOTE_DEV_ANTIGRAVITY_STATE_DIR="$temporary/runtime/state"
  export REMOTE_DEV_ANTIGRAVITY_VENDOR_STATE_DIR="$temporary/runtime/vendor-state"
  export REMOTE_DEV_ANTIGRAVITY_MANAGER="$MANAGER"
  export WORKSPACE="$temporary/runtime/workspace"
}

make_payload() {
  local path="$1"
  local version="$2"
  local side_effect="${3:-}"
  cat >"$path" <<EOF
#!/usr/bin/env bash
set -euo pipefail
${side_effect}
case "\${1:-}" in
  --version)
    printf '%s\\n' '$version'
    ;;
  --help)
    printf 'Usage: agy [args...]\\n'
    ;;
  *)
    if [[ -n "\${REMOTE_DEV_TEST_ARGS_FILE:-}" ]]; then
      : >"\$REMOTE_DEV_TEST_ARGS_FILE"
      for argument in "\$@"; do
        printf '%s\\n' "\$argument" >>"\$REMOTE_DEV_TEST_ARGS_FILE"
      done
    fi
    exit "\${REMOTE_DEV_TEST_EXIT_CODE:-0}"
    ;;
esac
EOF
  chmod 0755 "$path"
}

make_installer() {
  local path="$1"
  local payload="$2"
  local mode="${3:-good}"
  local execution_marker="${4:-}"
  local payload_b64
  payload_b64="$(base64 -w0 "$payload")"

  cat >"$path" <<EOF
#!/usr/bin/env bash
set -euo pipefail
${execution_marker:+touch '$execution_marker'}
install_dir=""
while ((\$#)); do
  case "\$1" in
    -d|--dir)
      [[ \$# -ge 2 ]] || exit 2
      install_dir="\$2"
      shift 2
      ;;
    -h|--help)
      printf '%s\\n' 'Usage: install.sh --dir <path>'
      exit 0
      ;;
    *) exit 2 ;;
  esac
done
[[ -n "\$install_dir" ]] || exit 3
EOF

  case "$mode" in
    good)
      cat >>"$path" <<EOF
mkdir -p "\$install_dir"
printf '%s' '$payload_b64' | base64 -d >"\$install_dir/agy"
chmod 0755 "\$install_dir/agy"
EOF
      ;;
    wrong-location)
      cat >>"$path" <<EOF
mkdir -p "\$install_dir"
printf '%s' '$payload_b64' | base64 -d >"\$install_dir/not-agy"
chmod 0755 "\$install_dir/not-agy"
EOF
      ;;
    fail)
      echo 'exit 42' >>"$path"
      ;;
    *) fail "unsupported installer fixture mode: $mode" ;;
  esac
  chmod 0755 "$path"
}

write_evidence() {
  local installer="$1"
  local payload="$2"
  local version="$3"
  local installer_sha_override="${4:-}"
  local binary_sha_override="${5:-}"
  local installer_sha binary_sha
  installer_sha="${installer_sha_override:-$(sha256sum "$installer" | awk '{print $1}')}"
  binary_sha="${binary_sha_override:-$(sha256sum "$payload" | awk '{print $1}')}"

  jq -n \
    --arg installer_sha "$installer_sha" \
    --arg binary_sha "$binary_sha" \
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
    }' >"$REMOTE_DEV_ANTIGRAVITY_EVIDENCE"
}

install_fixture() {
  local installer="$1"
  export REMOTE_DEV_ANTIGRAVITY_INSTALLER_FIXTURE="$installer"
  bash "$MANAGER" install --yes
}

reset_runtime
payload_v1="$temporary/payload-v1"
installer_v1="$temporary/installer-v1.sh"
make_payload "$payload_v1" '1.0.0-fixture'
make_installer "$installer_v1" "$payload_v1"
write_evidence "$installer_v1" "$payload_v1" '1.0.0-fixture'

# Explicit cancellation happens before the fixture is opened or copied.
export REMOTE_DEV_ANTIGRAVITY_INSTALLER_FIXTURE="$temporary/does-not-exist"
export REMOTE_DEV_ANTIGRAVITY_TEST_CONFIRM=n
bash "$MANAGER" install
test ! -e "$REMOTE_DEV_ANTIGRAVITY_BIN_DIR/agy" || fail "cancelled installation created a binary"
unset REMOTE_DEV_ANTIGRAVITY_TEST_CONFIRM

install_fixture "$installer_v1"
test -x "$REMOTE_DEV_ANTIGRAVITY_BIN_DIR/agy" || fail "first installation did not create the executable"
test "$(stat -c '%a' "$REMOTE_DEV_ANTIGRAVITY_BIN_DIR/agy")" = 700 || fail "installed executable permissions are not 700"
test "$(stat -c '%a' "$REMOTE_DEV_ANTIGRAVITY_STATE_DIR/install.json")" = 600 || fail "install manifest permissions are not 600"
test "$(bash "$MANAGER" status)" = '1.0.0-fixture' || fail "installed version was not detected"
test "$(bash "$MANAGER" status --menu)" = 'Antigravity: 1.0.0-fixture (runtime installed)' || fail "menu status is incorrect"

# Launcher preserves literal arguments, disables auto-update and re-hardens state.
secure_marker="$temporary/secure-called"
secure_script="$temporary/secure-state"
cat >"$secure_script" <<EOF
#!/usr/bin/env bash
set -euo pipefail
touch '$secure_marker'
EOF
chmod 0755 "$secure_script"
export REMOTE_DEV_SECURE_STATE="$secure_script"
export REMOTE_DEV_TEST_ARGS_FILE="$temporary/args.log"
export REMOTE_DEV_TEST_EXIT_CODE=0
pwned="$temporary/pwned"
bash "$RUNNER" 'literal space' "\$(touch $pwned)" ';echo injected'
test -f "$secure_marker" || fail "launcher did not harden state after exit"
test ! -e "$pwned" || fail "launcher evaluated an argument as shell code"
mapfile -t recorded_args <"$REMOTE_DEV_TEST_ARGS_FILE"
test "${recorded_args[0]}" = 'literal space' || fail "first launcher argument changed"
test "${recorded_args[1]}" = "\$(touch $pwned)" || fail "second launcher argument changed"
test "${recorded_args[2]}" = ';echo injected' || fail "third launcher argument changed"

# The official process exit status is preserved.
export REMOTE_DEV_TEST_EXIT_CODE=23
set +e
bash "$RUNNER" >/dev/null 2>&1
runner_status=$?
set -e
test "$runner_status" = 23 || fail "launcher did not preserve the official CLI exit status"
unset REMOTE_DEV_TEST_EXIT_CODE

# A missing installation never starts a download.
mv "$REMOTE_DEV_ANTIGRAVITY_BIN_DIR/agy" "$temporary/saved-agy"
expect_failure bash "$RUNNER" >/dev/null 2>&1
mv "$temporary/saved-agy" "$REMOTE_DEV_ANTIGRAVITY_BIN_DIR/agy"

# Failed update leaves the previously working executable and manifest untouched.
old_binary_sha="$(sha256sum "$REMOTE_DEV_ANTIGRAVITY_BIN_DIR/agy" | awk '{print $1}')"
old_manifest_sha="$(sha256sum "$REMOTE_DEV_ANTIGRAVITY_STATE_DIR/install.json" | awk '{print $1}')"
payload_v2="$temporary/payload-v2"
installer_fail="$temporary/installer-fail.sh"
make_payload "$payload_v2" '2.0.0-fixture'
make_installer "$installer_fail" "$payload_v2" fail
write_evidence "$installer_fail" "$payload_v2" '2.0.0-fixture'
export REMOTE_DEV_ANTIGRAVITY_INSTALLER_FIXTURE="$installer_fail"
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
test "$(sha256sum "$REMOTE_DEV_ANTIGRAVITY_BIN_DIR/agy" | awk '{print $1}')" = "$old_binary_sha" || fail "failed update replaced the working executable"
test "$(sha256sum "$REMOTE_DEV_ANTIGRAVITY_STATE_DIR/install.json" | awk '{print $1}')" = "$old_manifest_sha" || fail "failed update replaced the working manifest"

# A reviewed newer fixture updates atomically and refreshes the manifest.
installer_v2="$temporary/installer-v2.sh"
make_installer "$installer_v2" "$payload_v2"
write_evidence "$installer_v2" "$payload_v2" '2.0.0-fixture'
export REMOTE_DEV_ANTIGRAVITY_INSTALLER_FIXTURE="$installer_v2"
bash "$MANAGER" update --yes
test "$(bash "$MANAGER" status)" = '2.0.0-fixture' || fail "successful update did not activate the reviewed version"
test "$(jq -r '.version' "$REMOTE_DEV_ANTIGRAVITY_STATE_DIR/install.json")" = '2.0.0-fixture' || fail "successful update did not refresh the manifest"

# Installer bytes are approved before Bash executes them.
reset_runtime
malicious_marker="$temporary/malicious-installer-ran"
malicious_installer="$temporary/malicious-installer.sh"
make_installer "$malicious_installer" "$payload_v1" good "$malicious_marker"
write_evidence "$malicious_installer" "$payload_v1" '1.0.0-fixture' "$(printf '0%.0s' {1..64})"
export REMOTE_DEV_ANTIGRAVITY_INSTALLER_FIXTURE="$malicious_installer"
expect_failure bash "$MANAGER" install --yes >/dev/null 2>&1
test ! -e "$malicious_marker" || fail "unapproved installer bytes were executed"

# Payload bytes are approved before --version or any other invocation.
reset_runtime
payload_marker="$temporary/unapproved-payload-ran"
payload_malicious="$temporary/payload-malicious"
installer_payload_mismatch="$temporary/installer-payload-mismatch.sh"
make_payload "$payload_malicious" '3.0.0-fixture' "touch '$payload_marker'"
make_installer "$installer_payload_mismatch" "$payload_malicious"
write_evidence "$installer_payload_mismatch" "$payload_malicious" '3.0.0-fixture' '' "$(printf 'f%.0s' {1..64})"
export REMOTE_DEV_ANTIGRAVITY_INSTALLER_FIXTURE="$installer_payload_mismatch"
expect_failure bash "$MANAGER" install --yes >/dev/null 2>&1
test ! -e "$payload_marker" || fail "unapproved payload was invoked"
test ! -e "$REMOTE_DEV_ANTIGRAVITY_BIN_DIR/agy" || fail "unapproved payload reached the final binary path"

# Unexpected package layout and malformed version output both fail closed.
reset_runtime
installer_wrong_location="$temporary/installer-wrong-location.sh"
make_installer "$installer_wrong_location" "$payload_v1" wrong-location
write_evidence "$installer_wrong_location" "$payload_v1" '1.0.0-fixture'
export REMOTE_DEV_ANTIGRAVITY_INSTALLER_FIXTURE="$installer_wrong_location"
expect_failure bash "$MANAGER" install --yes >/dev/null 2>&1
test ! -e "$REMOTE_DEV_ANTIGRAVITY_BIN_DIR/agy" || fail "wrong installer layout reached the final path"

reset_runtime
payload_malformed="$temporary/payload-malformed"
installer_malformed="$temporary/installer-malformed.sh"
make_payload "$payload_malformed" 'not-a-version'
make_installer "$installer_malformed" "$payload_malformed"
write_evidence "$installer_malformed" "$payload_malformed" '4.0.0-fixture'
export REMOTE_DEV_ANTIGRAVITY_INSTALLER_FIXTURE="$installer_malformed"
expect_failure bash "$MANAGER" install --yes >/dev/null 2>&1
test ! -e "$REMOTE_DEV_ANTIGRAVITY_BIN_DIR/agy" || fail "malformed version payload reached the final path"

printf 'Optional Antigravity runtime regressions: OK\n'
