#!/usr/bin/env bash
set -euo pipefail

if (( $# != 2 )); then
  echo "Usage: $0 <repository> <tag>" >&2
  exit 2
fi

repository="$1"
tag="$2"

case "$repository" in
  ghcr.io/experience83/remote-dev-base|ghcr.io/experience83/remote-dev) ;;
  *)
    echo "ERROR: unsupported published image repository: $repository" >&2
    exit 2
    ;;
esac

if [[ "$tag" != edge-amd64 ]]; then
  echo "ERROR: periodic rescan may resolve only edge-amd64; got $tag" >&2
  exit 2
fi

mutable_ref="${repository}:${tag}"
docker pull --quiet "$mutable_ref" >/dev/null

mapfile -t matching_digests < <(
  docker image inspect "$mutable_ref" --format '{{range .RepoDigests}}{{println .}}{{end}}' \
    | grep -E "^${repository//./\.}@sha256:[0-9a-f]{64}$" \
    | sort -u
)

if (( ${#matching_digests[@]} != 1 )); then
  echo "ERROR: expected exactly one immutable RepoDigest for $mutable_ref; found ${#matching_digests[@]}" >&2
  exit 1
fi

printf '%s\n' "${matching_digests[0]}"
