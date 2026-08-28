#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$root/../.." && pwd)"
node_bin="${REMOTE_DEV_FRONTEND_NODE:-$(command -v node)}"

[[ "$($node_bin --version)" == v24.20.0 ]] || {
  echo "ERROR: ttyd client requires Node 24.20.0" >&2
  exit 1
}

python3 "$root/validate.py" --source-only

build_root="$(mktemp -d)"
trap 'rm -rf "$build_root"' EXIT
cache="$build_root/cache"
mkdir -p "$cache"

build_once() {
  local name="$1"
  local tree="$build_root/$name"
  local build_home="$build_root/${name}-home"
  cp -a "$root/upstream/html" "$tree"
  mkdir -p "$build_home"
  patch --batch --fuzz=0 --no-backup-if-mismatch -d "$tree" -p1 < "$root/patches/0001-remote-dev-client.patch"
  (
    cd "$tree"
    HOME="$build_home" YARN_CACHE_FOLDER="$cache" \
      "$node_bin" "$root/tooling/yarn-3.6.3.cjs" install --immutable --check-cache
    HOME="$build_home" YARN_CACHE_FOLDER="$cache" NODE_ENV=production SOURCE_DATE_EPOCH=1711767891 \
      "$node_bin" "$root/tooling/yarn-3.6.3.cjs" webpack --json > "$tree/dist-stats.json"
    python3 "$root/validate_stats.py" "$tree/dist-stats.json"
    HOME="$build_home" YARN_CACHE_FOLDER="$cache" NODE_ENV=production SOURCE_DATE_EPOCH=1711767891 \
      "$node_bin" "$root/tooling/yarn-3.6.3.cjs" gulp inline
  )
  [[ -s "$tree/dist/inline.html" ]] || {
    echo "ERROR: frontend build did not emit inline.html" >&2
    exit 1
  }
}

build_once first
build_once second
cmp "$build_root/first/dist/inline.html" "$build_root/second/dist/inline.html"
cmp "$build_root/first/dist/inline.html" "$root/dist/index.html"
python3 "$root/validate.py"
printf 'Remote Dev ttyd client reproducibility: OK\n'
