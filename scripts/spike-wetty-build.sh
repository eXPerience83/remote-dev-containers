#!/usr/bin/env bash
# Manual, isolated research only; not used by production or normal builds.
set -euo pipefail
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "${WETTY_RESEARCH_ISOLATED:-}" == 1 ]] ||
  die 'Only run on a disposable credential-free runner (WETTY_RESEARCH_ISOLATED=1)'
for name in GITHUB_TOKEN GH_TOKEN NPM_TOKEN NODE_AUTH_TOKEN WEB_PASSWORD; do
  [[ -z "${!name:-}" ]] || die "Refusing to run with $name present"
done

root="$(cd "$(dirname "$0")/.." && pwd -P)"
# shellcheck source=versions.env
source "$root/versions.env"
[[ "$(node --version)" == "v$NODE_VERSION" ]] ||
  die "Require pinned Node v$NODE_VERSION"
for tool in git npm python3 cc make; do
  command -v "$tool" >/dev/null 2>&1 || die "Missing tool: $tool"
done

readonly tag=v4.2.1
readonly source_sha=116189487c52759afec2b40ff293631f64e1fb6e
readonly pnpm_version=9.4.0
scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$scratch/home" "$scratch/npm" "$scratch/store"
export HOME="$scratch/home" NPM_CONFIG_CACHE="$scratch/npm"
export NPM_CONFIG_USERCONFIG=/dev/null GIT_TERMINAL_PROMPT=0 HUSKY=0

git -c credential.helper= clone --depth 1 --branch "$tag" --no-checkout \
  https://github.com/butlerx/wetty.git "$scratch/wetty"
git -C "$scratch/wetty" checkout --detach --quiet "$source_sha"
[[ "$(git -C "$scratch/wetty" rev-parse HEAD)" == "$source_sha" ]] ||
  die "Upstream tag commit changed"
cd "$scratch/wetty"

python3 - <<'PY'
import json
from pathlib import Path
manifest = json.loads(Path("package.json").read_text())
lock = Path("pnpm-lock.yaml").read_text()
if manifest["name"] != "wetty":
    raise SystemExit("Unexpected source package")
if manifest["engines"]["node"] != "^22.23.4 || ^24.22.1 || >=26.12.1":
    raise SystemExit("Node support contract changed")
for pkg, expected in (
    ("'@xterm/xterm'", "6.0.0"),
    ("node-pty", "1.1.0"),
    ("socket.io", "4.8.4"),
    ("express", "5.3.0"),
):
    start = lock.find(f"      {pkg}:\n        specifier:")
    if start < 0 or f"        version: {expected}" not in lock[start:start+200]:
        raise SystemExit(f"Unexpected upstream lock for {pkg} {expected}")
print("Tag and dependency lock preflight: OK")
PY

# External upstream code executes here: disposable, unprivileged research only.
npm exec --yes --package="pnpm@$pnpm_version" -- pnpm install \
  --frozen-lockfile --store-dir "$scratch/store"
npm exec --yes --package="pnpm@$pnpm_version" -- pnpm build
test -f build/main.js
test -f build/server.js
node build/main.js --help >/dev/null
node --input-type=module - <<'JS'
import pty from 'node-pty';
const proc = pty.spawn('/bin/sh', ['-c', "printf 'WETTY_PTY_OK\\n'"], {
  name: 'xterm-256color',
  cols: 80,
  rows: 24,
  cwd: process.cwd(),
  env: { PATH: process.env.PATH ?? '/usr/bin:/bin' }
});
let output = '';
await new Promise((resolve, reject) => {
  const timeout = setTimeout(() => {
    proc.kill();
    reject(new Error('PTY timed out'));
  }, 8000);
  proc.onData(data => { output += data; });
  proc.onExit(({ exitCode }) => {
    clearTimeout(timeout);
    if (exitCode === 0 && output.includes('WETTY_PTY_OK')) resolve();
    else reject(new Error('Native PTY failed: exit ' + exitCode));
  });
});
console.log('Native node-pty spawn/output: OK');
JS
printf 'Gate 0 source build complete: %s (%s) on Node %s\n' \
  "$tag" "$source_sha" "$NODE_VERSION"
