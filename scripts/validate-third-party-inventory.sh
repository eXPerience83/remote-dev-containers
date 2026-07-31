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

run_python_validation() {
  local python_bin="$1"
  "$python_bin" "$ROOT/scripts/test-legal-discovery-hardening.py"
  exec "$python_bin" "$ROOT/scripts/legal-inventory.py" --root "$ROOT" validate
}

if [[ -f "$ROOT/versions.env" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    run_python_validation python3
  elif command -v python >/dev/null 2>&1; then
    run_python_validation python
  fi
fi

require_file "$inventory"
require_file "$source_lock"
require_file "$ROOT/third_party/README.md"
require_file "$ROOT/third_party/optional-agents.md"
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required for legal inventory preflight" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "ERROR: git is required for legal source identity checks" >&2; exit 1; }

jq -e '.schema_version == 1 and (.components | type == "array" and length > 0)' "$inventory" >/dev/null
jq -e '.schema_version == 1 and (.documents | type == "array" and length > 0)' "$source_lock" >/dev/null

source_records=""
if ! source_records="$(jq -er '.documents | select(type == "array" and length > 0) | .[] | [.path, .git_blob_sha1] | @tsv' "$source_lock")" || [[ -z "$source_records" ]]; then
  echo "ERROR: reviewed legal source records are missing or invalid" >&2
  exit 1
fi
while IFS=$'\t' read -r path expected_blob; do
  require_file "$ROOT/$path"
  actual_blob="$(git hash-object "$ROOT/$path")"
  if [[ "$actual_blob" != "$expected_blob" ]]; then
    echo "ERROR: source-locked legal document differs from reviewed content: $path" >&2
    exit 1
  fi
done <<< "$source_records"

require_locked_component_version() {
  local env_name="$1"
  local component="$2"
  local effective="${!env_name:-}"
  local locked=""
  [[ -n "$effective" ]] || return 0
  if ! locked="$(jq -er --arg component "$component" \
    '[.documents[] | select(.component == $component) | .version] | unique | if length == 1 then .[0] else error("missing or conflicting reviewed versions") end' \
    "$source_lock")"; then
    echo "ERROR: unable to resolve one reviewed version for $component" >&2
    exit 1
  fi
  if [[ "$effective" != "$locked" ]]; then
    echo "ERROR: effective $component version $effective differs from reviewed legal sources $locked" >&2
    exit 1
  fi
}

require_locked_component_version REMOTE_DEV_GH_VERSION github-cli
require_locked_component_version REMOTE_DEV_TTYD_VERSION ttyd
require_locked_component_version REMOTE_DEV_MISE_VERSION mise
require_locked_component_version REMOTE_DEV_PYTHON_VERSION python-runtime

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
