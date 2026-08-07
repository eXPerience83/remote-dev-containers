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

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
expect_failure() { if "$@"; then fail "command unexpectedly succeeded: $*"; fi; }

for forbidden in \
  REMOTE_DEV_ANTIGRAVITY_TESTING \
  REMOTE_DEV_ANTIGRAVITY_EVIDENCE \
  REMOTE_DEV_ANTIGRAVITY_BIN_DIR \
  REMOTE_DEV_ANTIGRAVITY_STATE_DIR \
  REMOTE_DEV_ANTIGRAVITY_VENDOR_STATE_DIR; do
  grep -Fq "$forbidden" "$MANAGER_SOURCE" "$ANTIGRAVITY_LIB_SOURCE"/*.sh \
    && fail "production manager exposes test override: $forbidden"
done
grep -Fq 'source == "official-google-installer"' "$ANTIGRAVITY_LIB_SOURCE/manifest.sh" \
  || fail "schema-2 manifest does not require official-source provenance"
grep -Fq 'safe_official_url "$manifest_installer_final_url"' "$ANTIGRAVITY_LIB_SOURCE/manifest.sh" \
  || fail "local manifest does not validate the final official origin"
for validation_source in integrity.sh installer.sh; do
  grep -Fq 'AGY_CLI_DISABLE_AUTO_UPDATE=true' "$ANTIGRAVITY_LIB_SOURCE/$validation_source" \
    || fail "$validation_source does not disable vendor auto-update during changed-code validation"
done
grep -Fq -- '--no-new-privs' "$ANTIGRAVITY_LIB_SOURCE/integrity.sh" \
  || fail "official installer sandbox does not set no-new-privileges"
grep -Fq 'cd -- "$working_directory"' "$ANTIGRAVITY_LIB_SOURCE/integrity.sh" \
  || fail "official installer execution does not enter its isolated working directory"
grep -Fq 'local inspection_dir="$cleanup_root/inspection"' "$ANTIGRAVITY_LIB_SOURCE/commands.sh" \
  || fail "inspection captures are not outside the vendor-writable sandbox"

cp -- "$RUNTIME_SOURCE" "$RUNTIME_LIB"
chmod 0444 "$RUNTIME_LIB"
python3 - "$MANAGER_SOURCE" "$MANAGER" "$PATHS_LIB" "$RUNTIME_LIB" "$ANTIGRAVITY_LIB_DIR" <<'PY'
from pathlib import Path
import shlex
import sys
source, destination, paths_lib, runtime_lib, antigravity_lib_dir = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
for old, new in {
    "readonly paths_lib=/usr/local/lib/remote-dev/antigravity-paths.sh":
        f"readonly paths_lib={shlex.quote(str(paths_lib))}",
    "readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh":
        f"readonly runtime_lib={shlex.quote(str(runtime_lib))}",
    "readonly antigravity_lib_dir=/usr/local/lib/remote-dev/antigravity-runtime":
        f"readonly antigravity_lib_dir={shlex.quote(str(antigravity_lib_dir))}",
}.items():
    if text.count(old) != 1:
        raise SystemExit(f"missing fixture anchor: {old}")
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
    --output|-o) output="$2"; shift 2 ;;
    --write-out) shift 2 ;;
    *) shift ;;
  esac
done
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

reset_runtime() {
  rm -rf -- "$temporary/runtime"
  mkdir -p "$temporary/runtime/workspace"
  EVIDENCE="$temporary/runtime/evidence.json"
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
}

make_payload() {
  local path="$1" version="$2"
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
  local path="$1" payload="$2" prelude="${3:-}"
  local encoded
  encoded="$(base64 -w0 "$payload")"
  cat >"$path" <<EOF_INSTALLER
#!/usr/bin/env bash
set -euo pipefail
$prelude
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

make_large_installer() {
  local path="$1"
  cat >"$path" <<'EOF_INSTALLER'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --help ]]; then
  printf '%s\n' 'Usage: install.sh --dir <path>'
  exit 0
fi
[[ "${1:-}" == --dir && -n "${2:-}" ]] || exit 2
mkdir -p "$2"
cat >"$2/agy" <<'EOF_PAYLOAD'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --version) printf '%s\n' '2.1.0' ;;
  --help) printf '%s\n' 'Usage: agy' ;;
  *) exit 0 ;;
esac
#
EOF_PAYLOAD
head -c $((3 * 1024 * 1024)) /dev/zero | tr '\0' '#' >>"$2/agy"
printf '\n' >>"$2/agy"
chmod 0700 "$2/agy"
EOF_INSTALLER
  chmod 0755 "$path"
}

write_evidence() {
  local installer="$1" payload="$2" version="$3"
  jq -n \
    --arg isha "$(sha256sum "$installer" | awk '{print $1}')" \
    --arg bsha "$(sha256sum "$payload" | awk '{print $1}')" \
    --arg version "$version" \
    --argjson isize "$(stat -c '%s' "$installer")" \
    --argjson bsize "$(stat -c '%s' "$payload")" \
    '{schema_version:2,
      installer:{official_url:"https://antigravity.google/cli/install.sh",sha256:$isha,size:$isize},
      installed_binary:{sha256:$bsha,size:$bsize,version:$version},
      blocking_findings:[]}' >"$EVIDENCE"
}

reset_runtime
payload_v1="$temporary/payload-v1"
installer_v1="$temporary/installer-v1"
make_payload "$payload_v1" '1.0.0'
make_installer "$installer_v1" "$payload_v1"
write_evidence "$installer_v1" "$payload_v1" '1.0.0'
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_v1"
bash "$MANAGER" install --yes >/dev/null

# Independent executable, manifest and permission tampering is rejected.
printf '# changed\n' >>"$BINARY"
set +e
output="$(bash "$MANAGER" status --menu 2>&1)"; status=$?
set -e
test "$status" = 3 || fail "binary tamper returned $status"
grep -Fq 'damaged or locally modified' <<<"$output" || fail "binary tamper status is unclear"
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_v1"
bash "$MANAGER" update --yes >/dev/null
jq '.version = "9.9.9"' "$MANIFEST" >"$MANIFEST.changed"
mv "$MANIFEST.changed" "$MANIFEST"
chmod 0600 "$MANIFEST"
expect_failure bash "$MANAGER" status >/dev/null 2>&1
bash "$MANAGER" update --yes >/dev/null
chmod 0644 "$MANIFEST"
expect_failure bash "$MANAGER" status >/dev/null 2>&1
chmod 0600 "$MANIFEST"

# Symlinks at either trust-record path are never followed.
mv "$BINARY" "$temporary/real-binary"
ln -s "$temporary/real-binary" "$BINARY"
expect_failure bash "$MANAGER" status >/dev/null 2>&1
rm -f "$BINARY"
mv "$temporary/real-binary" "$BINARY"
mv "$MANIFEST" "$temporary/real-manifest"
ln -s "$temporary/real-manifest" "$MANIFEST"
expect_failure bash "$MANAGER" status >/dev/null 2>&1
rm -f "$MANIFEST"
mv "$temporary/real-manifest" "$MANIFEST"

# Legacy schema-1 installs remain admitted and become review-pending when image evidence advances.
legacy_sha="$(sha256sum "$BINARY" | awk '{print $1}')"
legacy_size="$(stat -c '%s' "$BINARY")"
legacy_installer_sha="$(sha256sum "$installer_v1" | awk '{print $1}')"
jq -n \
  --arg version '1.0.0' \
  --arg installer_sha "$legacy_installer_sha" \
  --arg binary_sha "$legacy_sha" \
  --argjson binary_size "$legacy_size" \
  '{schema_version:1,version:$version,
    installer_url:"https://antigravity.google/cli/install.sh",
    installer_sha256:$installer_sha,
    binary_sha256:$binary_sha,binary_size:$binary_size,
    runtime_installed:true,bundled_in_image:false}' >"$MANIFEST"
chmod 0600 "$MANIFEST"
payload_v2="$temporary/payload-v2"
installer_v2="$temporary/installer-v2"
make_payload "$payload_v2" '2.0.0'
make_installer "$installer_v2" "$payload_v2"
write_evidence "$installer_v2" "$payload_v2" '2.0.0'
test "$(bash "$MANAGER" status --menu)" = \
  'Antigravity: 1.0.0 (official source; Remote Dev review pending)' \
  || fail "legacy reviewed installation did not survive evidence advancement"

# A publication failure after replacing the binary restores the previous pair.
old_binary_sha="$(sha256sum "$BINARY" | awk '{print $1}')"
old_manifest_sha="$(sha256sum "$MANIFEST" | awk '{print $1}')"
real_mv="$(command -v mv)"
cat >"$test_bin/mv" <<EOF_MV
#!/usr/bin/env bash
set -euo pipefail
if [[ "\${@: -1}" == "\${REMOTE_DEV_TEST_FAIL_MV_DEST:-}" ]]; then
  exit 77
fi
exec '$real_mv' "\$@"
EOF_MV
chmod 0755 "$test_bin/mv"
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_v2"
export REMOTE_DEV_TEST_FAIL_MV_DEST="$MANIFEST"
expect_failure bash "$MANAGER" update --yes >/dev/null 2>&1
unset REMOTE_DEV_TEST_FAIL_MV_DEST
test "$(sha256sum "$BINARY" | awk '{print $1}')" = "$old_binary_sha" || fail "interrupted publish did not restore executable"
test "$(sha256sum "$MANIFEST" | awk '{print $1}')" = "$old_manifest_sha" || fail "interrupted publish did not restore manifest"
rm -f "$test_bin/mv"

# Changed installer code starts from the isolated HOME rather than the caller's cwd.
caller_cwd="$temporary/caller-cwd"
mkdir -m 0755 "$caller_cwd"
printf '%s\n' caller-data >"$caller_cwd/cwd-readable"
chmod 0644 "$caller_cwd/cwd-readable"
installer_cwd="$temporary/installer-cwd"
make_installer "$installer_cwd" "$payload_v2" \
  'if [[ -r ./cwd-readable ]]; then echo caller-cwd-visible >&2; exit 88; fi'
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_cwd"
(
  cd "$caller_cwd"
  bash "$MANAGER" update --yes >/dev/null
) || fail "installer inherited the caller working directory"

# The installer can write a candidate larger than the narrow stdout/stderr
# capture limit without inheriting that limit as its payload maximum.
installer_large="$temporary/installer-large"
make_large_installer "$installer_large"
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_large"
bash "$MANAGER" update --yes >/dev/null \
  || fail "installer could not write a supported candidate above the capture limit"
test "$(jq -r '.version' "$MANIFEST")" = 2.1.0 \
  || fail "large compatible candidate was not published"

# When tests execute as root, changed installer code runs as nobody, cannot read
# root-private state and cannot plant capture symlinks for later root opens.
if [[ "$(id -u)" == 0 ]]; then
  private_secret="$temporary/root-private-secret"
  forbidden_read_marker="$temporary/forbidden-read"
  forbidden_write_marker="$temporary/forbidden-write"
  printf '%s\n' secret >"$private_secret"
  chmod 0600 "$private_secret"
  installer_isolated="$temporary/installer-isolated"
  prelude="if [[ \"\${1:-}\" == --dir ]]; then ln -s '$private_secret' \"\$2/../inspection/readelf.out\" 2>/dev/null || true; fi; if cat '$private_secret' >/dev/null 2>&1; then touch '$forbidden_read_marker'; fi; touch '$forbidden_write_marker' 2>/dev/null || true"
  make_installer "$installer_isolated" "$payload_v2" "$prelude"
  export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_isolated"
  bash "$MANAGER" update --yes >/dev/null
  test ! -e "$forbidden_read_marker" || fail "installer read root-private state"
  test ! -e "$forbidden_write_marker" || fail "installer wrote outside its private staging subtree"
  test "$(<"$private_secret")" = secret || fail "root capture followed an installer-planted symlink"
fi

printf 'Antigravity admission and installer-isolation security regressions: OK\n'
