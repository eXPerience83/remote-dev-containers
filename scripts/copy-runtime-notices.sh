#!/usr/bin/env bash
set -euo pipefail

destination="${1:-/usr/share/doc/remote-dev/third_party/runtime}"

copy_notice_files() {
  local label="$1"
  local source_root="$2"
  local required="$3"
  local target_root="$destination/$label"
  local listing=""
  local source=""
  local relative=""
  local copied=0

  if [[ ! -d "$source_root" ]]; then
    if [[ "$required" == "required" ]]; then
      echo "ERROR: runtime root is missing for $label: $source_root" >&2
      exit 1
    fi
    return
  fi

  listing="$(mktemp)"
  find "$source_root" -maxdepth 8 -type f \
    \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) \
    -print0 > "$listing"

  while IFS= read -r -d '' source; do
    relative="${source#"$source_root"/}"
    install -D -m 0644 "$source" "$target_root/$relative"
    copied=$((copied + 1))
  done < "$listing"
  rm -f "$listing"

  if [[ "$required" == "required" && "$copied" -eq 0 ]]; then
    echo "ERROR: no runtime license or notice files found for $label below $source_root" >&2
    exit 1
  fi

  printf 'Copied %s runtime notice files for %s\n' "$copied" "$label"
}

mkdir -p "$destination"

python_root="$(python -c 'import sys; print(sys.base_prefix)')"
node_root="$(node -p 'require("path").dirname(require("path").dirname(process.execPath))')"
npm_root="$(npm root --global)/npm"

# The reviewed CPython license is stored in components/python/LICENSE. Copy any
# additional notices still present in the exact installed standalone artifact.
copy_notice_files python "$python_root" optional
copy_notice_files node "$node_root" required
copy_notice_files npm "$npm_root" required
