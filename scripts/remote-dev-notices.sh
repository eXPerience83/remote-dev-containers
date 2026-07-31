#!/usr/bin/env bash
set -euo pipefail

notice_root="${REMOTE_DEV_NOTICE_ROOT:-/usr/share/doc/remote-dev}"
third_party_root="$notice_root/third_party"
system_doc_root="${REMOTE_DEV_SYSTEM_DOC_ROOT:-/usr/share/doc}"
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

manifest_value() {
  local key="$1"
  shift
  local values=""
  values="$(grep -hE "^${key}=.+$" "$@" 2>/dev/null | cut -d= -f2- | LC_ALL=C sort -u || true)"
  if [[ -z "$values" ]] || [[ "$values" == *$'\n'* ]]; then
    echo "ERROR: build manifests must contain exactly one $key value" >&2
    return 1
  fi
  printf '%s\n' "$values"
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

git_blob_sha1() {
  local path="$1"
  local size=""
  size="$(wc -c < "$path")"
  size="${size//[[:space:]]/}"
  { printf 'blob %s\0' "$size"; cat "$path"; } | sha1sum | awk '{print $1}'
}

require_package_copyrights() {
  local packages=""
  local package=""
  if [[ -n "${REMOTE_DEV_INSTALLED_PACKAGES_FILE:-}" ]]; then
    if ! packages="$(cat "$REMOTE_DEV_INSTALLED_PACKAGES_FILE")"; then
      echo "ERROR: unable to read installed package list: $REMOTE_DEV_INSTALLED_PACKAGES_FILE" >&2
      return 1
    fi
  elif ! packages="$(dpkg-query -W -f='${Package}\n')"; then
    echo "ERROR: unable to enumerate installed Debian packages" >&2
    return 1
  fi
  if [[ -z "$packages" ]]; then
    echo "ERROR: installed Debian package list is empty" >&2
    return 1
  fi
  while IFS= read -r package; do
    [[ -n "$package" ]] || continue
    if ! require_file "$system_doc_root/$package/copyright"; then
      return 1
    fi
  done <<< "$packages"
}

check_inventory_location() {
  local location="$1"
  local path=""
  if [[ "$location" == *'<package>'* ]]; then
    require_package_copyrights
    return
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
  local expected_blob=""
  local actual_blob=""
  local key=""
  local location=""
  local component=""
  local component_scope=""
  local locked_version=""
  local effective_version=""
  local source_records=""
  local source_versions=""
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
    if capture_required_jq source_records "reviewed source records" \
      '.documents | select(type == "array" and length > 0) | .[] | [.path, .git_blob_sha1] | @tsv' "$source_lock"; then
      while IFS=$'\t' read -r path expected_blob; do
        path="$notice_root/$path"
        if ! require_file "$path"; then
          failed=1
          continue
        fi
        actual_blob="$(git_blob_sha1 "$path")"
        if [[ "$actual_blob" != "$expected_blob" ]]; then
          echo "ERROR: reviewed notice content differs from its locked blob identity: $path" >&2
          failed=1
        fi
      done <<< "$source_records"
    else
      failed=1
    fi

    if capture_required_jq source_versions "reviewed source component versions" \
      '.documents | group_by(.component)[] | . as $records | ($records | map(.version) | unique) as $versions | if ($versions | length) == 1 then [$records[0].component, $versions[0]] | @tsv else error("component has multiple reviewed versions") end' "$source_lock"; then
      while IFS=$'\t' read -r component locked_version; do
        if ! component_scope="$(jq -er --arg component "$component" \
          '.components[] | select(.id == $component) | .image_scope' "$inventory")"; then
          echo "ERROR: source-locked component has no image scope: $component" >&2
          failed=1
          continue
        fi
        if [[ "$component_scope" == "optional" ]] || \
          { (( has_codex == 0 )) && [[ "$component_scope" == "final" ]]; }; then
          continue
        fi
        if ! key="$(jq -er --arg component "$component" \
          '.components[] | select(.id == $component) | (.version_source.key // .version_source.mirror_env_key)' "$inventory")"; then
          echo "ERROR: source-locked component has no build-manifest version key: $component" >&2
          failed=1
          continue
        fi
        if ! effective_version="$(manifest_value "$key" "$manifest" "$codex_manifest")"; then
          failed=1
          continue
        fi
        if [[ "$effective_version" != "$locked_version" ]]; then
          echo "ERROR: installed $component version $effective_version differs from reviewed notices $locked_version" >&2
          failed=1
        fi
      done <<< "$source_versions"
    else
      failed=1
    fi
  fi

  if [[ -s "$inventory" ]]; then
    if capture_required_jq notice_locations "inventory notice locations" \
      ".components[] | $scope_filter | .notice_locations[]" "$inventory"; then
      local checked_package_family=0
      while IFS= read -r location; do
        if [[ "$location" == *'<package>'* ]]; then
          if (( checked_package_family == 1 )); then
            continue
          fi
          checked_package_family=1
        fi
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
  "") cat "$third_party_root/README.md" ;;
  --check) check_notices ;;
  --list) find "$notice_root" -type f -print | LC_ALL=C sort ;;
  --path) printf '%s\n' "$notice_root" ;;
  --versions) print_versions ;;
  --inventory-json) print_inventory_json ;;
  --help|-h) usage ;;
  *)
    echo "ERROR: unknown argument: $1" >&2
    usage >&2
    exit 2
    ;;
esac
