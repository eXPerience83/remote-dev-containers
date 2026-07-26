#!/usr/bin/env bash

format_short_revision() {
  local revision="$1"

  if [[ "$revision" =~ ^([0-9a-fA-F]{12,})(-dirty)?$ ]]; then
    printf '%s%s' "${BASH_REMATCH[1]:0:12}" "${BASH_REMATCH[2]:-}"
  else
    printf '%s' "$revision"
  fi
}
