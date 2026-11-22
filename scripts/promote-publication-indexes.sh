#!/usr/bin/env bash
set -euo pipefail

if (( $# != 4 )); then
  echo "Usage: $0 edge|stable BASE_INDEX_REF RUNTIME_INDEX_REF SHA_OR_RELEASE" >&2
  exit 2
fi

base_ref="$2"
runtime_ref="$3"
identifier="$4"
if [[ ! "$base_ref" =~ ^ghcr\.io/experience83/remote-dev-base@sha256:[a-f0-9]{64}$ ||
      ! "$runtime_ref" =~ ^ghcr\.io/experience83/remote-dev@sha256:[a-f0-9]{64}$ ]]; then
  echo "ERROR: expected immutable Base and Runtime index references" >&2
  exit 2
fi

case "$1" in
  edge)
    [[ "$identifier" =~ ^[a-f0-9]{40}$ ]] || exit 2
    base_tags=(edge-amd64 "sha-$identifier")
    runtime_tags=(edge edge-amd64 "sha-$identifier")
    ;;
  stable)
    [[ "$identifier" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || exit 2
    base_tags=("$identifier" stable-amd64)
    runtime_tags=("$identifier" stable stable-amd64 latest)
    ;;
  *) echo "ERROR: unknown publication channel" >&2; exit 2 ;;
esac

promote() {
  local ref="$1" metadata="$2"
  shift 2
  local repository="${ref%@*}" expected="${ref##*@}" tag actual
  local -a destinations=()

  for tag in "$@"; do
    destinations+=(--tag "$repository:$tag")
  done
  docker buildx imagetools create --prefer-index=false --metadata-file "$metadata" \
    "${destinations[@]}" "$ref"
  actual="$(jq -r '.["containerimage.descriptor"].digest // .["containerimage.digest"] // empty' "$metadata")"
  if [[ "$actual" != "$expected" ]]; then
    echo "ERROR: promotion of $ref returned digest $actual" >&2
    return 1
  fi
  for tag in "$@"; do
    actual="$(docker buildx imagetools inspect "$repository:$tag" \
      --format '{{json .Manifest.Digest}}' | jq -er '.')"
    if [[ "$actual" != "$expected" ]]; then
      echo "ERROR: $repository:$tag resolved to $actual instead of $expected" >&2
      return 1
    fi
  done
}

promote "$base_ref" base-promotion.json "${base_tags[@]}"
promote "$runtime_ref" runtime-promotion.json "${runtime_tags[@]}"
