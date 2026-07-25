#!/usr/bin/env bash
set -euo pipefail

metadata_dir=/usr/share/remote-dev

read_metadata() {
  local name="$1"
  local path="$metadata_dir/$name"

  if [[ -r "$path" ]]; then
    head -n 1 "$path"
  else
    printf 'unknown'
  fi
}

image_version="$(read_metadata image-version)"
source_revision="$(read_metadata source-revision)"
codex_version="$(codex --version 2>/dev/null || printf 'unavailable')"

if [[ "$source_revision" == "unknown" ]]; then
  short_revision=unknown
else
  short_revision="${source_revision:0:12}"
fi

case "${1:-}" in
  "")
    printf 'Image version: %s\n' "$image_version"
    printf 'Source revision: %s\n' "$source_revision"
    printf 'Codex CLI: %s\n' "$codex_version"
    ;;
  --menu)
    printf 'Image: %s @ %s\n' "$image_version" "$short_revision"
    printf 'Codex: %s\n' "$codex_version"
    ;;
  *)
    echo "Usage: remote-dev-version [--menu]" >&2
    exit 2
    ;;
esac
