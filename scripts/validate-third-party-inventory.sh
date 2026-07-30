#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
inventory="$ROOT/third_party/README.md"
optional_policy="$ROOT/third_party/optional-agents.md"

require_file() {
  local path="$1"
  if [[ ! -s "$path" ]]; then
    echo "ERROR: required third-party file is missing or empty: ${path#"$ROOT"/}" >&2
    exit 1
  fi
}

require_text() {
  local path="$1"
  local text="$2"
  if ! grep -Fq -- "$text" "$path"; then
    echo "ERROR: ${path#"$ROOT"/} must contain: $text" >&2
    exit 1
  fi
}

require_file "$inventory"
require_file "$optional_policy"

for file in \
  third_party/components/codex/NOTICE \
  third_party/components/github-cli/LICENSE \
  third_party/components/ttyd/LICENSE \
  third_party/components/mise/LICENSE \
  third_party/components/uv/LICENSE-MIT; do
  require_file "$ROOT/$file"
done

for variable in \
  UBUNTU_VERSION \
  UBUNTU_DIGEST \
  CODEX_RELEASE_TAG \
  GH_VERSION \
  TTYD_VERSION \
  MISE_VERSION \
  PYTHON_VERSION \
  NODE_VERSION \
  NPM_VERSION \
  UV_VERSION; do
  require_text "$inventory" "\`$variable\`"
done

for component in \
  'OpenAI Codex CLI' \
  'GitHub CLI' \
  'ttyd' \
  'mise' \
  'Python runtime' \
  'Node.js runtime' \
  'npm CLI' \
  'uv'; do
  require_text "$inventory" "$component"
done

for tool in node python uv; do
  require_text "$ROOT/mise.lock" "[[tools.$tool]]"
done

require_text "$optional_policy" 'must not contain the vendor binary or package'
require_text "$optional_policy" 'must never download optional software silently'
require_text "$optional_policy" 'Antigravity CLI'
require_text "$optional_policy" 'not bundled and not currently supported'
require_text "$optional_policy" 'Claude Code'
require_text "$optional_policy" 'not bundled, installed, advertised or supported'
require_text "$optional_policy" 'https://antigravity.google/terms'
require_text "$optional_policy" 'https://policies.google.com/privacy'

require_text "$ROOT/images/base/Dockerfile" 'apt-get install -y --no-install-recommends'
require_text "$ROOT/images/codex/Dockerfile" 'github.com/openai/codex/releases/download'
require_text "$ROOT/images/base/Dockerfile" 'github.com/cli/cli/releases/download'
require_text "$ROOT/images/base/Dockerfile" 'github.com/tsl0922/ttyd/releases/download'
require_text "$ROOT/images/base/Dockerfile" 'github.com/jdx/mise/releases/download'

if grep -Fqi 'placeholder' "$inventory"; then
  echo "ERROR: third_party/README.md must be a reviewed inventory, not a placeholder" >&2
  exit 1
fi

printf 'Third-party inventory and optional-agent policy: OK\n'
