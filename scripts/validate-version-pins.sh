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
edge_workflow="$ROOT/.github/workflows/publish-edge-amd64.yml"
upstream_workflow="$ROOT/.github/workflows/check-upstream.yml"

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
      reference="${reference%"${reference##*[![:space:]]}"}"

      case "$reference" in
        \"*\")
          reference="${reference:1:${#reference}-2}"
          ;;
        \'*\')
          reference="${reference:1:${#reference}-2}"
          ;;
      esac

      if [[ "$reference" == ./* ]]; then
        continue
      fi
      if [[ ! "$reference" =~ ^[^@[:space:]]+/[^@[:space:]]+@[0-9a-f]{40}$ ]]; then
        echo "ERROR: $workflow uses a mutable or invalid GitHub Action reference: $reference" >&2
        exit 1
      fi
    done < <(sed -n 's/^[[:space:]]*\(-[[:space:]]*\)\?uses:[[:space:]]*//p' "$workflow")
  done < <(find "$ROOT/.github/workflows" -type f \( -name '*.yml' -o -name '*.yaml' \) -print)
}

require_edge_path_trigger() {
  local path="$1"
  if ! grep -Fxq "      - \"$path\"" "$edge_workflow"; then
    echo "ERROR: edge publication must trigger when $path changes" >&2
    exit 1
  fi
}

require_codex_companion_updater() {
  local needle=""
  local required=(
    'release_sha256 "$workdir/codex.json" codex-code-mode-host-x86_64-unknown-linux-musl.tar.gz'
    'release_sha256 "$workdir/codex.json" codex-code-mode-host-aarch64-unknown-linux-musl.tar.gz'
    'replace_env CODEX_CODE_MODE_HOST_AMD64_SHA256 "$codex_code_mode_host_amd64_sha256"'
    'replace_env CODEX_CODE_MODE_HOST_ARM64_SHA256 "$codex_code_mode_host_arm64_sha256"'
    'replace_arg images/codex/Dockerfile CODEX_CODE_MODE_HOST_AMD64_SHA256 "$codex_code_mode_host_amd64_sha256"'
    'replace_arg images/codex/Dockerfile CODEX_CODE_MODE_HOST_ARM64_SHA256 "$codex_code_mode_host_arm64_sha256"'
  )

  for needle in "${required[@]}"; do
    if ! grep -Fq "$needle" "$upstream_workflow"; then
      echo "ERROR: check-upstream.yml must keep Codex code-mode host pins synchronized: $needle" >&2
      exit 1
    fi
  done
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
require_edge_path_trigger mise.toml
require_edge_path_trigger mise.lock
require_codex_companion_updater

if ! grep -Fq 'MISE_GLOBAL_CONFIG_FILE=/etc/mise/mise.toml' "$base_dockerfile"; then
  echo "ERROR: base Dockerfile must use the committed mise.toml as its global config" >&2
  exit 1
fi
if ! grep -Fq 'COPY --chmod=0444 mise.toml mise.lock /etc/mise/' "$base_dockerfile"; then
  echo "ERROR: base Dockerfile must copy immutable mise config and lock inputs" >&2
  exit 1
fi
if ! grep -Fq 'mise install --locked' "$base_dockerfile"; then
  echo "ERROR: base Dockerfile must install mise runtimes in locked mode" >&2
  exit 1
fi
if grep -Fq 'mise use --global' "$base_dockerfile"; then
  echo "ERROR: base Dockerfile must not resolve mise runtimes dynamically" >&2
  exit 1
fi
python3 "$ROOT/scripts/validate-mise-lock.py" --root "$ROOT"
python3 "$ROOT/scripts/test-validate-mise-lock.py" --root "$ROOT"
bash "$ROOT/scripts/test-regenerate-mise-lock.sh"

if [[ ! "$UBUNTU_VERSION" =~ ^[0-9]*[02468]\.04$ ]]; then
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
if [[ ! "$PYTHON_VERSION" =~ ^3\.14\.[0-9]+$ ]]; then
  echo "ERROR: PYTHON_VERSION must be an exact stable Python 3.14 maintenance release: $PYTHON_VERSION" >&2
  exit 1
fi
if [[ ! "$NODE_VERSION" =~ ^24\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: NODE_VERSION must be an exact stable Node 24 LTS maintenance release: $NODE_VERSION" >&2
  exit 1
fi
if [[ ! "$NPM_VERSION" =~ ^12\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: NPM_VERSION must be an exact supported npm 12 release: $NPM_VERSION" >&2
  exit 1
fi
if [[ ! "$UV_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: UV_VERSION must be an exact stable uv release: $UV_VERSION" >&2
  exit 1
fi

if grep -Fiq 'bubblewrap' "$base_dockerfile"; then
  echo "ERROR: default base Dockerfile must not install or reference Bubblewrap" >&2
  exit 1
fi

for variable in \
  CODEX_AMD64_SHA256 \
  CODEX_ARM64_SHA256 \
  CODEX_CODE_MODE_HOST_AMD64_SHA256 \
  CODEX_CODE_MODE_HOST_ARM64_SHA256 \
  GH_AMD64_SHA256 \
  GH_ARM64_SHA256 \
  TTYD_AMD64_SHA256 \
  TTYD_ARM64_SHA256 \
  MISE_AMD64_SHA256 \
  MISE_ARM64_SHA256; do
  require_sha256 "$variable"
done

for variable in \
  BASE_VERSION \
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
  PYTHON_VERSION \
  NODE_VERSION \
  NPM_VERSION \
  UV_VERSION; do
  require_synced_arg "$variable" "$base_dockerfile"
done

for variable in \
  CODEX_RELEASE_TAG \
  CODEX_AMD64_SHA256 \
  CODEX_ARM64_SHA256 \
  CODEX_CODE_MODE_HOST_AMD64_SHA256 \
  CODEX_CODE_MODE_HOST_ARM64_SHA256; do
  require_synced_arg "$variable" "$codex_dockerfile"
done

printf 'Ubuntu base pin: %s@%s\n' "$UBUNTU_VERSION" "$UBUNTU_DIGEST"
printf 'Codex release pin: %s\n' "$CODEX_RELEASE_TAG"
printf 'Python release pin: %s\n' "$PYTHON_VERSION"
printf 'Node LTS release pin: %s\n' "$NODE_VERSION"
printf 'npm release pin: %s\n' "$NPM_VERSION"
printf 'uv release pin: %s\n' "$UV_VERSION"
echo "Release asset SHA-256 pins, Codex companion updater bindings and mise runtime lock data are present and synchronized."
