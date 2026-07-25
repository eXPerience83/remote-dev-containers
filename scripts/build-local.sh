#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"

bash "$ROOT/scripts/validate-version-pins.sh"

BASE_IMAGE="${BASE_IMAGE:-codex-remote-dev-base:local}"
CODEX_IMAGE="${CODEX_IMAGE:-codex-remote-dev:local}"
PLATFORM="${PLATFORM:-linux/amd64}"
PROJECT_VERSION="${PROJECT_VERSION:-$BASE_VERSION}"

if [[ -z "${SOURCE_REVISION+x}" ]]; then
  if git -C "$ROOT" rev-parse --verify HEAD >/dev/null 2>&1; then
    SOURCE_REVISION="$(git -C "$ROOT" rev-parse HEAD)"
    if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=normal)" ]]; then
      SOURCE_REVISION="${SOURCE_REVISION}-dirty"
    fi
  else
    SOURCE_REVISION=local-untracked
  fi
fi

common_args=(
  --platform "$PLATFORM"
  --build-arg "UBUNTU_VERSION=$UBUNTU_VERSION"
  --build-arg "BASE_VERSION=$BASE_VERSION"
  --build-arg "GH_VERSION=$GH_VERSION"
  --build-arg "TTYD_VERSION=$TTYD_VERSION"
  --build-arg "MISE_VERSION=$MISE_VERSION"
  --build-arg "PYTHON_VERSION=$PYTHON_VERSION"
  --build-arg "NODE_VERSION=$NODE_VERSION"
  --build-arg "UV_VERSION=$UV_VERSION"
)

docker build "${common_args[@]}" -t "$BASE_IMAGE" -f "$ROOT/images/base/Dockerfile" "$ROOT"
docker build \
  --platform "$PLATFORM" \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  --build-arg "CODEX_RELEASE_TAG=$CODEX_RELEASE_TAG" \
  --build-arg "PROJECT_VERSION=$PROJECT_VERSION" \
  --build-arg "SOURCE_REVISION=$SOURCE_REVISION" \
  -t "$CODEX_IMAGE" \
  -f "$ROOT/images/codex/Dockerfile" \
  "$ROOT"

docker run --rm --entrypoint /usr/local/bin/codex-smoke-test "$CODEX_IMAGE"
bash "$ROOT/scripts/runtime-smoke-test.sh" "$CODEX_IMAGE"
docker image inspect "$BASE_IMAGE" "$CODEX_IMAGE" --format '{{.RepoTags}} {{.Size}}'
