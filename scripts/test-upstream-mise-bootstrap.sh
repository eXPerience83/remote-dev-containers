#!/usr/bin/env bash
# Test the *latest* checksum-verified mise against the real updater bootstrap.
# Never write repository files; all tool state is temporary and credential-free.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
# shellcheck disable=SC1091
source "$ROOT/versions.env"

[[ "$PYTHON_VERSION" =~ ^3[.]14[.][0-9]+$ ]] || {
  echo "ERROR: expected a reviewed exact Python 3.14 patch" >&2; exit 1;
}
for tool in gh jq curl sha256sum python3 timeout; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "ERROR: missing latest-mise canary prerequisite $tool" >&2; exit 1;
  }
done

release_json="$(gh api repos/jdx/mise/releases/latest)"
version="$(jq -er '.tag_name | select(test("^v[0-9]{4}[.][0-9]+[.][0-9]+$"))' <<<"$release_json")"
asset_name="mise-$version-linux-x64"
digest="$(jq -er --arg name "$asset_name" '.assets[] | select(.name == $name) | .digest | select(test("^sha256:[a-f0-9]{64}$"))' <<<"$release_json")"
size="$(jq -er --arg name "$asset_name" '.assets[] | select(.name == $name) | .size | select(type == "number" and . > 1000000 and . < 250000000)' <<<"$release_json")"
echo "Live mise bootstrap compatibility: $version ($size bytes), Python $PYTHON_VERSION"

scratch="$(mktemp -d -t remote-dev-mise-canary.XXXXXXXX)"
trap 'rm -rf -- "$scratch"' EXIT
for dir in bootstrap runtime config cache data home system tmp; do
  install -d -m 0700 "$scratch/$dir"
done
: >"$scratch/config/global.toml"
: >"$scratch/system/config.toml"

curl --fail --silent --show-error --location --retry 3 --retry-all-errors \
  --connect-timeout 10 --max-time 300 --max-filesize 250000000 \
  "https://github.com/jdx/mise/releases/download/$version/$asset_name" \
  --output "$scratch/mise"
expected_sha="$(printf '%s' "$digest" | cut -d: -f2)"
printf '%s  %s\n' "$expected_sha" "$scratch/mise" | sha256sum -c -
chmod 0700 "$scratch/mise"

cat >"$scratch/bootstrap/mise.toml" <<EOF
[settings]
lockfile = true
locked_verify_provenance = true
lockfile_platforms = ["linux-x64", "linux-arm64"]

[tools]
python = "$PYTHON_VERSION"
EOF

# Prevent a downloaded tool from inheriting CI GitHub credentials or user config.
run_mise() {
  timeout --signal=TERM --kill-after=30s 10m \
    env -i \
      PATH="$PATH" HOME="$scratch/home" \
      MISE_CACHE_DIR="$scratch/cache" \
      MISE_CONFIG_DIR="$scratch/config" \
      MISE_DATA_DIR="$scratch/data" \
      MISE_GLOBAL_CONFIG_FILE="$scratch/config/global.toml" \
      MISE_SYSTEM_DIR="$scratch/system" \
      MISE_SYSTEM_CONFIG_DIR="$scratch/system" \
      MISE_SYSTEM_CONFIG_FILE="$scratch/system/config.toml" \
      MISE_TMP_DIR="$scratch/tmp" \
      MISE_SAFE=1 MISE_HTTP_TIMEOUT=60s MISE_PYTHON_COMPILE=false \
      UV_PYTHON_DOWNLOADS=never \
      "$scratch/mise" "$@"
}

(
  cd "$scratch/bootstrap"
  run_mise lock --platform linux-x64,linux-arm64
)
python3 "$ROOT/scripts/validate-mise-bootstrap-lock.py" \
  --lock "$scratch/bootstrap/mise.lock" --python-version "$PYTHON_VERSION"
# Install exclusively from the validated private system lock, never an
# untrusted project lock (mise 2026.11.x MISE_SAFE=1 URL restrictions).
cp "$scratch/bootstrap/mise.toml" "$scratch/system/config.toml"
cp "$scratch/bootstrap/mise.lock" "$scratch/system/config.lock"
chmod 0600 "$scratch/system/config.toml" "$scratch/system/config.lock"
(
  cd "$scratch/runtime"
  run_mise install --locked
  python_dir="$(run_mise where "python@$PYTHON_VERSION")"
  [[ "$python_dir" == "$scratch/data/installs/python/$PYTHON_VERSION" ]] || {
    echo "ERROR: canary installed Python outside isolated mise data" >&2; exit 1;
  }
  [[ "$("$python_dir/bin/python3" --version)" == "Python $PYTHON_VERSION" ]] || {
    echo "ERROR: canary Python is not the reviewed version" >&2; exit 1;
  }
)
echo "OK latest verified mise locks and installs Python in isolated safe mode."
