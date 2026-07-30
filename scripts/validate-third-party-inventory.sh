#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
inventory="$ROOT/third_party/inventory.json"
source_lock="$ROOT/third_party/sources.lock.json"

require_file() {
  local path="$1"
  if [[ ! -s "$path" ]]; then
    echo "ERROR: required legal inventory file is missing or empty: ${path#"$ROOT"/}" >&2
    exit 1
  fi
}

# CI and normal repository validation use the complete Python implementation.
if [[ -f "$ROOT/versions.env" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    exec python3 "$ROOT/scripts/legal-inventory.py" --root "$ROOT" validate
  elif command -v python >/dev/null 2>&1; then
    exec python "$ROOT/scripts/legal-inventory.py" --root "$ROOT" validate
  fi
fi

# The base Dockerfile runs this check before the mise Python runtime exists and
# deliberately mounts only legal/build inputs. Keep a fail-closed jq/git
# preflight here; the complete renderer/discovery/SBOM tests still run in CI.
require_file "$inventory"
require_file "$source_lock"
require_file "$ROOT/third_party/README.md"
require_file "$ROOT/third_party/optional-agents.md"
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required for legal inventory preflight" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "ERROR: git is required for legal source identity checks" >&2; exit 1; }

jq -e '.schema_version == 1 and (.components | type == "array" and length > 0)' "$inventory" >/dev/null
jq -e '.schema_version == 1 and (.documents | type == "array" and length > 0)' "$source_lock" >/dev/null

while IFS=$'\t' read -r path expected_blob; do
  require_file "$ROOT/$path"
  actual_blob="$(git hash-object "$ROOT/$path")"
  if [[ "$actual_blob" != "$expected_blob" ]]; then
    echo "ERROR: source-locked legal document differs from reviewed content: $path" >&2
    exit 1
  fi
done < <(jq -er '.documents[] | [.path, .git_blob_sha1] | @tsv' "$source_lock")

mapfile -t claimed_inputs < <(jq -er '[.components[].inputs[]] | unique[]' "$inventory")
mapfile -t aliases < <(jq -er '.docker_arg_aliases // {} | keys[]' "$inventory")
for dockerfile in "$ROOT/images/base/Dockerfile" "$ROOT/images/codex/Dockerfile"; do
  while IFS= read -r key; do
    if ! printf '%s\n' "${claimed_inputs[@]}" "${aliases[@]}" | grep -Fxq -- "$key"; then
      echo "ERROR: Docker version/checksum argument is not inventoried: $key" >&2
      exit 1
    fi
  done < <(sed -nE 's/^[[:space:]]*ARG ([A-Z][A-Z0-9_]*(VERSION|RELEASE_TAG|DIGEST|SHA256))=.*/\1/p' "$dockerfile")

done

mapfile -t claimed_markers < <(jq -er '.components[].download_url_markers[]?' "$inventory")
while IFS= read -r url; do
  owner_count=0
  for marker in "${claimed_markers[@]}"; do
    [[ "$url" == *"$marker"* ]] && owner_count=$((owner_count + 1))
  done
  if (( owner_count != 1 )); then
    echo "ERROR: direct-download URL must be claimed exactly once: $url" >&2
    exit 1
  fi
done < <(grep -rhoE 'https://[^"[:space:]]+/releases/download/[^"[:space:]]+' \
  "$ROOT/images/base/Dockerfile" "$ROOT/images/codex/Dockerfile" | LC_ALL=C sort -u)

mapfile -t locked_tools < <(sed -nE 's/^\[\[tools\.([^]]+)\]\]$/\1/p' "$ROOT/mise.lock" | LC_ALL=C sort -u)
mapfile -t claimed_tools < <(jq -er '.components[].version_source | select(.kind == "mise") | .tool' "$inventory" | LC_ALL=C sort -u)
if [[ "$(printf '%s\n' "${locked_tools[@]}")" != "$(printf '%s\n' "${claimed_tools[@]}")" ]]; then
  echo "ERROR: mise.lock tools and legal inventory claims differ" >&2
  diff -u <(printf '%s\n' "${locked_tools[@]}") <(printf '%s\n' "${claimed_tools[@]}") >&2 || true
  exit 1
fi

grep -Fq 'generated from `third_party/inventory.json`' "$ROOT/third_party/README.md" \
  || { echo "ERROR: third_party/README.md is not the generated inventory" >&2; exit 1; }

printf 'Third-party legal inventory preflight: OK\n'
