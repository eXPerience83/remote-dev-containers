#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"

bash "$ROOT/scripts/validate-version-pins.sh"

require_build_value() {
  local label="$1"
  local value="$2"

  if [[ -z "$value" ]]; then
    echo "ERROR: $label must not be empty" >&2
    exit 1
  fi
  if [[ "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
    echo "ERROR: $label must be a single-line value" >&2
    exit 1
  fi
  case "$value" in
    unknown|unavailable)
      echo "ERROR: $label must identify the build, not use the reserved value $value" >&2
      exit 1
      ;;
  esac
}

BASE_IMAGE="${BASE_IMAGE:-codex-remote-dev-base:local}"
CODEX_IMAGE="${CODEX_IMAGE:-codex-remote-dev:local}"
PLATFORM="${PLATFORM:-linux/amd64}"
PROJECT_VERSION="${PROJECT_VERSION:-${BASE_VERSION:-}}"

if [[ -z "${SOURCE_REVISION:-}" ]]; then
  SOURCE_REVISION="$(bash "$ROOT/scripts/detect-source-revision.sh" "$ROOT")"
fi

require_build_value PROJECT_VERSION "$PROJECT_VERSION"
require_build_value SOURCE_REVISION "$SOURCE_REVISION"

common_args=(
  --platform "$PLATFORM"
  --build-arg "UBUNTU_VERSION=$UBUNTU_VERSION"
  --build-arg "UBUNTU_DIGEST=$UBUNTU_DIGEST"
  --build-arg "BASE_VERSION=$BASE_VERSION"
  --build-arg "GH_VERSION=$GH_VERSION"
  --build-arg "GH_AMD64_SHA256=$GH_AMD64_SHA256"
  --build-arg "GH_ARM64_SHA256=$GH_ARM64_SHA256"
  --build-arg "TTYD_VERSION=$TTYD_VERSION"
  --build-arg "TTYD_AMD64_SHA256=$TTYD_AMD64_SHA256"
  --build-arg "TTYD_ARM64_SHA256=$TTYD_ARM64_SHA256"
  --build-arg "MISE_VERSION=$MISE_VERSION"
  --build-arg "MISE_AMD64_SHA256=$MISE_AMD64_SHA256"
  --build-arg "MISE_ARM64_SHA256=$MISE_ARM64_SHA256"
  --build-arg "PYTHON_VERSION=$PYTHON_VERSION"
  --build-arg "NODE_VERSION=$NODE_VERSION"
  --build-arg "NPM_VERSION=$NPM_VERSION"
  --build-arg "UV_VERSION=$UV_VERSION"
)

docker build "${common_args[@]}" -t "$BASE_IMAGE" -f "$ROOT/images/base/Dockerfile" "$ROOT"
docker build \
  --platform "$PLATFORM" \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  --build-arg "CODEX_RELEASE_TAG=$CODEX_RELEASE_TAG" \
  --build-arg "CODEX_AMD64_SHA256=$CODEX_AMD64_SHA256" \
  --build-arg "CODEX_ARM64_SHA256=$CODEX_ARM64_SHA256" \
  --build-arg "PROJECT_VERSION=$PROJECT_VERSION" \
  --build-arg "SOURCE_REVISION=$SOURCE_REVISION" \
  -t "$CODEX_IMAGE" \
  -f "$ROOT/images/codex/Dockerfile" \
  "$ROOT"

docker run --rm --entrypoint /usr/local/bin/codex-smoke-test "$CODEX_IMAGE"
bash "$ROOT/scripts/runtime-smoke-test.sh" "$CODEX_IMAGE"
docker image inspect "$BASE_IMAGE" "$CODEX_IMAGE" --format '{{.RepoTags}} {{.Size}}'
