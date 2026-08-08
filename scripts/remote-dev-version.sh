#!/usr/bin/env bash
set -euo pipefail

metadata_dir=/usr/share/remote-dev
lib_dir=/usr/local/lib/remote-dev
runtime_manager=/usr/local/bin/remote-dev-codex-runtime

# shellcheck source=/usr/local/lib/remote-dev/format-short-revision.sh
source "$lib_dir/format-short-revision.sh"

read_metadata() {
  local name="$1"
  local path="$metadata_dir/$name"
  local value=""

  if [[ ! -r "$path" ]]; then
    printf 'unknown'
    return 0
  fi

  IFS= read -r value < "$path" || true
  if [[ -z "$value" ]]; then
    printf 'unknown'
  else
    printf '%s' "$value"
  fi
}

validate_value() {
  local label="$1"
  local value="$2"

  case "$value" in
    ""|unknown|unavailable)
      echo "ERROR: $label metadata is unavailable" >&2
      return 1
      ;;
  esac
}

image_version="$(read_metadata image-version)"
source_revision="$(read_metadata source-revision)"
codex_version="$(/usr/local/bin/codex --version 2>/dev/null || printf 'unavailable')"
short_revision="$(format_short_revision "$source_revision")"

validate_metadata() {
  local result=0

  validate_value "image version" "$image_version" || result=1
  validate_value "source revision" "$source_revision" || result=1
  validate_value "bundled Codex CLI version" "$codex_version" || result=1

  return "$result"
}

print_codex_runtime_status() {
  local role="${REMOTE_DEV_ROLE:-codex}"
  local runtime_status=""
  if [[ "$role" != codex || ! -x "$runtime_manager" ]]; then
    return 0
  fi
  if ! runtime_status="$("$runtime_manager" status 2>/dev/null)"; then
    printf '%s\n' 'Codex runtime: unavailable'
    return 0
  fi
  sed '/^Codex bundled:/d' <<<"$runtime_status"
}

case "${1:-}" in
  "")
    printf 'Image version: %s\n' "$image_version"
    printf 'Source revision: %s\n' "$source_revision"
    printf 'Codex CLI: %s\n' "$codex_version"
    print_codex_runtime_status
    ;;
  --menu)
    printf 'Image: %s @ %s\n' "$image_version" "$short_revision"
    printf 'Codex: %s\n' "$codex_version"
    ;;
  --check)
    # Optional runtime damage must never make immutable image identity unhealthy.
    validate_metadata
    ;;
  *)
    echo "Usage: remote-dev-version [--menu|--check]" >&2
    exit 2
    ;;
esac
