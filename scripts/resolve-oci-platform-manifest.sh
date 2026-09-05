#!/usr/bin/env bash
set -euo pipefail

if (( $# != 3 )); then
  echo "Usage: $0 <repository@index-digest> <os> <architecture>" >&2
  exit 2
fi

index_ref="$1"
expected_os="$2"
expected_arch="$3"

fail() {
  echo "ERROR: OCI platform manifest resolution: $*" >&2
  exit 1
}

[[ "$index_ref" =~ ^ghcr\.io/experience83/(remote-dev-base|remote-dev)@sha256:[0-9a-f]{64}$ ]] \
  || fail "reference is not an immutable Remote Dev GHCR digest"
[[ "$expected_os" =~ ^[a-z0-9][a-z0-9._-]*$ ]] \
  || fail "invalid operating system selector"
[[ "$expected_arch" =~ ^[a-z0-9][a-z0-9._-]*$ ]] \
  || fail "invalid architecture selector"

raw_index="$(docker buildx imagetools inspect "$index_ref" --raw)" \
  || fail "could not inspect OCI index $index_ref"

media_type="$(jq -r '.mediaType // empty' <<<"$raw_index")" \
  || fail "could not parse OCI index media type"
case "$media_type" in
  application/vnd.oci.image.index.v1+json|application/vnd.docker.distribution.manifest.list.v2+json)
    ;;
  *)
    fail "root digest media type '$media_type' is not an image index"
    ;;
esac

matches="$(
  jq -ce \
    --arg os "$expected_os" \
    --arg arch "$expected_arch" \
    '[
      .manifests[]?
      | select(.platform.os == $os and .platform.architecture == $arch)
      | select((.annotations["vnd.docker.reference.type"] // "") != "attestation-manifest")
    ]' <<<"$raw_index"
)" || fail "could not parse platform descriptors from OCI index"

match_count="$(jq -r 'length' <<<"$matches")"
[[ "$match_count" == 1 ]] \
  || fail "expected exactly one runnable ${expected_os}/${expected_arch} manifest, found $match_count"

manifest_digest="$(jq -r '.[0].digest // empty' <<<"$matches")"
[[ "$manifest_digest" =~ ^sha256:[0-9a-f]{64}$ ]] \
  || fail "selected platform manifest digest is malformed"

manifest_media_type="$(jq -r '.[0].mediaType // empty' <<<"$matches")"
case "$manifest_media_type" in
  application/vnd.oci.image.manifest.v1+json|application/vnd.docker.distribution.manifest.v2+json)
    ;;
  *)
    fail "selected platform descriptor media type '$manifest_media_type' is not runnable"
    ;;
esac

repository="${index_ref%@*}"
printf '%s@%s\n' "$repository" "$manifest_digest"
