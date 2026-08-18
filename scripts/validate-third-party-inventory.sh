#!/usr/bin/env bash
set -euo pipefail

root="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
inventory="$root/third_party/inventory.json"
versions="$root/versions.env"

require_file() {
  local path="$1"
  if [[ ! -s "$path" ]]; then
    echo "ERROR: required file is missing or empty: $path" >&2
    exit 1
  fi
}

require_file "$inventory"
require_file "$root/third_party/README.md"
require_file "$root/third_party/optional-agents.md"

jq -e '
  .schema_version == 1
  and (.components | type == "array" and length > 0)
  and ([.components[].id] | length == (unique | length))
  and all(.components[];
    (.id | type == "string" and length > 0)
    and (.name | type == "string" and length > 0)
    and (.image_scope == "both" or .image_scope == "base" or .image_scope == "final")
    and (.version | type == "string" and length > 0)
    and (.source | type == "string" and length > 0)
    and (.license | type == "string" and length > 0)
    and (.notices | type == "array" and length > 0)
    and all(.notices[];
      (.path | type == "string" and length > 0)
      and (
        .source == "repository"
        or .source == "artifact"
        or .source == "runtime"
        or .source == "system"
      )
    )
  )
' "$inventory" >/dev/null

if [[ -s "$versions" ]]; then
  # shellcheck disable=SC1090
  source "$versions"

  while IFS=$'\t' read -r key expected; do
    actual="${!key:-}"
    if [[ -z "$actual" ]]; then
      echo "ERROR: inventory version key is absent from versions.env: $key" >&2
      exit 1
    fi
    if [[ "$actual" != "$expected" ]]; then
      echo "ERROR: $key is $actual in versions.env but $expected in the inventory" >&2
      exit 1
    fi
  done < <(jq -r '.components[] | select(.version_key != null) | [.version_key, .version] | @tsv' "$inventory")

  inventory_keys="$(
    jq -r '.components[] | .version_key // empty' "$inventory" | LC_ALL=C sort -u
  )"
  version_keys="$(
    sed -nE 's/^([A-Z0-9_]+_(VERSION|RELEASE_TAG))=.*/\1/p' "$versions" \
      | grep -v '^BASE_VERSION$' \
      | grep -v '^CONTEXT7_CLI_VERSION$' \
      | LC_ALL=C sort -u
  )"
  if [[ "$inventory_keys" != "$version_keys" ]]; then
    echo "ERROR: distributed tool version keys in versions.env and third_party/inventory.json differ" >&2
    diff -u <(printf '%s\n' "$version_keys") <(printf '%s\n' "$inventory_keys") >&2 || true
    exit 1
  fi
else
  # Docker builds mount only the files read by this validator. Compare effective
  # versions passed by the Dockerfile without requiring the complete repository.
  declare -A build_versions=(
    [GH_VERSION]="${REMOTE_DEV_GH_VERSION:-}"
    [TTYD_VERSION]="${REMOTE_DEV_TTYD_VERSION:-}"
    [MISE_VERSION]="${REMOTE_DEV_MISE_VERSION:-}"
    [PYTHON_VERSION]="${REMOTE_DEV_PYTHON_VERSION:-}"
  )
  for key in "${!build_versions[@]}"; do
    actual="${build_versions[$key]}"
    [[ -n "$actual" ]] || continue
    expected="$(jq -er --arg key "$key" '.components[] | select(.version_key == $key) | .version' "$inventory")"
    if [[ "$actual" != "$expected" ]]; then
      echo "ERROR: effective $key is $actual but the inventory records $expected" >&2
      exit 1
    fi
  done
fi

while IFS= read -r relative; do
  if [[ "$relative" == */ ]]; then
    if [[ ! -d "$root/third_party/$relative" ]] \
      || [[ -z "$(find "$root/third_party/$relative" -type f -size +0c -print -quit)" ]]; then
      echo "ERROR: preserved notice directory is missing or empty: third_party/$relative" >&2
      exit 1
    fi
  elif [[ ! -s "$root/third_party/$relative" ]]; then
    echo "ERROR: preserved notice file is missing or empty: third_party/$relative" >&2
    exit 1
  fi
done < <(
  jq -r '
    .components[].notices[]
    | select(.source == "repository" or .source == "artifact")
    | .path
  ' "$inventory"
)

printf 'Third-party inventory: OK (%s distributed components)\n' "$(jq '.components | length' "$inventory")"
