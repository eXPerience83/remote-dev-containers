#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT

test_bin="$temporary/bin"
cleanup_root="$temporary/work"
mkdir -p "$test_bin" "$cleanup_root"

readonly OFFICIAL_INSTALLER_URL="https://antigravity.google/cli/install.sh"
readonly OFFICIAL_INSTALLER_ORIGIN="https://antigravity.google"
readonly MAX_INSTALLER_SIZE=$((2 * 1024 * 1024))
readonly MAX_INSTALLER_REDIRECTS=5
readonly CAPTURE_LIMIT_BLOCKS=2048

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

# shellcheck source=scripts/lib/antigravity-runtime/integrity.sh
source "$ROOT/scripts/lib/antigravity-runtime/integrity.sh"
# shellcheck source=scripts/lib/antigravity-runtime/installer.sh
source "$ROOT/scripts/lib/antigravity-runtime/installer.sh"

installer_fixture="$temporary/install.sh"
cat >"$installer_fixture" <<'INSTALLER'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --help ]]; then
  printf '%s\n' 'Usage: install.sh --dir <path>'
  exit 0
fi
[[ "${1:-}" == --dir && -n "${2:-}" ]] || exit 2
INSTALLER
chmod 0700 "$installer_fixture"

cat >"$test_bin/curl" <<'CURL_FIXTURE'
#!/usr/bin/env bash
set -euo pipefail

output=""
url=""
while (( $# )); do
  case "$1" in
    --output|-o)
      output="$2"
      shift 2
      ;;
    --proto|--proto-redir|--retry|--connect-timeout|--max-time|--max-filesize|--max-redirs|--write-out)
      shift 2
      ;;
    --tlsv1.2|--fail|--silent|--show-error|--retry-all-errors)
      shift
      ;;
    *)
      url="$1"
      shift
      ;;
  esac
done
[[ -n "$output" && -n "$url" ]] || exit 2
: >"$output"

case "${REMOTE_DEV_TEST_REDIRECT_MODE:?}:$url" in
  same-origin:https://antigravity.google/cli/install.sh)
    printf '%s\n%s\n%s\n%s\n' \
      302 "$url" text/html '/cli/current.sh'
    ;;
  same-origin:https://antigravity.google/cli/current.sh)
    cp -- "${REMOTE_DEV_TEST_INSTALLER_FIXTURE:?}" "$output"
    printf '%s\n%s\n%s\n%s\n' \
      200 "$url" application/x-sh ''
    ;;
  off-origin-return:https://antigravity.google/cli/install.sh)
    printf '%s\n%s\n%s\n%s\n' \
      302 "$url" text/html 'https://redirect.invalid/bounce'
    ;;
  off-origin-return:https://redirect.invalid/bounce)
    : >"${REMOTE_DEV_TEST_OFF_ORIGIN_CALLED:?}"
    printf '%s\n%s\n%s\n%s\n' \
      302 "$url" text/html 'https://antigravity.google/cli/current.sh'
    ;;
  off-origin-return:https://antigravity.google/cli/current.sh)
    cp -- "${REMOTE_DEV_TEST_INSTALLER_FIXTURE:?}" "$output"
    printf '%s\n%s\n%s\n%s\n' \
      200 "$url" application/x-sh ''
    ;;
  *)
    printf 'unexpected fixture URL: %s\n' "$url" >&2
    exit 2
    ;;
esac
CURL_FIXTURE
chmod 0755 "$test_bin/curl"

export PATH="$test_bin:$PATH"
export REMOTE_DEV_TEST_INSTALLER_FIXTURE="$installer_fixture"

# Relative redirects that remain on the fixed Google origin are followed one
# hop at a time and the final installer bytes are retained.
export REMOTE_DEV_TEST_REDIRECT_MODE=same-origin
destination="$temporary/downloaded-install.sh"
download_installer "$destination"
cmp -s "$installer_fixture" "$destination" \
  || fail "same-origin redirect did not preserve the installer"
[[ "$candidate_installer_final_url" == 'https://antigravity.google/cli/current.sh' ]] \
  || fail "same-origin redirect final URL was not recorded"

# A chain that leaves the official origin and later returns is rejected before
# the off-origin request is made, specifically by the origin validator.
export REMOTE_DEV_TEST_REDIRECT_MODE=off-origin-return
export REMOTE_DEV_TEST_OFF_ORIGIN_CALLED="$temporary/off-origin-called"
rm -f -- "$REMOTE_DEV_TEST_OFF_ORIGIN_CALLED"
rejection_output=""
rejection_status=0
rejection_output="$(
  download_installer "$temporary/rejected-install.sh" 2>&1
)" || rejection_status=$?
(( rejection_status != 0 )) || fail "off-origin intermediate redirect was accepted"
grep -Fq 'left the reviewed Google origin' <<<"$rejection_output" \
  || fail "off-origin redirect was rejected for an unexpected reason: $rejection_output"
[[ ! -e "$REMOTE_DEV_TEST_OFF_ORIGIN_CALLED" ]] \
  || fail "downloader contacted an off-origin intermediate redirect"

printf 'Antigravity redirect-origin regressions: OK\n'
