#!/usr/bin/env bash
set -euo pipefail

image_names_lib="${REMOTE_DEV_IMAGE_NAMES_LIB:-/usr/local/lib/remote-dev/remote-dev-image-names.sh}"
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-image-names.sh
source "$image_names_lib"

assert_eq() {
  local expected="$1"
  local actual="$2"
  local label="$3"

  if [[ "$actual" != "$expected" ]]; then
    printf 'ERROR: %s: expected %q, got %q\n' "$label" "$expected" "$actual" >&2
    exit 1
  fi
}

resolve_in_clean_shell() {
  env -u REMOTE_DEV_IMAGE -u CODEX_IMAGE -u REMOTE_DEV_BASE_IMAGE -u BASE_IMAGE \
    "$@" bash -c 'source "$1"; remote_dev_resolve_compatible_image "$2" "$3" "$4"' \
    _ "$image_names_lib" "$5" "$6" "$7"
}

assert_eq remote-dev:local \
  "$(resolve_in_clean_shell env REMOTE_DEV_IMAGE=remote-dev:local REMOTE_DEV_IMAGE CODEX_IMAGE ignored)" \
  "canonical final image"

assert_eq legacy-final:local \
  "$(resolve_in_clean_shell env CODEX_IMAGE=legacy-final:local REMOTE_DEV_IMAGE CODEX_IMAGE remote-dev:local 2>/dev/null)" \
  "legacy final image fallback"

assert_eq canonical-wins:local \
  "$(resolve_in_clean_shell env REMOTE_DEV_IMAGE=canonical-wins:local CODEX_IMAGE=legacy-loses:local REMOTE_DEV_IMAGE CODEX_IMAGE remote-dev:local 2>/dev/null)" \
  "canonical final image precedence"

assert_eq remote-dev:local \
  "$(resolve_in_clean_shell env REMOTE_DEV_IMAGE CODEX_IMAGE remote-dev:local)" \
  "default final image"

assert_eq remote-dev-base:local \
  "$(resolve_in_clean_shell env REMOTE_DEV_BASE_IMAGE=remote-dev-base:local REMOTE_DEV_BASE_IMAGE BASE_IMAGE ignored)" \
  "canonical base image"

assert_eq legacy-base:local \
  "$(resolve_in_clean_shell env BASE_IMAGE=legacy-base:local REMOTE_DEV_BASE_IMAGE BASE_IMAGE remote-dev-base:local 2>/dev/null)" \
  "legacy base image fallback"

warning_file="$(mktemp)"
trap 'rm -f "$warning_file"' EXIT
result="$(
  env REMOTE_DEV_IMAGE=canonical:local CODEX_IMAGE=legacy:local \
    bash -c 'source "$1"; remote_dev_resolve_compatible_image REMOTE_DEV_IMAGE CODEX_IMAGE remote-dev:local' \
    _ "$image_names_lib" 2>"$warning_file"
)"
assert_eq canonical:local "$result" "conflicting canonical value"
grep -Fq -- 'REMOTE_DEV_IMAGE=canonical:local overrides deprecated CODEX_IMAGE=legacy:local' "$warning_file"

echo "Canonical and legacy image-name resolution tests: OK"
