#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANAGER_SOURCE="$ROOT/scripts/remote-dev-antigravity.sh"
RUNTIME_SOURCE="$ROOT/scripts/lib/remote-dev-runtime.sh"
ANTIGRAVITY_LIB_SOURCE="$ROOT/scripts/lib/antigravity-runtime"

temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
harness="$temporary/harness"
test_bin="$temporary/test-bin"
MANAGER="$harness/remote-dev-antigravity"
RUNTIME_LIB="$harness/remote-dev-runtime.sh"
PATHS_LIB="$harness/antigravity-paths.sh"
ANTIGRAVITY_LIB_DIR="$harness/antigravity-runtime"
mkdir -p "$harness" "$test_bin"
cp -R -- "$ANTIGRAVITY_LIB_SOURCE" "$ANTIGRAVITY_LIB_DIR"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

# Ignore ~/.curlrc and retain every fixed-origin transport bound even if the
# invocation is reformatted or its flags are reordered.
curl_invocation="$(awk '
  index($0, "if ! curl \\") { capture=1 }
  capture { print }
  capture && index($0, "--output \"$hop_body\"") { exit }
' "$ANTIGRAVITY_LIB_SOURCE/installer.sh")"
[[ -n "$curl_invocation" ]] \
  || fail "could not locate the official installer curl invocation"
for required in \
  --disable \
  "--proto '=https'" \
  "--proto-redir '=https'" \
  --tlsv1.2 \
  --max-filesize \
  --max-redirs; do
  grep -Fq -- "$required" <<<"$curl_invocation" \
    || fail "official installer download is missing the $required hardening flag"
done

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
chmod 0755 "$MANAGER"

cat >"$test_bin/curl" <<'CURL_FIXTURE'
#!/usr/bin/env bash
set -euo pipefail
output=""
while (( $# )); do
  case "$1" in
    --output|-o)
      output="$2"
      shift 2
      ;;
    --write-out)
      shift 2
      ;;
    *) shift ;;
  esac
done
[[ -n "$output" ]] || exit 2
[[ -z "${REMOTE_DEV_TEST_CURL_MARKER:-}" ]] || : >"$REMOTE_DEV_TEST_CURL_MARKER"
cp -- "${REMOTE_DEV_TEST_INSTALLER_FIXTURE:?}" "$output"
printf '%s\n%s\n%s\n%s\n' \
  '200' \
  'https://antigravity.google/cli/install.sh' \
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

export PATH="$test_bin:$PATH"
export REMOTE_DEV_ROLE=antigravity
export REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1

EVIDENCE="$temporary/evidence.json"
BIN_DIR="$temporary/runtime/bin"
BINARY="$BIN_DIR/agy"
STATE_DIR="$temporary/runtime/state"
MANIFEST="$STATE_DIR/install.json"
VENDOR_STATE_DIR="$temporary/runtime/vendor"
{
  printf 'readonly ANTIGRAVITY_EVIDENCE=%q\n' "$EVIDENCE"
  printf 'readonly ANTIGRAVITY_BIN_DIR=%q\n' "$BIN_DIR"
  printf 'readonly ANTIGRAVITY_BINARY=%q\n' "$BINARY"
  printf 'readonly ANTIGRAVITY_STATE_DIR=%q\n' "$STATE_DIR"
  printf 'readonly ANTIGRAVITY_MANIFEST=%q\n' "$MANIFEST"
  printf 'readonly ANTIGRAVITY_VENDOR_STATE_DIR=%q\n' "$VENDOR_STATE_DIR"
} >"$PATHS_LIB"
chmod 0444 "$PATHS_LIB"

make_payload() {
  local path="$1"
  local version="$2"
  cat >"$path" <<EOF_PAYLOAD
#!/usr/bin/env bash
set -euo pipefail
case "\${1:-}" in
  --version) printf '%s\\n' '$version' ;;
  --help) printf '%s\\n' 'Usage: agy' ;;
  *) exit 0 ;;
esac
EOF_PAYLOAD
  chmod 0755 "$path"
}

make_installer() {
  local path="$1"
  local payload="$2"
  local encoded
  encoded="$(base64 -w0 "$payload")"
  cat >"$path" <<EOF_INSTALLER
#!/usr/bin/env bash
set -euo pipefail
if [[ "\${1:-}" == --help ]]; then
  printf '%s\\n' 'Usage: install.sh --dir <path>'
  exit 0
fi
[[ "\${1:-}" == --dir && -n "\${2:-}" ]] || exit 2
mkdir -p "\$2"
printf '%s' '$encoded' | base64 -d >"\$2/agy"
chmod 0700 "\$2/agy"
EOF_INSTALLER
  chmod 0755 "$path"
}

write_evidence() {
  local installer="$1"
  local payload="$2"
  local version="$3"
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

payload="$temporary/payload"
installer="$temporary/installer"
make_payload "$payload" '1.0.0'
make_installer "$installer" "$payload"
write_evidence "$installer" "$payload" '1.0.0'
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer"
bash "$MANAGER" install --yes >/dev/null

# An orphaned manifest is damaged state. First-install must reject it before
# download, while the explicit update path replaces it from the official source.
rm -f "$BINARY"
export REMOTE_DEV_TEST_CURL_MARKER="$temporary/install-curl"
rm -f "$REMOTE_DEV_TEST_CURL_MARKER"
install_output=""
install_status=0
install_output="$(bash "$MANAGER" install --yes 2>&1)" || install_status=$?
(( install_status != 0 )) || fail "install accepted existing damaged state"
grep -Fq 'installation state already exists' <<<"$install_output" \
  || fail "install rejected damaged state for an unexpected reason: $install_output"
test ! -e "$REMOTE_DEV_TEST_CURL_MARKER" \
  || fail "install downloaded before rejecting existing damaged state"

export REMOTE_DEV_TEST_CURL_MARKER="$temporary/update-curl"
rm -f "$REMOTE_DEV_TEST_CURL_MARKER"
bash "$MANAGER" update --yes >/dev/null
test -x "$BINARY" || fail "update did not restore an orphaned manifest installation"
test -f "$MANIFEST" || fail "update did not preserve a repaired manifest"
test -e "$REMOTE_DEV_TEST_CURL_MARKER" \
  || fail "repair update did not use the explicit official-source flow"
unset REMOTE_DEV_TEST_CURL_MARKER

# An orphaned executable remains damaged during passive status. Only the same
# explicit update command may recreate its missing manifest.
rm -f "$MANIFEST"
status_output=""
status_status=0
status_output="$(bash "$MANAGER" status --menu 2>&1)" || status_status=$?
test "$status_status" = 3 || fail "status did not report a missing manifest as damaged"
grep -Fq 'damaged or locally modified' <<<"$status_output" \
  || fail "status reported an unexpected missing-manifest state: $status_output"
test ! -e "$MANIFEST" || fail "passive status recreated the missing manifest"

bash "$MANAGER" update --yes >/dev/null
test -x "$BINARY" || fail "update did not preserve the repaired executable"
test -f "$MANIFEST" || fail "update did not restore a missing manifest"

echo 'Antigravity partial-repair and download-hardening regressions: OK'
