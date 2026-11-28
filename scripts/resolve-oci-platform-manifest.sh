#!/usr/bin/env bash
set -euo pipefail

if (( $# != 3 && $# != 4 )) || { (( $# == 4 )) && [[ "$4" != --wait-for-push ]]; }; then
  echo "Usage: $0 <repository@index-digest> <os> <architecture> [--wait-for-push]" >&2
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

if [[ "${4:-}" == --wait-for-push ]]; then
  # Only a just-pushed immutable index may use this bounded visibility wait.
  # Do not retry authentication, mixed/unknown errors, timeouts or validation.
  error_file="$(mktemp)"
  trap 'rm -f -- "$error_file"' EXIT
  delays=(2 4 8)
  for (( attempt=0; ; attempt++ )); do
    if raw_index="$(timeout --kill-after=5s 30s docker buildx imagetools inspect "$index_ref" --raw 2>"$error_file")"; then
      break
    else
      status=$?
    fi
    error="$(cat "$error_file")"
    if [[ "$status" != 1 || -n "$raw_index" || "$error" != "ERROR: $index_ref: not found" ]] || (( attempt >= ${#delays[@]} )); then
      fail "could not inspect newly pushed OCI index $index_ref"
    fi
    echo "Waiting ${delays[attempt]}s for visibility of immutable OCI index $index_ref" >&2
    sleep "${delays[attempt]}"
  done
else
  raw_index="$(docker buildx imagetools inspect "$index_ref" --raw)" \
    || fail "could not inspect OCI index $index_ref"
fi

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
