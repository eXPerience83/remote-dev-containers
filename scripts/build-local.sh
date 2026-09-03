#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"
# shellcheck source=scripts/lib/remote-dev-image-names.sh
source "$ROOT/scripts/lib/remote-dev-image-names.sh"

bash "$ROOT/scripts/validate-version-pins.sh"
REMOTE_DEV_IMAGE_NAMES_LIB="$ROOT/scripts/lib/remote-dev-image-names.sh" \
  bash "$ROOT/scripts/test-image-name-compat.sh"

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

remote_dev_base_image="$(
  remote_dev_resolve_compatible_image \
    REMOTE_DEV_BASE_IMAGE BASE_IMAGE remote-dev-base:local
)"
remote_dev_image="$(
  remote_dev_resolve_compatible_image \
    REMOTE_DEV_IMAGE CODEX_IMAGE remote-dev:local
)"
PLATFORM="${PLATFORM:-linux/amd64}"
PROJECT_VERSION="${PROJECT_VERSION:-${BASE_VERSION:-}}"
PROJECT_CHANNEL="${PROJECT_CHANNEL:-local}"

if [[ -z "${SOURCE_REVISION:-}" ]]; then
  SOURCE_REVISION="$(bash "$ROOT/scripts/detect-source-revision.sh" "$ROOT")"
fi

require_build_value PROJECT_VERSION "$PROJECT_VERSION"
require_build_value PROJECT_CHANNEL "$PROJECT_CHANNEL"
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

docker build \
  "${common_args[@]}" \
  -t "$remote_dev_base_image" \
  -f "$ROOT/images/base/Dockerfile" \
  "$ROOT"
remote_dev_tag_compatibility_aliases \
  "$remote_dev_base_image" \
  remote-dev-base:local \
  codex-remote-dev-base:local

docker build \
  --platform "$PLATFORM" \
  --build-arg "BASE_IMAGE=$remote_dev_base_image" \
  --build-arg "CODEX_RELEASE_TAG=$CODEX_RELEASE_TAG" \
  --build-arg "CODEX_AMD64_SHA256=$CODEX_AMD64_SHA256" \
  --build-arg "CODEX_ARM64_SHA256=$CODEX_ARM64_SHA256" \
  --build-arg "PROJECT_VERSION=$PROJECT_VERSION" \
  --build-arg "PROJECT_CHANNEL=$PROJECT_CHANNEL" \
  --build-arg "SOURCE_REVISION=$SOURCE_REVISION" \
  -t "$remote_dev_image" \
  -f "$ROOT/images/codex/Dockerfile" \
  "$ROOT"
remote_dev_tag_compatibility_aliases \
  "$remote_dev_image" \
  remote-dev:local \
  codex-remote-dev:local

docker run --rm --entrypoint /usr/local/bin/codex-smoke-test "$remote_dev_image"
docker run --rm \
  --network none \
  --entrypoint /opt/remote-dev/mise/shims/python \
  -v "$ROOT/scripts/test-remote-dev-context7-runtime-isolation.py:/tmp/test-remote-dev-context7-runtime-isolation.py:ro" \
  -e REMOTE_DEV_CONTEXT7_DEVICE_LOGIN_HELPER=/usr/local/bin/remote-dev-context7-device-login \
  "$remote_dev_image" /tmp/test-remote-dev-context7-runtime-isolation.py
codex_noexec_smoke_command=(
  docker run --rm
  --user 0:0
  --network none
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777
  --entrypoint /opt/remote-dev/mise/shims/python
  -v "$ROOT/scripts/test-codex-runtime-noexec-staging.py:/tmp/test-codex-runtime-noexec-staging.py:ro"
  -e REMOTE_DEV_CODEX_RUNTIME_MANAGER=/usr/local/bin/remote-dev-codex-runtime
  "$remote_dev_image" /tmp/test-codex-runtime-noexec-staging.py
)
timeout --foreground 60s "${codex_noexec_smoke_command[@]}"
bash "$ROOT/scripts/runtime-smoke-test.sh" "$remote_dev_image"
bash "$ROOT/scripts/test-web-password-runtime.sh" "$remote_dev_image"
bash "$ROOT/scripts/test-cross-service-isolation.sh" "$remote_dev_image"

canonical_base_id="$(docker image inspect remote-dev-base:local --format '{{.Id}}')"
legacy_base_id="$(docker image inspect codex-remote-dev-base:local --format '{{.Id}}')"
canonical_runtime_id="$(docker image inspect remote-dev:local --format '{{.Id}}')"
legacy_runtime_id="$(docker image inspect codex-remote-dev:local --format '{{.Id}}')"
if [[ "$canonical_base_id" != "$legacy_base_id" ]]; then
  echo "ERROR: legacy base tag does not reference the canonical local image" >&2
  exit 1
fi
if [[ "$canonical_runtime_id" != "$legacy_runtime_id" ]]; then
  echo "ERROR: legacy runtime tag does not reference the canonical local image" >&2
  exit 1
fi

docker image inspect \
  remote-dev-base:local \
  remote-dev:local \
  codex-remote-dev-base:local \
  codex-remote-dev:local \
  --format '{{.RepoTags}} {{.Id}} {{.Size}}'
