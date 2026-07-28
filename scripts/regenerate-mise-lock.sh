#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"

MISE_BIN="${MISE_BIN:-mise}"
MISE_HTTP_TIMEOUT_VALUE="${MISE_HTTP_TIMEOUT:-60}"
MISE_LOCK_TIMEOUT_VALUE="${MISE_LOCK_TIMEOUT:-10m}"

if ! command -v "$MISE_BIN" >/dev/null 2>&1; then
  echo "ERROR: mise is required to regenerate mise.lock" >&2
  exit 1
fi
if ! command -v timeout >/dev/null 2>&1; then
  echo "ERROR: GNU timeout is required to bound mise.lock regeneration" >&2
  exit 1
fi

installed_version="$("$MISE_BIN" --version | awk '{print $1}')"
if [[ "$installed_version" != "$MISE_VERSION" ]]; then
  cat >&2 <<EOF
ERROR: mise.lock must be generated with the pinned mise release.
Expected: $MISE_VERSION
Found:    $installed_version
Set MISE_BIN to the verified mise $MISE_VERSION binary and retry.
EOF
  exit 1
fi

for required_file in versions.env mise.toml mise.lock; do
  if [[ ! -f "$ROOT/$required_file" ]]; then
    echo "ERROR: required lock input is missing: $ROOT/$required_file" >&2
    exit 1
  fi
done

scratch="$(mktemp -d)"
trap 'rm -rf "${scratch:?}"' EXIT
workspace="$scratch/workspace"
mkdir -p \
  "$workspace" \
  "$scratch/cache" \
  "$scratch/config" \
  "$scratch/data" \
  "$scratch/system" \
  "$scratch/tmp"
cp "$ROOT/versions.env" "$ROOT/mise.toml" "$ROOT/mise.lock" "$workspace/"
: > "$scratch/config/global.toml"

# Clear caller-provided MISE_* settings before applying the small controlled set
# below. The lock is generated in a temporary config root so parent/profile files,
# user caches, installed plugins and partial writes cannot influence the result.
env_args=()
while IFS='=' read -r name _; do
  if [[ "$name" == MISE_* ]]; then
    env_args+=(-u "$name")
  fi
done < <(env)

(
  cd "$workspace"
  env "${env_args[@]}" \
    MISE_CACHE_DIR="$scratch/cache" \
    MISE_CONFIG_DIR="$scratch/config" \
    MISE_DATA_DIR="$scratch/data" \
    MISE_GLOBAL_CONFIG_FILE="$scratch/config/global.toml" \
    MISE_HTTP_TIMEOUT="$MISE_HTTP_TIMEOUT_VALUE" \
    MISE_SAFE=1 \
    MISE_SYSTEM_DIR="$scratch/system" \
    MISE_TMP_DIR="$scratch/tmp" \
    timeout --signal=TERM --kill-after=30s "$MISE_LOCK_TIMEOUT_VALUE" \
    "$MISE_BIN" lock --platform linux-x64,linux-arm64
)

python3 "$ROOT/scripts/validate-mise-lock.py" --root "$workspace"
install -m 0644 "$workspace/mise.lock" "$ROOT/mise.lock"
python3 "$ROOT/scripts/validate-mise-lock.py" --root "$ROOT"
echo "Regenerated mise.lock with mise $MISE_VERSION from isolated inputs."
