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

# Admission executes the real, checksum-verified CLI with no inherited tokens,
# validates the generated two-platform lock, and attempts a strict locked install.
# Known regressions defer the mise upgrade; unexpected failures still fail CI.
candidate_version="$(printf '%s' "$version" | sed 's/^v//')"
selected="$(python3 "$ROOT/scripts/admit-mise-upstream.py" \
  --current "$MISE_VERSION" --candidate "$candidate_version" \
  --mise-bin "$scratch/mise" --python-version "$PYTHON_VERSION")"
if [[ "$selected" != "$MISE_VERSION" && "$selected" != "$candidate_version" ]]; then
  echo "ERROR: mise admission returned an unexpected version: $selected" >&2
  exit 1
fi
if [[ "$selected" == "$candidate_version" ]]; then
  echo "OK latest verified mise $selected meets the strict bootstrap contract."
else
  echo "DEFER latest mise $candidate_version; pinned $MISE_VERSION remains in use."
fi
