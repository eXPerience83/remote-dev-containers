#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
empty_env="$(mktemp)"
trap 'rm -f "$empty_env"' EXIT

assert_eq() {
  local expected="$1"
  local actual="$2"
  local label="$3"

  if [[ "$actual" != "$expected" ]]; then
    printf 'ERROR: %s: expected %q, got %q\n' "$label" "$expected" "$actual" >&2
    exit 1
  fi
}

resolve_image() {
  local compose_file="$1"
  shift

  env -u REMOTE_DEV_IMAGE -u CODEX_IMAGE "$@" \
    docker compose \
      --env-file "$empty_env" \
      -f "$root/$compose_file" \
      config --images
}

for compose_file in compose/docker-compose.yml compose/truenas.yml; do
  assert_eq \
    ghcr.io/experience83/remote-dev:edge-amd64 \
    "$(resolve_image "$compose_file")" \
    "$compose_file canonical default"

  assert_eq \
    example.invalid/legacy:test \
    "$(resolve_image "$compose_file" CODEX_IMAGE=example.invalid/legacy:test)" \
    "$compose_file legacy fallback"

  assert_eq \
    example.invalid/canonical:test \
    "$(resolve_image "$compose_file" REMOTE_DEV_IMAGE=example.invalid/canonical:test)" \
    "$compose_file canonical override"

  assert_eq \
    example.invalid/canonical:test \
    "$(resolve_image "$compose_file" \
      REMOTE_DEV_IMAGE=example.invalid/canonical:test \
      CODEX_IMAGE=example.invalid/legacy:test)" \
    "$compose_file canonical precedence"

  assert_eq \
    example.invalid/legacy:test \
    "$(resolve_image "$compose_file" \
      REMOTE_DEV_IMAGE= \
      CODEX_IMAGE=example.invalid/legacy:test)" \
    "$compose_file empty canonical fallback"
done

echo "Compose canonical and legacy image resolution tests: OK"
