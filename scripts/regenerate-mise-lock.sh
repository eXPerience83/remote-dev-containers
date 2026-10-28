#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"

MISE_BIN="${MISE_BIN:-mise}"
MISE_HTTP_TIMEOUT_VALUE="${MISE_HTTP_TIMEOUT:-60s}"
MISE_LOCK_TIMEOUT_VALUE="${MISE_LOCK_TIMEOUT:-10m}"

if [[ ! "$MISE_HTTP_TIMEOUT_VALUE" =~ ^[1-9][0-9]*(ms|s|m|h)$ ]]; then
  echo "ERROR: MISE_HTTP_TIMEOUT must be a positive simple duration such as 60s: $MISE_HTTP_TIMEOUT_VALUE" >&2
  exit 1
fi
if [[ ! "$MISE_LOCK_TIMEOUT_VALUE" =~ ^[1-9][0-9]*(s|m|h|d)$ ]]; then
  echo "ERROR: MISE_LOCK_TIMEOUT must be a positive GNU timeout duration such as 10m: $MISE_LOCK_TIMEOUT_VALUE" >&2
  exit 1
fi
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

UV_BIN="${UV_BIN:-$(mise which uv)}"
UV_BIN="$(realpath "$UV_BIN")"
if [[ "$("$UV_BIN" --version | awk '{print $2}')" != "$UV_VERSION" ]]; then
  echo "ERROR: graph regeneration requires uv $UV_VERSION; set UV_BIN to the verified binary" >&2
  exit 1
fi

for required_file in versions.env mise.toml mise.lock; do
  if [[ ! -f "$ROOT/$required_file" ]]; then
    echo "ERROR: required lock input is missing: $ROOT/$required_file" >&2
    exit 1
  fi
done

scratch="$(mktemp -d)"
replacement=""
cleanup() {
  if [[ -n "$replacement" ]]; then
    rm -f -- "$replacement"
  fi
  rm -rf -- "${scratch:?}"
}
trap cleanup EXIT
workspace="$scratch/workspace"
mkdir -p \
  "$workspace" \
  "$scratch/cache" \
  "$scratch/config" \
  "$scratch/data" \
  "$scratch/system" \
  "$scratch/tmp" \
  "$scratch/bootstrap"
cp "$ROOT/versions.env" "$ROOT/mise.toml" "$ROOT/mise.lock" "$workspace/"
cp -R "$ROOT/.mise" "$workspace/.mise"
: > "$scratch/config/global.toml"

# Clear caller-provided MISE_* settings before applying the small controlled set
# below. The lock is generated in a temporary config root so parent/profile files,
# user caches, installed plugins and partial writes cannot influence the result.
env_args=()
while IFS='=' read -r -d '' name _; do
  if [[ "$name" == MISE_* ]]; then
    env_args+=(-u "$name")
  fi
done < <(env -0)

# A PyPI uv dependency graph needs the exact administrative Python available
# locally. First lock Python alone, validate its *actual* artifacts for both
# platforms, and install only that verified x64 runtime in the isolated data dir.
# uv remains forbidden from fetching a second, independently selected Python.
cat > "$scratch/bootstrap/mise.toml" <<EOF
[settings]
lockfile = true
locked_verify_provenance = true
lockfile_platforms = ["linux-x64", "linux-arm64"]

[tools]
python = "$PYTHON_VERSION"
EOF

run_isolated_mise() {
  env "${env_args[@]}" \
    PATH="$(dirname "$UV_BIN"):$PATH" \
    MISE_CACHE_DIR="$scratch/cache" \
    MISE_CONFIG_DIR="$scratch/config" \
    MISE_DATA_DIR="$scratch/data" \
    MISE_GLOBAL_CONFIG_FILE="$scratch/config/global.toml" \
    MISE_HTTP_TIMEOUT="$MISE_HTTP_TIMEOUT_VALUE" \
    MISE_PYTHON_COMPILE=false \
    MISE_SAFE=1 \
    MISE_SYSTEM_DIR="$scratch/system" \
    MISE_TMP_DIR="$scratch/tmp" \
    UV_PYTHON_DOWNLOADS=never \
    "$@"
}

(
  cd "$scratch/bootstrap"
  run_isolated_mise timeout --signal=TERM --kill-after=30s "$MISE_LOCK_TIMEOUT_VALUE" \
    "$MISE_BIN" lock --platform linux-x64,linux-arm64
)

# A bootstrap lock is deliberately Python-only, so the full validator cannot
# check it. Reuse its exact locked-artifact policy before installing anything.
python3 - "$ROOT/scripts/validate-mise-lock.py" "$scratch/bootstrap/mise.lock" "$PYTHON_VERSION" <<'PY'
import importlib.util
import sys
import tomllib
from pathlib import Path

spec = importlib.util.spec_from_file_location("mise_lock_validator", sys.argv[1])
assert spec is not None and spec.loader is not None
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
with Path(sys.argv[2]).open("rb") as handle:
    lock = tomllib.load(handle)
validator.require_exact_keys(lock, {"lockfile_version", "tools"}, "bootstrap lock")
if lock["lockfile_version"] != 3 or not isinstance(lock["tools"], dict):
    validator.fail("bootstrap must use mise.lock version 3 with a tool mapping")
validator.require_exact_keys(lock["tools"], {"python"}, "bootstrap tools")
validator.validate_tool_entry("python", sys.argv[3], lock["tools"]["python"])
PY

(
  cd "$scratch/bootstrap"
  run_isolated_mise timeout --signal=TERM --kill-after=30s "$MISE_LOCK_TIMEOUT_VALUE" \
    "$MISE_BIN" install --locked "python@$PYTHON_VERSION"
)
python_dir="$(cd "$scratch/bootstrap" && run_isolated_mise "$MISE_BIN" where "python@$PYTHON_VERSION")"
python_dir="$(realpath "$python_dir")"
if [[ "$python_dir" != "$scratch/data/"* || ! -x "$python_dir/bin/python3" ]]; then
  echo "ERROR: locked administrative Python was not installed inside the isolated mise data directory" >&2
  exit 1
fi
if [[ "$("$python_dir/bin/python3" --version)" != "Python $PYTHON_VERSION" ]]; then
  echo "ERROR: isolated Python interpreter does not match pinned $PYTHON_VERSION" >&2
  exit 1
fi

(
  cd "$workspace"
  run_isolated_mise env PATH="$python_dir/bin:$(dirname "$UV_BIN"):$PATH" \
    timeout --signal=TERM --kill-after=30s "$MISE_LOCK_TIMEOUT_VALUE" \
    "$MISE_BIN" lock --platform linux-x64,linux-arm64
)

python3 "$ROOT/scripts/validate-mise-lock.py" --root "$workspace"
# Content-addressed graph directories are published before the referencing lock.
# Keep older directories: a failed replacement must leave the previous lock usable.
cp -R "$workspace/.mise/." "$ROOT/.mise/"
replacement="$(mktemp "$ROOT/.mise.lock.tmp.XXXXXX")"
install -m 0644 "$workspace/mise.lock" "$replacement"
mv -f -- "$replacement" "$ROOT/mise.lock"
replacement=""
python3 "$ROOT/scripts/validate-mise-lock.py" --root "$ROOT"

# Maintain separate, exact full-distribution legal evidence for both Python lines.
# These sources may carry different dependency license texts and must never share
# one mutable notice tree.
for python_version in "$PYTHON_VERSION" "$PYTHON_315_VERSION"; do
  case "$python_version" in
    3.14.*)
      notice_dir="$ROOT/third_party/components/python-build-standalone" ;;
    3.15.*)
      notice_dir="$ROOT/third_party/components/python-build-standalone-315" ;;
    *)
      echo "ERROR: unreviewed Python notice line: $python_version" >&2
      exit 1 ;;
  esac
  notice_args=(--python-version "$python_version" --output "$notice_dir")
  if ! python3 "$ROOT/scripts/compact-python-runtime-notices.py" --check "${notice_args[@]}"; then
    if ! command -v zstd >/dev/null 2>&1; then
      if [[ "${CI:-}" == "true" ]] && command -v sudo >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y --no-install-recommends zstd
      else
        echo "ERROR: zstd is required to refresh Python runtime legal metadata." >&2
        exit 1
      fi
    fi
    python3 "$ROOT/scripts/sync-python-runtime-notices.py" --write "${notice_args[@]}"
    python3 "$ROOT/scripts/compact-python-runtime-notices.py" --write "${notice_args[@]}"
  fi
  python3 "$ROOT/scripts/compact-python-runtime-notices.py" --check "${notice_args[@]}"
done

echo "Regenerated mise.lock with mise $MISE_VERSION from isolated inputs."
