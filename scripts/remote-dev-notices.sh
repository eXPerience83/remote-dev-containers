#!/usr/bin/env bash
set -euo pipefail

notice_root="${REMOTE_DEV_NOTICE_ROOT:-/usr/share/doc/remote-dev}"
third_party_root="$notice_root/third_party"
inventory="$third_party_root/inventory.json"
source_lock="$third_party_root/sources.lock.json"

usage() {
  cat <<'EOF'
Usage: remote-dev-notices [--check|--list|--path|--versions|--inventory-json|--help]

Without arguments, print the generated third-party inventory.

  --check           verify required project, component and runtime notices
  --list            list every notice file below the canonical directory
  --path            print the canonical notice directory
  --versions        print exact component versions and digests embedded at build time
  --inventory-json  print the machine-readable inventory and reviewed source lock
  --help            show this help
EOF
}

require_file() {
  local path="$1"
  if [[ ! -s "$path" ]]; then
    echo "ERROR: required notice file is missing or empty: $path" >&2
    return 1
  fi
}

require_nonempty_directory() {
  local path="$1"
  if [[ ! -d "$path" ]] || ! find "$path" -type f -size +0c -print -quit | grep -q .; then
    echo "ERROR: required notice directory has no non-empty files: $path" >&2
    return 1
  fi
}

require_python_runtime_license() {
  local path="$1"
  if [[ ! -d "$path" ]] || ! find "$path" -type f \
    \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) \
    ! -name 'LICENSE.cpython.txt' -size +0c -print -quit | grep -q .; then
    echo "ERROR: required supplemental Python runtime license or notice is missing below: $path" >&2
    return 1
  fi
}

require_manifest_value() {
  local key="$1"
  shift
  local manifest=""
  for manifest in "$@"; do
    if [[ -s "$manifest" ]] && grep -Eq "^${key}=.+$" "$manifest"; then
      return 0
    fi
  done
  echo "ERROR: build manifests are missing a non-empty $key value" >&2
  return 1
}

capture_required_jq() {
  local output_name="$1"
  local description="$2"
  local filter="$3"
  local file="$4"
  local output=""

  if ! output="$(jq -er "$filter" "$file")" || [[ -z "$output" ]]; then
    echo "ERROR: $description query failed or returned no values: $file" >&2
    return 1
  fi
  printf -v "$output_name" '%s' "$output"
}

check_inventory_location() {
  local location="$1"
  local path=""

  # This is a documented package-family path rather than a single file.
  if [[ "$location" == *'<package>'* ]]; then
    return 0
  fi
  if [[ "$location" == /* ]]; then
    path="$location"
  else
    path="$third_party_root/$location"
  fi
  if [[ "$location" == */ ]]; then
    require_nonempty_directory "$path"
  else
    require_file "$path"
  fi
}

check_notices() {
  local failed=0
  local path=""
  local key=""
  local location=""
  local source_paths=""
  local notice_locations=""
  local input_keys=""
  local manifest="$third_party_root/BUILD-VERSIONS.env"
  local codex_manifest="$third_party_root/CODEX-BUILD.env"
  local has_codex=0
  local scope_filter='select(.image_scope == "base" or .image_scope == "both" or .image_scope == "project")'

  if command -v codex >/dev/null 2>&1; then
    has_codex=1
    scope_filter='select(.image_scope != "optional")'
  fi

  for path in \
    "$notice_root/LICENSE" \
    "$third_party_root/README.md" \
    "$third_party_root/optional-agents.md" \
    "$inventory" \
    "$source_lock" \
    "$manifest"; do
    if ! require_file "$path"; then
      failed=1
    fi
  done

  if [[ -s "$inventory" ]] && ! jq -e '.schema_version == 1 and (.components | type == "array" and length > 0)' "$inventory" >/dev/null; then
    echo "ERROR: invalid machine-readable inventory: $inventory" >&2
    failed=1
  fi
  if [[ -s "$source_lock" ]] && ! jq -e '.schema_version == 1 and (.documents | type == "array" and length > 0)' "$source_lock" >/dev/null; then
    echo "ERROR: invalid reviewed source lock: $source_lock" >&2
    failed=1
  fi

  if [[ -s "$source_lock" ]]; then
    if capture_required_jq source_paths "reviewed source paths" \
      '.documents | select(type == "array" and length > 0) | .[].path' "$source_lock"; then
      while IFS= read -r path; do
        if ! require_file "$notice_root/$path"; then
          failed=1
        fi
      done <<< "$source_paths"
    else
      failed=1
    fi
  fi

  if [[ -s "$inventory" ]]; then
    if capture_required_jq notice_locations "inventory notice locations" \
      ".components[] | $scope_filter | .notice_locations[]" "$inventory"; then
      while IFS= read -r location; do
        if ! check_inventory_location "$location"; then
          failed=1
        fi
      done <<< "$notice_locations"
    else
      failed=1
    fi

    if capture_required_jq input_keys "inventory build inputs" \
      ".components[] | $scope_filter | .inputs[]" "$inventory"; then
      while IFS= read -r key; do
        if ! require_manifest_value "$key" "$manifest" "$codex_manifest"; then
          failed=1
        fi
      done < <(printf '%s\n' "$input_keys" | LC_ALL=C sort -u)
    else
      failed=1
    fi
  fi

  if (( has_codex == 1 )) && ! require_file "$codex_manifest"; then
    failed=1
  fi

  for path in \
    "$third_party_root/runtime/python" \
    "$third_party_root/runtime/npm"; do
    if ! require_nonempty_directory "$path"; then
      failed=1
    fi
  done
  if ! require_python_runtime_license "$third_party_root/runtime/python"; then
    failed=1
  fi

  if (( failed != 0 )); then
    return 1
  fi

  printf 'Third-party notices: OK (%s)\n' "$third_party_root"
}

print_versions() {
  require_file "$third_party_root/BUILD-VERSIONS.env"
  cat "$third_party_root/BUILD-VERSIONS.env"
  if [[ -s "$third_party_root/CODEX-BUILD.env" ]]; then
    cat "$third_party_root/CODEX-BUILD.env"
  fi
}

print_inventory_json() {
  require_file "$inventory"
  require_file "$source_lock"
  jq -n \
    --slurpfile inventory "$inventory" \
    --slurpfile sources "$source_lock" \
    '{inventory: $inventory[0], reviewed_sources: $sources[0]}'
}

case "${1:-}" in
  "")
    cat "$third_party_root/README.md"
    ;;
  --check)
    check_notices
    ;;
  --list)
    find "$notice_root" -type f -print | LC_ALL=C sort
    ;;
  --path)
    printf '%s\n' "$notice_root"
    ;;
  --versions)
    print_versions
    ;;
  --inventory-json)
    print_inventory_json
    ;;
  --help|-h)
    usage
    ;;
  *)
    echo "ERROR: unknown argument: $1" >&2
    usage >&2
    exit 2
    ;;
esac
