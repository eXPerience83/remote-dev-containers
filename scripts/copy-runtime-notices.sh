#!/usr/bin/env bash
set -euo pipefail

notice_root="${REMOTE_DEV_NOTICE_ROOT:-/usr/share/doc/remote-dev}"
third_party_root="$notice_root/third_party"
project_license="${REMOTE_DEV_PROJECT_LICENSE:-$notice_root/LICENSE}"

require_file() {
  local path="$1"
  if [[ ! -s "$path" ]]; then
    echo "ERROR: required source notice is missing or empty: $path" >&2
    exit 1
  fi
}

copy_file() {
  local source="$1"
  local destination="$2"
  require_file "$source"
  install -D -m 0644 "$source" "$destination"
}

copy_python_notices() {
  local python_prefix=""
  local destination_root="$third_party_root/runtime/python"
  local source=""
  local relative=""
  local copied=0

  python_prefix="$(python -c 'import sys; print(sys.base_prefix)')"
  if [[ ! -d "$python_prefix" ]]; then
    echo "ERROR: Python base prefix does not exist: $python_prefix" >&2
    exit 1
  fi

  install -d -m 0755 "$destination_root"
  while IFS= read -r -d '' source; do
    relative="${source#"$python_prefix"/}"
    install -D -m 0644 "$source" "$destination_root/$relative"
    copied=$((copied + 1))
  done < <(
    find "$python_prefix" -maxdepth 7 -type f \
      \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' -o -name 'PYTHON.json' \) \
      -print0
  )

  if (( copied == 0 )); then
    echo "ERROR: no Python runtime license or notice files found below $python_prefix" >&2
    exit 1
  fi
}

copy_node_notices() {
  local node_root=""
  local destination_root="$third_party_root/runtime/node"

  node_root="$(node -p 'require("path").dirname(require("path").dirname(process.execPath))')"
  copy_file "$node_root/LICENSE" "$destination_root/LICENSE"
}

copy_npm_notices() {
  local npm_root=""
  local npm_package=""
  local destination_root="$third_party_root/runtime/npm"

  npm_root="$(npm root --global)"
  npm_package="$npm_root/npm"
  copy_file "$npm_package/LICENSE" "$destination_root/LICENSE"

  if [[ -s "$npm_package/DEPENDENCIES.md" ]]; then
    install -D -m 0644 "$npm_package/DEPENDENCIES.md" "$destination_root/DEPENDENCIES.md"
  fi
}

require_file "$project_license"
require_file "$third_party_root/components/codex/NOTICE"
require_file "$third_party_root/components/github-cli/LICENSE"
require_file "$third_party_root/components/ttyd/LICENSE"
require_file "$third_party_root/components/mise/LICENSE"
require_file "$third_party_root/components/uv/LICENSE-MIT"

copy_file "$project_license" "$third_party_root/components/codex/LICENSE-APACHE-2.0"
copy_file "$project_license" "$third_party_root/components/uv/LICENSE-APACHE-2.0"
copy_python_notices
copy_node_notices
copy_npm_notices

chmod -R a=rX "$notice_root"
printf 'Copied bundled runtime notices into %s\n' "$third_party_root"
