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

require_frontend_pin() {
  local file="$1"
  local first_line=""
  local pattern='^# syntax=docker/dockerfile:[0-9]+\.[0-9]+(\.[0-9]+)?@sha256:[0-9a-f]{64}$'

  first_line="$(head -n 1 "$file")"
  if [[ ! "$first_line" =~ $pattern ]]; then
    echo "ERROR: $file must pin the Dockerfile frontend to an exact version and digest" >&2
    exit 1
  fi
  printf '%s\n' "$first_line"
}

require_action_shas() {
  local workflow=""
  local reference=""

  while IFS= read -r workflow; do
    while IFS= read -r reference; do
      reference="${reference%%[[:space:]]#*}"
      if [[ "$reference" == ./* ]]; then
        continue
      fi
      if [[ ! "$reference" =~ ^[^@[:space:]]+/[^@[:space:]]+@[0-9a-f]{40}$ ]]; then
        echo "ERROR: $workflow uses a mutable or invalid GitHub Action reference: $reference" >&2
        exit 1
      fi
    done < <(sed -n 's/^[[:space:]]*-[[:space:]]*uses:[[:space:]]*//p' "$workflow")
  done < <(find "$ROOT/.github/workflows" -type f \( -name '*.yml' -o -name '*.yaml' \) -print)
}

base_frontend="$(require_frontend_pin "$base_dockerfile")"
codex_frontend="$(require_frontend_pin "$codex_dockerfile")"
if [[ "$base_frontend" != "$codex_frontend" ]]; then
  echo "ERROR: Dockerfiles must use the same pinned frontend image" >&2
  exit 1
fi
if ! grep -Fxq 'FROM ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST}' "$base_dockerfile"; then
  echo "ERROR: base Dockerfile must bind Ubuntu to UBUNTU_DIGEST" >&2
  exit 1
fi
require_action_shas

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
if [[ ! "$NPM_VERSION" =~ ^11\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: NPM_VERSION must be an exact supported npm 11 release: $NPM_VERSION" >&2
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
  MISE_ARM64_SHA256 \
  NPM_VERSION; do
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
printf 'npm release pin: %s\n' "$NPM_VERSION"
echo "Release asset SHA-256 pins are present and synchronized."
