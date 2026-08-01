#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"

scratch="$(mktemp -d)"
trap 'rm -rf "${scratch:?}"' EXIT
fake_mise="$scratch/fake-mise"

cat > "$fake_mise" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--version" ]]; then
  printf '%s linux-x64 (test)\n' "$FAKE_MISE_VERSION"
  exit 0
fi

if [[ "$#" -ne 3 || "$1" != "lock" || "$2" != "--platform" || "$3" != "linux-x64,linux-arm64" ]]; then
  echo "unexpected fake mise arguments: $*" >&2
  exit 80
fi

[[ "$PWD" == */workspace ]] || { echo "lock did not run in isolated workspace: $PWD" >&2; exit 81; }
[[ "${MISE_SAFE:-}" == "1" ]] || { echo "MISE_SAFE was not forced" >&2; exit 82; }
[[ "${MISE_HTTP_TIMEOUT:-}" == "7s" ]] || { echo "HTTP timeout override was not preserved" >&2; exit 83; }
[[ -z "${MISE_ENV+x}" ]] || { echo "MISE_ENV leaked into regeneration" >&2; exit 84; }
[[ -z "${MISE_AQUA_REGISTRY_URL+x}" ]] || { echo "registry override leaked into regeneration" >&2; exit 85; }
[[ "${MISE_CACHE_DIR:-}" != "$FORBIDDEN_MISE_CACHE_DIR" ]] || { echo "caller cache directory was reused" >&2; exit 86; }
[[ -f "${MISE_GLOBAL_CONFIG_FILE:-}" && ! -s "$MISE_GLOBAL_CONFIG_FILE" ]] \
  || { echo "global config was not isolated" >&2; exit 87; }
for directory in MISE_CACHE_DIR MISE_CONFIG_DIR MISE_DATA_DIR MISE_SYSTEM_DIR MISE_TMP_DIR; do
  value="${!directory:-}"
  [[ -n "$value" && "$value" == */* ]] || { echo "$directory was not isolated" >&2; exit 88; }
done

printf '%s\n' "$(dirname "$MISE_CACHE_DIR")" > "$FAKE_SCRATCH_RECORD"
case "$FAKE_MISE_MODE" in
  success)
    printf '\n# fake regeneration marker\n' >> mise.lock
    ;;
  invalid)
    printf '%s\n' 'not valid toml = [' > mise.lock
    ;;
  fail)
    printf '%s\n' 'partial output' > mise.lock
    exit 42
    ;;
  *)
    echo "unknown FAKE_MISE_MODE: $FAKE_MISE_MODE" >&2
    exit 89
    ;;
esac
EOF
chmod 0755 "$fake_mise"

copy_fixture() {
  local destination="$1"
  mkdir -p "$destination/scripts" "$destination/third_party/components"
  cp \
    "$ROOT/versions.env" \
    "$ROOT/mise.toml" \
    "$ROOT/mise.lock" \
    "$destination/"
  cp \
    "$ROOT/scripts/regenerate-mise-lock.sh" \
    "$ROOT/scripts/validate-mise-lock.py" \
    "$ROOT/scripts/sync-python-runtime-notices.py" \
    "$ROOT/scripts/compact-python-runtime-notices.py" \
    "$destination/scripts/"
  cp -R \
    "$ROOT/third_party/components/python-build-standalone" \
    "$destination/third_party/components/"
}

assert_no_temp_lock() {
  local fixture_root="$1"
  local leftover=""
  leftover="$(find "$fixture_root" -maxdepth 1 -type f -name '.mise.lock.tmp.*' -print -quit)"
  if [[ -n "$leftover" ]]; then
    echo "ERROR: temporary lock replacement was not removed: $leftover" >&2
    exit 1
  fi
}

run_helper_with_path() {
  local fixture_root="$1"
  local mode="$2"
  local record="$3"
  local path_value="$4"
  local forbidden_cache="$scratch/forbidden-cache"
  mkdir -p "$forbidden_cache"

  env \
    PATH="$path_value" \
    FAKE_MISE_MODE="$mode" \
    FAKE_MISE_VERSION="$MISE_VERSION" \
    FAKE_SCRATCH_RECORD="$record" \
    FORBIDDEN_MISE_CACHE_DIR="$forbidden_cache" \
    MISE_AQUA_REGISTRY_URL="https://example.invalid/registry" \
    MISE_BIN="$fake_mise" \
    MISE_CACHE_DIR="$forbidden_cache" \
    MISE_ENV="unexpected-profile" \
    MISE_HTTP_TIMEOUT=7s \
    MISE_LOCK_TIMEOUT=5s \
    bash "$fixture_root/scripts/regenerate-mise-lock.sh"
}

run_helper() {
  run_helper_with_path "$1" "$2" "$3" "$PATH"
}

success_root="$scratch/success-repo"
success_record="$scratch/success-record"
copy_fixture "$success_root"
run_helper "$success_root" success "$success_record"
grep -Fq '# fake regeneration marker' "$success_root/mise.lock"
assert_no_temp_lock "$success_root"
success_scratch="$(cat "$success_record")"
[[ ! -e "$success_scratch" ]] || { echo "successful regeneration scratch was not removed" >&2; exit 1; }
echo "OK isolated successful regeneration"

invalid_root="$scratch/invalid-repo"
invalid_record="$scratch/invalid-record"
copy_fixture "$invalid_root"
if run_helper "$invalid_root" invalid "$invalid_record"; then
  echo "ERROR: invalid generated lock was accepted" >&2
  exit 1
fi
cmp -s "$ROOT/mise.lock" "$invalid_root/mise.lock" \
  || { echo "ERROR: invalid generated lock replaced the committed fixture" >&2; exit 1; }
assert_no_temp_lock "$invalid_root"
invalid_scratch="$(cat "$invalid_record")"
[[ ! -e "$invalid_scratch" ]] || { echo "invalid regeneration scratch was not removed" >&2; exit 1; }
echo "OK reject invalid generated lock without partial write"

failure_root="$scratch/failure-repo"
failure_record="$scratch/failure-record"
copy_fixture "$failure_root"
if run_helper "$failure_root" fail "$failure_record"; then
  echo "ERROR: failed mise command was treated as success" >&2
  exit 1
fi
cmp -s "$ROOT/mise.lock" "$failure_root/mise.lock" \
  || { echo "ERROR: failed regeneration replaced the committed fixture" >&2; exit 1; }
assert_no_temp_lock "$failure_root"
failure_scratch="$(cat "$failure_record")"
[[ ! -e "$failure_scratch" ]] || { echo "failed regeneration scratch was not removed" >&2; exit 1; }
echo "OK preserve lock after failed regeneration"

fake_tools="$scratch/fake-tools"
mkdir -p "$fake_tools"
cat > "$fake_tools/install" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
destination="${!#}"
printf '%s\n' 'partial replacement' > "$destination"
exit 43
EOF
chmod 0755 "$fake_tools/install"

install_failure_root="$scratch/install-failure-repo"
install_failure_record="$scratch/install-failure-record"
copy_fixture "$install_failure_root"
if run_helper_with_path \
  "$install_failure_root" \
  success \
  "$install_failure_record" \
  "$fake_tools:$PATH"; then
  echo "ERROR: failed replacement copy was treated as success" >&2
  exit 1
fi
cmp -s "$ROOT/mise.lock" "$install_failure_root/mise.lock" \
  || { echo "ERROR: failed replacement copy changed the committed fixture" >&2; exit 1; }
assert_no_temp_lock "$install_failure_root"
install_failure_scratch="$(cat "$install_failure_record")"
[[ ! -e "$install_failure_scratch" ]] || { echo "copy-failure scratch was not removed" >&2; exit 1; }
echo "OK preserve lock after replacement copy failure"

bad_http_root="$scratch/bad-http-repo"
copy_fixture "$bad_http_root"
if env \
  MISE_BIN="$fake_mise" \
  MISE_HTTP_TIMEOUT=60 \
  MISE_LOCK_TIMEOUT=5s \
  bash "$bad_http_root/scripts/regenerate-mise-lock.sh"; then
  echo "ERROR: unitless HTTP timeout was accepted" >&2
  exit 1
fi
cmp -s "$ROOT/mise.lock" "$bad_http_root/mise.lock" \
  || { echo "ERROR: bad HTTP timeout changed the lock" >&2; exit 1; }
assert_no_temp_lock "$bad_http_root"
echo "OK reject unitless HTTP timeout"

bad_lock_root="$scratch/bad-lock-repo"
copy_fixture "$bad_lock_root"
if env \
  MISE_BIN="$fake_mise" \
  MISE_HTTP_TIMEOUT=7s \
  MISE_LOCK_TIMEOUT=--help \
  bash "$bad_lock_root/scripts/regenerate-mise-lock.sh"; then
  echo "ERROR: option-like lock timeout was accepted" >&2
  exit 1
fi
cmp -s "$ROOT/mise.lock" "$bad_lock_root/mise.lock" \
  || { echo "ERROR: bad lock timeout changed the lock" >&2; exit 1; }
assert_no_temp_lock "$bad_lock_root"
echo "OK reject option-like lock timeout"

echo "All isolated mise lock regeneration tests passed."
