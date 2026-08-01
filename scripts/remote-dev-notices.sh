#!/usr/bin/env bash
set -euo pipefail

notice_root="${REMOTE_DEV_NOTICE_ROOT:-/usr/share/doc/remote-dev}"
third_party_root="$notice_root/third_party"
inventory="$third_party_root/inventory.json"

usage() {
  cat <<'EOF'
Usage: remote-dev-notices [--check|--list|--path|--versions|--inventory-json|--help]

Without arguments, print the human-readable third-party notice guide.
EOF
}

require_file() {
  local path="$1"
  if [[ ! -s "$path" ]]; then
    echo "ERROR: required notice file is missing or empty: $path" >&2
    return 1
  fi
}

require_directory() {
  local path="$1"
  if [[ ! -d "$path" ]] || [[ -z "$(find "$path" -type f -size +0c -print -quit)" ]]; then
    echo "ERROR: required notice directory is missing or empty: $path" >&2
    return 1
  fi
}

selected_scope() {
  case "${REMOTE_DEV_NOTICE_IMAGE_SCOPE:-auto}" in
    base|final) printf '%s\n' "$REMOTE_DEV_NOTICE_IMAGE_SCOPE" ;;
    auto)
      if command -v codex >/dev/null 2>&1; then
        printf 'final\n'
      else
        printf 'base\n'
      fi
      ;;
    *)
      echo "ERROR: REMOTE_DEV_NOTICE_IMAGE_SCOPE must be auto, base or final" >&2
      return 1
      ;;
  esac
}

check_notices() {
  local scope=""
  local source=""
  local relative=""
  local path=""
  local failed=0
  local actual=""
  local key=""
  local expected=""
  local -a manifests=()

  scope="$(selected_scope)"

  for path in \
    "$notice_root/LICENSE" \
    "$third_party_root/README.md" \
    "$third_party_root/optional-agents.md" \
    "$inventory"; do
    require_file "$path" || failed=1
  done

  if ! jq -e '.schema_version == 1 and (.components | type == "array" and length > 0)' "$inventory" >/dev/null; then
    echo "ERROR: invalid third-party inventory: $inventory" >&2
    failed=1
  fi

  while IFS=$'\t' read -r source relative; do
    case "$source" in
      repository|artifact|runtime)
        path="$third_party_root/$relative"
        if [[ "$relative" == */ ]]; then
          require_directory "$path" || failed=1
        else
          require_file "$path" || failed=1
        fi
        ;;
      system)
        # Ubuntu package notices are retained in package-owned locations. Check a
        # representative package here; the SBOM remains the package inventory.
        require_file "${REMOTE_DEV_SYSTEM_DOC_ROOT:-/usr/share/doc}/bash/copyright" || failed=1
        ;;
      *)
        echo "ERROR: unsupported notice source in inventory: $source" >&2
        failed=1
        ;;
    esac
  done < <(
    jq -r --arg scope "$scope" '
      .components[]
      | select(.image_scope == "both" or .image_scope == $scope)
      | .notices[]
      | [.source, .path]
      | @tsv
    ' "$inventory"
  )

  manifests=("$third_party_root/BUILD-VERSIONS.env")
  if [[ "$scope" == "final" ]]; then
    manifests+=("$third_party_root/CODEX-BUILD.env")
  fi
  for path in "${manifests[@]}"; do
    require_file "$path" || failed=1
  done

  while IFS=$'\t' read -r key expected; do
    actual="$(
      grep -hE "^${key}=.+$" "${manifests[@]}" 2>/dev/null \
        | cut -d= -f2- \
        | LC_ALL=C sort -u
    )"
    if [[ -z "$actual" || "$actual" == *$'\n'* ]]; then
      echo "ERROR: build manifests must contain exactly one $key value" >&2
      failed=1
    elif [[ "$actual" != "$expected" ]]; then
      echo "ERROR: installed $key is $actual but the reviewed inventory records $expected" >&2
      failed=1
    fi
  done < <(
    jq -r --arg scope "$scope" '
      .components[]
      | select(.image_scope == "both" or .image_scope == $scope)
      | select(.version_key != null)
      | [.version_key, .version]
      | @tsv
    ' "$inventory"
  )

  if (( failed != 0 )); then
    return 1
  fi

  printf 'Third-party notices: OK (%s image)\n' "$scope"
}

case "${1:-}" in
  "") cat "$third_party_root/README.md" ;;
  --check) check_notices ;;
  --list) find "$notice_root" -type f -print | LC_ALL=C sort ;;
  --path) printf '%s\n' "$notice_root" ;;
  --versions)
    if [[ -s "$third_party_root/BUILD-VERSIONS.env" ]]; then
      cat "$third_party_root/BUILD-VERSIONS.env"
      if [[ -s "$third_party_root/CODEX-BUILD.env" ]]; then
        cat "$third_party_root/CODEX-BUILD.env"
      fi
    else
      jq -r '.components[] | [.id, .version] | @tsv' "$inventory"
    fi
    ;;
  --inventory-json) cat "$inventory" ;;
  --help|-h) usage ;;
  *)
    echo "ERROR: unknown argument: $1" >&2
    usage >&2
    exit 2
    ;;
esac
