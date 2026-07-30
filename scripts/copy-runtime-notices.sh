#!/usr/bin/env bash
set -euo pipefail
shopt -s lastpipe

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
  local copied_license=0

  python_prefix="$(python -c 'import sys; print(sys.base_prefix)')"
  if [[ ! -d "$python_prefix" ]]; then
    echo "ERROR: Python base prefix does not exist: $python_prefix" >&2
    exit 1
  fi

  # The locked install_only_stripped archive omits CPython's primary license.
  # Preserve the exact LICENSE from the matching CPython tag separately, then
  # supplement it with every license/notice file that the installed artifact
  # still provides for its bundled runtime and dependencies.
  copy_file "$third_party_root/components/python/LICENSE" "$destination_root/LICENSE.cpython.txt"

  find "$python_prefix" -maxdepth 7 -type f \
    \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' -o -name 'PYTHON.json' \) \
    -print0 |
    while IFS= read -r -d '' source; do
      relative="${source#"$python_prefix"/}"
      install -D -m 0644 "$source" "$destination_root/$relative"
      if [[ "${source##*/}" != "PYTHON.json" ]]; then
        copied_license=$((copied_license + 1))
      fi
    done

  if (( copied_license == 0 )); then
    echo "ERROR: no supplemental Python runtime license or notice files found below $python_prefix" >&2
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
  local source=""
  local relative=""
  local copied=0

  npm_root="$(npm root --global)"
  npm_package="$npm_root/npm"
  require_file "$npm_package/LICENSE"
  install -d -m 0755 "$destination_root"

  find "$npm_package" -type f \
    \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) \
    -print0 |
    while IFS= read -r -d '' source; do
      relative="${source#"$npm_package"/}"
      install -D -m 0644 "$source" "$destination_root/$relative"
      copied=$((copied + 1))
    done

  if (( copied == 0 )); then
    echo "ERROR: no npm package or dependency license files found below $npm_package" >&2
    exit 1
  fi

  node - "$npm_package" "$destination_root/DEPENDENCIES.txt" <<'NODE'
const fs = require('fs');
const path = require('path');

const root = process.argv[2];
const output = process.argv[3];
const packages = new Map();

function clean(value) {
  return String(value ?? '').replace(/[\t\r\n]+/g, ' ').trim();
}

function licenseText(value) {
  if (typeof value === 'string') return clean(value);
  if (Array.isArray(value)) return clean(value.map(licenseText).filter(Boolean).join(' OR '));
  if (value && typeof value === 'object') return clean(value.type || JSON.stringify(value));
  return 'NOASSERTION';
}

function visit(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.name === '.bin') continue;
    const candidate = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      visit(candidate);
      continue;
    }
    if (entry.name !== 'package.json') continue;

    const metadata = JSON.parse(fs.readFileSync(candidate, 'utf8'));
    if (!metadata.name || !metadata.version) continue;
    const declaredLicense = metadata.license ?? metadata.licenses;
    const row = [clean(metadata.name), clean(metadata.version), licenseText(declaredLicense)].join('\t');
    packages.set(row, row);
  }
}

visit(root);
if (packages.size === 0) {
  throw new Error(`no npm package metadata found below ${root}`);
}

const rows = [...packages.values()].sort((left, right) => left.localeCompare(right));
const content = [
  '# Generated from package.json files in the exact installed npm package.',
  '# name\tversion\tdeclared-license',
  ...rows,
  '',
].join('\n');
fs.writeFileSync(output, content, { encoding: 'utf8', mode: 0o644 });
NODE

  require_file "$destination_root/DEPENDENCIES.txt"
}

require_file "$project_license"
require_file "$third_party_root/components/codex/NOTICE"
require_file "$third_party_root/components/codex/SOURCE.env"
require_file "$third_party_root/components/github-cli/LICENSE"
require_file "$third_party_root/components/github-cli/SOURCE.env"
require_file "$third_party_root/components/ttyd/LICENSE"
require_file "$third_party_root/components/ttyd/SOURCE.env"
require_file "$third_party_root/components/mise/LICENSE"
require_file "$third_party_root/components/mise/SOURCE.env"
require_file "$third_party_root/components/python/LICENSE"
require_file "$third_party_root/components/python/SOURCE.env"
require_file "$third_party_root/components/uv/LICENSE-APACHE-2.0"
require_file "$third_party_root/components/uv/LICENSE-MIT"

copy_file "$project_license" "$third_party_root/components/codex/LICENSE-APACHE-2.0"
copy_python_notices
copy_node_notices
copy_npm_notices

chmod -R a=rX "$notice_root"
printf 'Copied bundled runtime notices into %s\n' "$third_party_root"
