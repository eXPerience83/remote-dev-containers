#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"

docker_arg() {
  local file="$1"
  local name="$2"
  sed -n "s/^ARG ${name}=//p" "$file" | head -n 1
}

require_synced_arg() {
  local variable="$1"
  local file="$2"
  local expected="${!variable}"
  local actual=""

  actual="$(docker_arg "$file" "$variable")"
  if [[ -z "$actual" ]]; then
    echo "ERROR: $file has no default $variable argument" >&2
    exit 1
  fi
  if [[ "$actual" != "$expected" ]]; then
    cat >&2 <<EOF
ERROR: $variable pins are inconsistent.
versions.env: $expected
$file: $actual
Update both references in the same pull request.
EOF
    exit 1
  fi
}

require_sha256() {
  local variable="$1"
  local value="${!variable}"

  if [[ ! "$value" =~ ^[0-9a-f]{64}$ ]]; then
    echo "ERROR: $variable must be an exact lowercase SHA-256: $value" >&2
    exit 1
  fi
}

base_dockerfile="$ROOT/images/base/Dockerfile"
codex_dockerfile="$ROOT/images/codex/Dockerfile"

if [[ ! "$UBUNTU_VERSION" =~ ^[0-9]+\.04$ ]]; then
  echo "ERROR: UBUNTU_VERSION must be an explicit Ubuntu LTS release tag: $UBUNTU_VERSION" >&2
  exit 1
fi
if [[ ! "$UBUNTU_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "ERROR: UBUNTU_DIGEST must be an exact OCI sha256 digest: $UBUNTU_DIGEST" >&2
  exit 1
fi
if [[ ! "$CODEX_RELEASE_TAG" =~ ^rust-v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: CODEX_RELEASE_TAG must be an exact stable release tag: $CODEX_RELEASE_TAG" >&2
  exit 1
fi
if [[ ! "$GH_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: GH_VERSION must be an exact semantic version: $GH_VERSION" >&2
  exit 1
fi
if [[ ! "$TTYD_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: TTYD_VERSION must be an exact semantic version: $TTYD_VERSION" >&2
  exit 1
fi
if [[ ! "$MISE_VERSION" =~ ^[0-9]{4}\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: MISE_VERSION must be an exact stable release version: $MISE_VERSION" >&2
  exit 1
fi

for variable in \
  CODEX_AMD64_SHA256 \
  CODEX_ARM64_SHA256 \
  GH_AMD64_SHA256 \
  GH_ARM64_SHA256 \
  TTYD_AMD64_SHA256 \
  TTYD_ARM64_SHA256 \
  MISE_AMD64_SHA256 \
  MISE_ARM64_SHA256; do
  require_sha256 "$variable"
done

for variable in \
  UBUNTU_VERSION \
  UBUNTU_DIGEST \
  GH_VERSION \
  GH_AMD64_SHA256 \
  GH_ARM64_SHA256 \
  TTYD_VERSION \
  TTYD_AMD64_SHA256 \
  TTYD_ARM64_SHA256 \
  MISE_VERSION \
  MISE_AMD64_SHA256 \
  MISE_ARM64_SHA256; do
  require_synced_arg "$variable" "$base_dockerfile"
done

for variable in \
  CODEX_RELEASE_TAG \
  CODEX_AMD64_SHA256 \
  CODEX_ARM64_SHA256; do
  require_synced_arg "$variable" "$codex_dockerfile"
done

printf 'Ubuntu base pin: %s@%s\n' "$UBUNTU_VERSION" "$UBUNTU_DIGEST"
printf 'Codex release pin: %s\n' "$CODEX_RELEASE_TAG"
echo "Release asset SHA-256 pins are present and synchronized."
