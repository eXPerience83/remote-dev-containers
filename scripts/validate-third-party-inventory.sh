#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
inventory="$ROOT/third_party/README.md"
optional_policy="$ROOT/third_party/optional-agents.md"
base_dockerfile="$ROOT/images/base/Dockerfile"
codex_dockerfile="$ROOT/images/codex/Dockerfile"

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

require_text "$base_dockerfile" 'apt-get install -y --no-install-recommends'
require_text "$codex_dockerfile" 'github.com/openai/codex/releases/download'
require_text "$base_dockerfile" 'github.com/cli/cli/releases/download'
require_text "$base_dockerfile" 'github.com/tsl0922/ttyd/releases/download'
require_text "$base_dockerfile" 'github.com/jdx/mise/releases/download'
require_text "$ROOT/scripts/copy-runtime-notices.sh" 'DEPENDENCIES.md'
require_text "$ROOT/scripts/remote-dev-notices.sh" 'runtime/npm/DEPENDENCIES.md'

for dockerfile in "$base_dockerfile" "$codex_dockerfile"; do
  require_text "$dockerfile" 'org.opencontainers.image.licenses="Apache-2.0"'
  require_text "$dockerfile" 'io.github.experience83.remote-dev.license-scope="Remote Dev project code only; bundled components retain upstream terms"'
  require_text "$dockerfile" 'io.github.experience83.remote-dev.third-party-notices="/usr/share/doc/remote-dev/third_party"'
done

if grep -Fqi 'placeholder' "$inventory"; then
  echo "ERROR: third_party/README.md must be a reviewed inventory, not a placeholder" >&2
  exit 1
fi

if grep -FRq 'LicenseRef-ThirdParty-Notices' "$base_dockerfile" "$codex_dockerfile"; then
  echo "ERROR: OCI license metadata must use an SPDX project license and a separate notice-scope annotation" >&2
  exit 1
fi

printf 'Third-party inventory and optional-agent policy: OK\n'
