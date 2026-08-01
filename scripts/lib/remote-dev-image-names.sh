#!/usr/bin/env bash

if [[ -n "${REMOTE_DEV_IMAGE_NAMES_LIB_LOADED:-}" ]]; then
  return 0
fi
REMOTE_DEV_IMAGE_NAMES_LIB_LOADED=1

remote_dev_resolve_compatible_image() {
  local canonical_name="$1"
  local legacy_name="$2"
  local default_value="$3"
  local canonical_value="${!canonical_name:-}"
  local legacy_value="${!legacy_name:-}"

  if [[ -n "$canonical_value" ]]; then
    if [[ -n "$legacy_value" && "$legacy_value" != "$canonical_value" ]]; then
      printf 'WARNING: %s=%s overrides deprecated %s=%s\n' \
        "$canonical_name" "$canonical_value" "$legacy_name" "$legacy_value" >&2
    fi
    printf '%s\n' "$canonical_value"
    return 0
  fi

  if [[ -n "$legacy_value" ]]; then
    printf 'WARNING: %s is deprecated; use %s instead (supported through v0.1.x)\n' \
      "$legacy_name" "$canonical_name" >&2
    printf '%s\n' "$legacy_value"
    return 0
  fi

  printf '%s\n' "$default_value"
}

remote_dev_tag_compatibility_aliases() {
  local source_image="$1"
  shift
  local alias=""

  for alias in "$@"; do
    if [[ "$alias" != "$source_image" ]]; then
      docker tag "$source_image" "$alias"
    fi
  done
}
