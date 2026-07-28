#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"

MISE_BIN="${MISE_BIN:-mise}"
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

empty_global_config="$(mktemp)"
trap 'rm -f "$empty_global_config"' EXIT

(
  cd "$ROOT"
  MISE_GLOBAL_CONFIG_FILE="$empty_global_config" \
    MISE_SAFE=1 \
    MISE_HTTP_TIMEOUT="${MISE_HTTP_TIMEOUT:-60}" \
    timeout --signal=TERM --kill-after=30s "${MISE_LOCK_TIMEOUT:-10m}" \
    "$MISE_BIN" lock --platform linux-x64,linux-arm64
)

python3 "$ROOT/scripts/validate-mise-lock.py" --root "$ROOT"
echo "Regenerated mise.lock with mise $MISE_VERSION."
