#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
inventory="$ROOT/third_party/README.md"
optional_policy="$ROOT/third_party/optional-agents.md"
base_dockerfile="$ROOT/images/base/Dockerfile"
codex_dockerfile="$ROOT/images/codex/Dockerfile"
codex_notice="$ROOT/third_party/components/codex/NOTICE"
codex_source="$ROOT/third_party/components/codex/SOURCE.env"
python_license="$ROOT/third_party/components/python/LICENSE"
python_source="$ROOT/third_party/components/python/SOURCE.env"

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

read_record_value() {
  local path="$1"
  local key="$2"
  local value=""

  if ! value="$(
    awk -F= -v key="$key" '
      $1 == key {
        count += 1
        sub(/^[^=]*=/, "")
        value = $0
      }
      END {
        if (count != 1 || value == "") exit 1
        print value
      }
    ' "$path"
  )"; then
    echo "ERROR: ${path#"$ROOT"/} must contain exactly one non-empty $key value" >&2
    exit 1
  fi

  printf '%s\n' "$value"
}

locked_tool_version() {
  local tool="$1"
  local section="[[tools.${tool}]]"
  local version=""

  if ! version="$(
    awk -v section="$section" '
      /^\[\[tools\.[^]]+\]\]$/ {
        in_section = ($0 == section)
        if (in_section) section_count += 1
        next
      }
      in_section && /^version = "[^"]+"$/ {
        version_count += 1
        value = $0
        sub(/^version = "/, "", value)
        sub(/"$/, "", value)
      }
      END {
        if (section_count != 1 || version_count != 1 || value == "") exit 1
        print value
      }
    ' "$ROOT/mise.lock"
  )"; then
    echo "ERROR: mise.lock must contain exactly one versioned $tool entry" >&2
    exit 1
  fi

  printf '%s\n' "$version"
}

require_file "$inventory"
require_file "$optional_policy"
require_file "$ROOT/scripts/print-locked-runtime-artifacts.py"

# Full repository validation also checks workflow triggers and synchronized
# defaults. Docker deliberately excludes .github from its build context, so the
# image-context pass validates only the files and effective-value manifests that
# can actually be embedded in the image.
if [[ -d "$ROOT/.github/workflows" ]]; then
  bash "$ROOT/scripts/validate-version-pins.sh"
fi

for file in \
  third_party/components/codex/NOTICE \
  third_party/components/codex/SOURCE.env \
  third_party/components/github-cli/LICENSE \
  third_party/components/ttyd/LICENSE \
  third_party/components/mise/LICENSE \
  third_party/components/python/LICENSE \
  third_party/components/python/SOURCE.env \
  third_party/components/uv/LICENSE-APACHE-2.0 \
  third_party/components/uv/LICENSE-MIT; do
  require_file "$ROOT/$file"
done

codex_release_tag="$(sed -n 's/^ARG CODEX_RELEASE_TAG=//p' "$codex_dockerfile")"
if [[ -z "$codex_release_tag" || "$codex_release_tag" == *$'\n'* ]]; then
  echo "ERROR: images/codex/Dockerfile must define exactly one CODEX_RELEASE_TAG default" >&2
  exit 1
fi

recorded_codex_tag="$(read_record_value "$codex_source" CODEX_RELEASE_TAG)"
recorded_codex_url="$(read_record_value "$codex_source" CODEX_NOTICE_URL)"
recorded_codex_blob="$(read_record_value "$codex_source" CODEX_NOTICE_GIT_BLOB_SHA1)"
expected_codex_url="https://raw.githubusercontent.com/openai/codex/${codex_release_tag}/NOTICE"
actual_codex_blob="$(git hash-object "$codex_notice")"

if [[ "$recorded_codex_tag" != "$codex_release_tag" ]]; then
  echo "ERROR: Codex NOTICE release $recorded_codex_tag does not match Dockerfile release $codex_release_tag" >&2
  exit 1
fi
if [[ "$recorded_codex_url" != "$expected_codex_url" ]]; then
  echo "ERROR: Codex NOTICE URL must match the selected release: $expected_codex_url" >&2
  exit 1
fi
if [[ ! "$recorded_codex_blob" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR: CODEX_NOTICE_GIT_BLOB_SHA1 must be an exact lowercase Git blob SHA-1" >&2
  exit 1
fi
if [[ "$actual_codex_blob" != "$recorded_codex_blob" ]]; then
  echo "ERROR: third_party/components/codex/NOTICE does not match its reviewed source record" >&2
  exit 1
fi

python_version="$(locked_tool_version python)"
docker_python_version="$(sed -n 's/^ARG PYTHON_VERSION=//p' "$base_dockerfile")"
if [[ -z "$docker_python_version" || "$docker_python_version" == *$'\n'* ]]; then
  echo "ERROR: images/base/Dockerfile must define exactly one PYTHON_VERSION default" >&2
  exit 1
fi
if [[ "$docker_python_version" != "$python_version" ]]; then
  echo "ERROR: images/base/Dockerfile PYTHON_VERSION does not match mise.lock: $docker_python_version != $python_version" >&2
  exit 1
fi

recorded_python_version="$(read_record_value "$python_source" CPYTHON_VERSION)"
recorded_python_url="$(read_record_value "$python_source" CPYTHON_LICENSE_URL)"
recorded_python_blob="$(read_record_value "$python_source" CPYTHON_LICENSE_GIT_BLOB_SHA1)"
expected_python_url="https://raw.githubusercontent.com/python/cpython/v${python_version}/LICENSE"
actual_python_blob="$(git hash-object "$python_license")"

if [[ "$recorded_python_version" != "$python_version" ]]; then
  echo "ERROR: CPython license version $recorded_python_version does not match mise.lock Python $python_version" >&2
  exit 1
fi
if [[ "$recorded_python_url" != "$expected_python_url" ]]; then
  echo "ERROR: CPython license URL must match the locked Python tag: $expected_python_url" >&2
  exit 1
fi
if [[ ! "$recorded_python_blob" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR: CPYTHON_LICENSE_GIT_BLOB_SHA1 must be an exact lowercase Git blob SHA-1" >&2
  exit 1
fi
if [[ "$actual_python_blob" != "$recorded_python_blob" ]]; then
  echo "ERROR: third_party/components/python/LICENSE does not match its reviewed source record" >&2
  exit 1
fi

require_text "$inventory" "selected Codex \`${codex_release_tag}\` release"
require_text "$inventory" '`components/codex/SOURCE.env`'
require_text "$inventory" "matching CPython \`v${python_version}\` tag"
require_text "$inventory" '`components/python/SOURCE.env`'

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

for variable in \
  BASE_VERSION \
  UBUNTU_VERSION \
  UBUNTU_DIGEST \
  GH_VERSION \
  GH_AMD64_SHA256 \
  GH_ARM64_SHA256 \
  TTYD_VERSION \
  TTYD_AMD64_SHA256 \
  TTYD_ARM64_SHA256 \
  MISE_VERSION \
  MISE_AMD64_SHA256 \
  MISE_ARM64_SHA256 \
  PYTHON_VERSION \
  NODE_VERSION \
  NPM_VERSION \
  UV_VERSION; do
  require_text "$base_dockerfile" "\"$variable=\${$variable}\""
done

for variable in \
  SOURCE_REVISION \
  PROJECT_VERSION \
  CODEX_RELEASE_TAG \
  CODEX_AMD64_SHA256 \
  CODEX_ARM64_SHA256; do
  require_text "$codex_dockerfile" "\"$variable=\${$variable}\""
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
require_text "$optional_policy" '--skip-aliases'
require_text "$optional_policy" '--skip-path'
require_text "$optional_policy" '~/.gemini/antigravity-cli/settings.json'

require_text "$base_dockerfile" 'apt-get install -y --no-install-recommends'
require_text "$codex_dockerfile" 'github.com/openai/codex/releases/download'
require_text "$base_dockerfile" 'github.com/cli/cli/releases/download'
require_text "$base_dockerfile" 'github.com/tsl0922/ttyd/releases/download'
require_text "$base_dockerfile" 'github.com/jdx/mise/releases/download'
require_text "$base_dockerfile" 'print-locked-runtime-artifacts.py'
require_text "$base_dockerfile" 'build argument disagrees with mise.lock'
require_text "$ROOT/scripts/copy-runtime-notices.sh" 'DEPENDENCIES.txt'
require_text "$ROOT/scripts/copy-runtime-notices.sh" 'components/codex/SOURCE.env'
require_text "$ROOT/scripts/copy-runtime-notices.sh" 'components/python/LICENSE'
require_text "$ROOT/scripts/copy-runtime-notices.sh" 'components/python/SOURCE.env'
require_text "$ROOT/scripts/copy-runtime-notices.sh" 'LICENSE.cpython.txt'
require_text "$ROOT/scripts/remote-dev-notices.sh" 'components/codex/SOURCE.env'
require_text "$ROOT/scripts/remote-dev-notices.sh" 'components/python/SOURCE.env'
require_text "$ROOT/scripts/remote-dev-notices.sh" 'runtime/python/LICENSE.cpython.txt'
require_text "$ROOT/scripts/remote-dev-notices.sh" 'runtime/npm/DEPENDENCIES.txt'
require_text "$ROOT/scripts/remote-dev-notices.sh" 'BUILD-VERSIONS.env'
require_text "$ROOT/scripts/remote-dev-notices.sh" 'CODEX-BUILD.env'

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
  require_text "$ROOT/scripts/remote-dev-notices.sh" "$key"
done

for dockerfile in "$base_dockerfile" "$codex_dockerfile"; do
  require_text "$dockerfile" 'io.github.experience83.remote-dev.project-license="Apache-2.0"'
  require_text "$dockerfile" 'io.github.experience83.remote-dev.license-scope="Remote Dev project code only; bundled components retain upstream terms"'
  require_text "$dockerfile" 'io.github.experience83.remote-dev.third-party-notices="/usr/share/doc/remote-dev/third_party"'
done

require_text "$codex_dockerfile" 'org.opencontainers.image.documentation="https://github.com/eXPerience83/remote-dev-containers/blob/${SOURCE_REVISION}/third_party/README.md"'

if grep -Fqi 'placeholder' "$inventory"; then
  echo "ERROR: third_party/README.md must be a reviewed inventory, not a placeholder" >&2
  exit 1
fi

if grep -Fq 'org.opencontainers.image.licenses=' "$base_dockerfile" "$codex_dockerfile"; then
  echo "ERROR: aggregate images must not advertise a project-only OCI licenses value" >&2
  exit 1
fi

printf 'Third-party inventory and optional-agent policy: OK\n'
