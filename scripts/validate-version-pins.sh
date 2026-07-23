#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"

dockerfile_ubuntu="$(sed -n 's/^ARG UBUNTU_VERSION=//p' "$ROOT/images/base/Dockerfile" | head -n 1)"

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

printf 'Ubuntu version pins are synchronized: %s\n' "$UBUNTU_VERSION"
