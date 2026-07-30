#!/usr/bin/env bash
set -euo pipefail

notice_root="${REMOTE_DEV_NOTICE_ROOT:-/usr/share/doc/remote-dev}"
third_party_root="$notice_root/third_party"

usage() {
  cat <<'EOF'
Usage: remote-dev-notices [--check|--list|--path|--versions|--help]

Without arguments, print the third-party inventory.

  --check     verify that required project, component and runtime notices exist
  --list      list all notice files below the canonical notice directory
  --path      print the canonical notice directory
  --versions  print the exact component versions and digests embedded at build time
  --help      show this help
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
  local manifest="$1"
  local key="$2"
  if ! grep -Eq "^${key}=.+$" "$manifest"; then
    echo "ERROR: build manifest is missing a non-empty $key value: $manifest" >&2
    return 1
  fi
}

check_notices() {
  local failed=0
  local path=""
  local key=""
  local manifest="$third_party_root/BUILD-VERSIONS.env"

  for path in \
    "$notice_root/LICENSE" \
    "$third_party_root/README.md" \
    "$third_party_root/optional-agents.md" \
    "$manifest" \
    "$third_party_root/components/codex/LICENSE-APACHE-2.0" \
    "$third_party_root/components/codex/NOTICE" \
    "$third_party_root/components/github-cli/LICENSE" \
    "$third_party_root/components/ttyd/LICENSE" \
    "$third_party_root/components/mise/LICENSE" \
    "$third_party_root/components/python/LICENSE" \
    "$third_party_root/components/uv/LICENSE-APACHE-2.0" \
    "$third_party_root/components/uv/LICENSE-MIT" \
    "$third_party_root/runtime/python/LICENSE.cpython.txt" \
    "$third_party_root/runtime/node/LICENSE" \
    "$third_party_root/runtime/npm/LICENSE" \
    "$third_party_root/runtime/npm/DEPENDENCIES.txt"; do
    if ! require_file "$path"; then
      failed=1
    fi
  done

  if [[ -s "$manifest" ]]; then
    for key in \
      PYTHON_VERSION \
      PYTHON_ARTIFACT_URL \
      PYTHON_ARTIFACT_CHECKSUM \
      NODE_VERSION \
      NODE_ARTIFACT_URL \
      NODE_ARTIFACT_CHECKSUM \
      UV_VERSION \
      UV_ARTIFACT_URL \
      UV_ARTIFACT_CHECKSUM; do
      if ! require_manifest_value "$manifest" "$key"; then
        failed=1
      fi
    done
  fi

  if command -v codex >/dev/null 2>&1; then
    if ! require_file "$third_party_root/CODEX-BUILD.env"; then
      failed=1
    fi
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
  --help|-h)
    usage
    ;;
  *)
    echo "ERROR: unknown argument: $1" >&2
    usage >&2
    exit 2
    ;;
esac
