#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANAGER_SOURCE="$ROOT/scripts/remote-dev-antigravity.sh"

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
harness="$temporary/harness"
test_bin="$temporary/test-bin"
mkdir -p "$harness" "$test_bin"
MANAGER="$harness/remote-dev-antigravity"
PATHS_LIB="$harness/antigravity-paths.sh"
RUNTIME_LIB="$harness/remote-dev-runtime.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
expect_failure() { if "$@"; then fail "command unexpectedly succeeded: $*"; fi; }

cat >"$RUNTIME_LIB" <<'EOF'
remote_dev_resolve_role() {
  case "${REMOTE_DEV_ROLE:-}" in
    antigravity) printf '%s\n' antigravity ;;
    *) return 2 ;;
  esac
}
EOF
chmod 0644 "$RUNTIME_LIB"

python3 - "$MANAGER_SOURCE" "$MANAGER" "$PATHS_LIB" "$RUNTIME_LIB" <<'PY'
from pathlib import Path
import shlex
import sys
source, destination, paths_lib, runtime_lib = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
replacements = {
    "readonly paths_lib=/usr/local/lib/remote-dev/antigravity-paths.sh":
        f"readonly paths_lib={shlex.quote(str(paths_lib))}",
    "readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh":
        f"readonly runtime_lib={shlex.quote(str(runtime_lib))}",
}
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit(f"missing fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$MANAGER"

cat >"$test_bin/curl" <<'CURL'
#!/usr/bin/env bash
set -euo pipefail
destination=""
while (( $# )); do
  case "$1" in
    --output|-o) destination="$2"; shift 2 ;;
    --write-out) shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$destination" ]]
if [[ -n "${REMOTE_DEV_TEST_CURL_CALLED:-}" ]]; then : >"$REMOTE_DEV_TEST_CURL_CALLED"; fi
cp -- "${REMOTE_DEV_TEST_INSTALLER:?}" "$destination"
printf '%s\n%s\n' \
  "${REMOTE_DEV_TEST_FINAL_URL:-https://antigravity.google/cli/install.sh}" \
  "${REMOTE_DEV_TEST_CONTENT_TYPE:-application/x-sh}"
CURL
chmod 0755 "$test_bin/curl"
export PATH="$test_bin:$PATH"
export REMOTE_DEV_ROLE=antigravity

reset_runtime() {
  rm -rf -- "$temporary/runtime"
  mkdir -p "$temporary/runtime/workspace"
  EVIDENCE="$temporary/runtime/evidence.json"
  BIN_DIR="$temporary/runtime/bin"
  STATE_DIR="$temporary/runtime/state"
  VENDOR_STATE_DIR="$temporary/runtime/vendor"
  BINARY="$BIN_DIR/agy"
  MANIFEST="$STATE_DIR/install.json"
  ROLLBACK_BINARY="$STATE_DIR/rollback/agy"
  ROLLBACK_MANIFEST="$STATE_DIR/rollback/install.json"
  cat >"$PATHS_LIB" <<EOF
readonly ANTIGRAVITY_EVIDENCE=$(printf '%q' "$EVIDENCE")
readonly ANTIGRAVITY_BIN_DIR=$(printf '%q' "$BIN_DIR")
readonly ANTIGRAVITY_BINARY=$(printf '%q' "$BINARY")
readonly ANTIGRAVITY_STATE_DIR=$(printf '%q' "$STATE_DIR")
readonly ANTIGRAVITY_MANIFEST=$(printf '%q' "$MANIFEST")
readonly ANTIGRAVITY_VENDOR_STATE_DIR=$(printf '%q' "$VENDOR_STATE_DIR")
EOF
  chmod 0444 "$PATHS_LIB"
}

make_payload() {
  local destination="$1"
  local version="$2"
  local source="$temporary/payload.c"
  cat >"$source" <<EOF
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
  if (argc > 1 && strcmp(argv[1], "--version") == 0) { puts("agy $version"); return 0; }
  if (argc > 1 && strcmp(argv[1], "--help") == 0) { puts("Usage: agy [args]"); return 0; }
  const char *marker = getenv("REMOTE_DEV_TEST_RUN_MARKER");
  if (marker) { FILE *f = fopen(marker, "w"); if (f) { fputs(getenv("AGY_CLI_DISABLE_AUTO_UPDATE") ?: "unset", f); fclose(f); } }
  return 0;
}
EOF
  gcc -O2 "$source" -o "$destination"
  truncate -s 2097152 "$destination"
  chmod 0755 "$destination"
}

make_installer() {
  local destination="$1"
  local payload="$2"
  local mode="${3:-good}"
  cat >"$destination" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\${1:-}" == --help ]]; then
  printf '%s\n' 'Usage: install.sh --dir <path>'
  exit 0
fi
[[ "\${1:-}" == --dir && -n "\${2:-}" ]] || exit 2
case '$mode' in
  good)
    mkdir -p "\$2"
    cp -- '$payload' "\$2/agy"
    chmod 0755 "\$2/agy"
    ;;
  wrong-location)
    mkdir -p "\$2"
    cp -- '$payload' "\$2/not-agy"
    ;;
  fail) exit 42 ;;
esac
EOF
  chmod 0755 "$destination"
}

write_review_evidence() {
  local payload="$1"
  local version="$2"
  jq -n \
    --arg version "$version" \
    --arg sha "$(sha256sum "$payload" | awk '{print $1}')" \
    --argjson size "$(stat -c '%s' "$payload")" \
    '{schema_version:2, installer:{sha256:("0"*64),size:1,content_type:"application/x-sh"}, installed_binary:{version:$version,sha256:$sha,size:$size},blocking_findings:[]}' \
    >"$EVIDENCE"
}

install_from() {
  export REMOTE_DEV_TEST_INSTALLER="$1"
  bash "$MANAGER" install --yes >/dev/null
}
update_from() {
  export REMOTE_DEV_TEST_INSTALLER="$1"
  bash "$MANAGER" update --yes >/dev/null
}

reset_runtime
payload_v1="$temporary/agy-v1"
payload_v2="$temporary/agy-v2"
installer_v1="$temporary/install-v1.sh"
installer_v2="$temporary/install-v2.sh"
installer_fail="$temporary/install-fail.sh"
installer_wrong="$temporary/install-wrong.sh"
make_payload "$payload_v1" 1.0.0
make_payload "$payload_v2" 2.0.0
make_installer "$installer_v1" "$payload_v1"
make_installer "$installer_v2" "$payload_v2"
make_installer "$installer_fail" "$payload_v2" fail
make_installer "$installer_wrong" "$payload_v2" wrong-location
write_review_evidence "$payload_v1" 1.0.0

# Confirmation is required before the official endpoint is contacted.
export REMOTE_DEV_TEST_INSTALLER="$installer_v1"
export REMOTE_DEV_TEST_CURL_CALLED="$temporary/curl-before-confirmation"
expect_failure bash "$MANAGER" install </dev/null >/dev/null 2>&1
test ! -e "$REMOTE_DEV_TEST_CURL_CALLED" || fail "installation contacted Google before confirmation"
unset REMOTE_DEV_TEST_CURL_CALLED

# A reviewed version installs through the official-source flow and records local integrity.
install_from "$installer_v1"
test "$(bash "$MANAGER" status)" = 1.0.0 || fail "plain reviewed status changed"
test "$(bash "$MANAGER" status --menu)" = 'Antigravity: 1.0.0 (official, reviewed)' \
  || fail "reviewed menu status is incorrect"
test "$(stat -c '%a' "$BINARY")" = 700 || fail "binary mode is not 700"
test "$(stat -c '%a' "$MANIFEST")" = 600 || fail "manifest mode is not 600"
jq -e '.schema_version == 2 and .source == "official-google-installer" and .automatic_updates_disabled == true' \
  "$MANIFEST" >/dev/null || fail "new manifest contract was not recorded"
export REMOTE_DEV_TEST_CURL_CALLED="$temporary/curl-during-status"
bash "$MANAGER" status >/dev/null
test ! -e "$REMOTE_DEV_TEST_CURL_CALLED" || fail "normal status contacted the installer endpoint"
unset REMOTE_DEV_TEST_CURL_CALLED

# A newer official payload remains usable even when image review evidence is older.
update_from "$installer_v2"
test "$(bash "$MANAGER" status)" = 2.0.0 || fail "review-pending version was blocked"
test "$(bash "$MANAGER" status --menu)" = 'Antigravity: 2.0.0 (official, review pending)' \
  || fail "review-pending menu status is incorrect"
test -x "$ROLLBACK_BINARY" || fail "update did not retain a rollback executable"
test "$(jq -r .version "$ROLLBACK_MANIFEST")" = 1.0.0 || fail "rollback manifest has wrong version"

# Normal launch integrity checks do not contact the installer and local tampering is blocked.
original_sha="$(sha256sum "$BINARY" | awk '{print $1}')"
printf x >>"$BINARY"
set +e
bash "$MANAGER" status >/dev/null 2>&1
status=$?
set -e
test "$status" = 3 || fail "tampered binary did not return status 3"
cp -- "$payload_v2" "$BINARY"
chmod 0700 "$BINARY"
test "$(sha256sum "$BINARY" | awk '{print $1}')" = "$original_sha" || fail "fixture repair changed payload identity"

# Rollback restores the previous reviewed version and keeps the newer copy as the next rollback.
bash "$MANAGER" rollback >/dev/null
test "$(bash "$MANAGER" status)" = 1.0.0 || fail "rollback did not restore v1"
test "$(jq -r .version "$ROLLBACK_MANIFEST")" = 2.0.0 || fail "rollback did not preserve v2"

# Failed and malformed updates leave the active installation untouched.
active_sha="$(sha256sum "$BINARY" | awk '{print $1}')"
export REMOTE_DEV_TEST_INSTALLER="$installer_fail"
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
test "$(sha256sum "$BINARY" | awk '{print $1}')" = "$active_sha" || fail "failed update replaced active binary"
export REMOTE_DEV_TEST_INSTALLER="$installer_wrong"
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
test "$(sha256sum "$BINARY" | awk '{print $1}')" = "$active_sha" || fail "wrong-layout update replaced active binary"

# Same-origin redirects remain compatible and their effective URL is recorded.
export REMOTE_DEV_TEST_INSTALLER="$installer_v2"
export REMOTE_DEV_TEST_FINAL_URL=https://antigravity.google/cli/releases/current-install.sh
bash "$MANAGER" update --yes >/dev/null
test "$(jq -r .installer_final_url "$MANIFEST")" = "$REMOTE_DEV_TEST_FINAL_URL" \
  || fail "same-origin final installer URL was not recorded"
unset REMOTE_DEV_TEST_FINAL_URL

# Cross-origin redirects and unexpected content types are rejected before execution.
execution_marker="$temporary/executed"
cat >"$temporary/marked-installer.sh" <<EOF
#!/usr/bin/env bash
touch '$execution_marker'
exit 0
EOF
chmod 0755 "$temporary/marked-installer.sh"
export REMOTE_DEV_TEST_INSTALLER="$temporary/marked-installer.sh"
export REMOTE_DEV_TEST_FINAL_URL=https://evil.example/install.sh
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
test ! -e "$execution_marker" || fail "redirected installer executed"
unset REMOTE_DEV_TEST_FINAL_URL
export REMOTE_DEV_TEST_CONTENT_TYPE=text/html
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
test ! -e "$execution_marker" || fail "HTML installer executed"
unset REMOTE_DEV_TEST_CONTENT_TYPE

# Existing schema-1 manifests remain valid across image updates.
cp -- "$payload_v2" "$BINARY"
chmod 0700 "$BINARY"
jq -n \
  --arg version 2.0.0 \
  --arg sha "$(sha256sum "$payload_v2" | awk '{print $1}')" \
  --argjson size "$(stat -c '%s' "$payload_v2")" \
  '{schema_version:1,installed_at_utc:"legacy",version:$version,installer_url:"https://antigravity.google/cli/install.sh",installer_sha256:("0"*64),binary_sha256:$sha,binary_size:$size,runtime_installed:true,bundled_in_image:false}' \
  >"$MANIFEST"
chmod 0600 "$MANIFEST"
test "$(bash "$MANAGER" status)" = 2.0.0 || fail "legacy manifest was invalidated"

# Review evidence can disappear without disabling an intact local install.
rm -f -- "$EVIDENCE"
test "$(bash "$MANAGER" status --menu)" = 'Antigravity: 2.0.0 (official, review unavailable)' \
  || fail "missing review evidence blocked an intact installation"

echo "Antigravity official-source availability regressions: OK"
