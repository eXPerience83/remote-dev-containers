#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"

dockerfile_ubuntu="$(sed -n 's/^ARG UBUNTU_VERSION=//p' "$ROOT/images/base/Dockerfile" | head -n 1)"
dockerfile_codex="$(sed -n 's/^ARG CODEX_RELEASE_TAG=//p' "$ROOT/images/codex/Dockerfile" | head -n 1)"

if [[ -z "$dockerfile_ubuntu" ]]; then
  echo "ERROR: images/base/Dockerfile has no default UBUNTU_VERSION argument" >&2
  exit 1
fi

if [[ "$dockerfile_ubuntu" != "$UBUNTU_VERSION" ]]; then
  cat >&2 <<EOF
ERROR: Ubuntu version pins are inconsistent.
versions.env:            $UBUNTU_VERSION
images/base/Dockerfile:  $dockerfile_ubuntu
Update both references in the same pull request.
EOF
  exit 1
fi

if [[ ! "$UBUNTU_VERSION" =~ ^[0-9]+\.04$ ]]; then
  echo "ERROR: UBUNTU_VERSION must be an explicit Ubuntu LTS release tag, not a floating tag: $UBUNTU_VERSION" >&2
  exit 1
fi

if [[ -z "$dockerfile_codex" ]]; then
  echo "ERROR: images/codex/Dockerfile has no default CODEX_RELEASE_TAG argument" >&2
  exit 1
fi

if [[ "$dockerfile_codex" != "$CODEX_RELEASE_TAG" ]]; then
  cat >&2 <<EOF
ERROR: Codex release pins are inconsistent.
versions.env:             $CODEX_RELEASE_TAG
images/codex/Dockerfile:  $dockerfile_codex
Update both references in the same pull request.
EOF
  exit 1
fi

if [[ ! "$CODEX_RELEASE_TAG" =~ ^rust-v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: CODEX_RELEASE_TAG must be an exact stable release tag: $CODEX_RELEASE_TAG" >&2
  exit 1
fi

printf 'Ubuntu version pins are synchronized: %s\n' "$UBUNTU_VERSION"
printf 'Codex release pins are synchronized: %s\n' "$CODEX_RELEASE_TAG"
