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

docker_arg_default() {
  local path="$1"
  local key="$2"
  local value=""

  if ! value="$(
    awk -v prefix="ARG ${key}=" '
      index($0, prefix) == 1 {
        count += 1
        value = substr($0, length(prefix) + 1)
      }
      END {
        if (count != 1 || value == "") exit 1
        print value
      }
    ' "$path"
  )"; then
    echo "ERROR: ${path#"$ROOT"/} must define exactly one non-empty ARG $key default" >&2
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

verify_source_record() {
  local label="$1"
  local source_record="$2"
  local version_key="$3"
  local expected_version="$4"
  local url_key="$5"
  local expected_url="$6"
  local blob_key="$7"
  local preserved_file="$8"
  local recorded_version=""
  local recorded_url=""
  local recorded_blob=""
  local actual_blob=""

  recorded_version="$(read_record_value "$source_record" "$version_key")"
  recorded_url="$(read_record_value "$source_record" "$url_key")"
  recorded_blob="$(read_record_value "$source_record" "$blob_key")"
  actual_blob="$(git hash-object "$preserved_file")"

  if [[ "$recorded_version" != "$expected_version" ]]; then
    echo "ERROR: $label source version $recorded_version does not match selected version $expected_version" >&2
    exit 1
  fi
  if [[ "$recorded_url" != "$expected_url" ]]; then
    echo "ERROR: $label source URL must match the selected release: $expected_url" >&2
    exit 1
  fi
  if [[ ! "$recorded_blob" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ERROR: $blob_key must be an exact lowercase Git blob SHA-1" >&2
    exit 1
  fi
  if [[ "$actual_blob" != "$recorded_blob" ]]; then
    echo "ERROR: ${preserved_file#"$ROOT"/} does not match its reviewed source record" >&2
    exit 1
  fi
}

require_file "$inventory"
require_file "$optional_policy"
require_file "$ROOT/scripts/print-locked-runtime-artifacts.py"

# Full repository validation also checks workflow triggers and synchronized
# defaults. Docker deliberately excludes .github from its build context, so the
# image-context pass validates only files and effective build values available
# inside that context.
if [[ -d "$ROOT/.github/workflows" ]]; then
  bash "$ROOT/scripts/validate-version-pins.sh"
fi

for file in \
  third_party/components/codex/NOTICE \
  third_party/components/codex/SOURCE.env \
  third_party/components/github-cli/LICENSE \
  third_party/components/github-cli/SOURCE.env \
  third_party/components/ttyd/LICENSE \
  third_party/components/ttyd/SOURCE.env \
  third_party/components/mise/LICENSE \
  third_party/components/mise/SOURCE.env \
  third_party/components/python/LICENSE \
  third_party/components/python/SOURCE.env \
  third_party/components/uv/LICENSE-APACHE-2.0 \
  third_party/components/uv/LICENSE-MIT; do
  require_file "$ROOT/$file"
done

codex_release_tag="$(docker_arg_default "$codex_dockerfile" CODEX_RELEASE_TAG)"
verify_source_record \
  'Codex NOTICE' \
  "$ROOT/third_party/components/codex/SOURCE.env" \
  CODEX_RELEASE_TAG "$codex_release_tag" \
  CODEX_NOTICE_URL "https://raw.githubusercontent.com/openai/codex/${codex_release_tag}/NOTICE" \
  CODEX_NOTICE_GIT_BLOB_SHA1 "$ROOT/third_party/components/codex/NOTICE"

gh_default="$(docker_arg_default "$base_dockerfile" GH_VERSION)"
gh_version="${REMOTE_DEV_GH_VERSION:-$gh_default}"
verify_source_record \
  'GitHub CLI license' \
  "$ROOT/third_party/components/github-cli/SOURCE.env" \
  GH_VERSION "$gh_version" \
  GH_LICENSE_URL "https://raw.githubusercontent.com/cli/cli/v${gh_version}/LICENSE" \
  GH_LICENSE_GIT_BLOB_SHA1 "$ROOT/third_party/components/github-cli/LICENSE"

ttyd_default="$(docker_arg_default "$base_dockerfile" TTYD_VERSION)"
ttyd_version="${REMOTE_DEV_TTYD_VERSION:-$ttyd_default}"
verify_source_record \
  'ttyd license' \
  "$ROOT/third_party/components/ttyd/SOURCE.env" \
  TTYD_VERSION "$ttyd_version" \
  TTYD_LICENSE_URL "https://raw.githubusercontent.com/tsl0922/ttyd/${ttyd_version}/LICENSE" \
  TTYD_LICENSE_GIT_BLOB_SHA1 "$ROOT/third_party/components/ttyd/LICENSE"

mise_default="$(docker_arg_default "$base_dockerfile" MISE_VERSION)"
mise_version="${REMOTE_DEV_MISE_VERSION:-$mise_default}"
verify_source_record \
  'mise license' \
  "$ROOT/third_party/components/mise/SOURCE.env" \
  MISE_VERSION "$mise_version" \
  MISE_LICENSE_URL "https://raw.githubusercontent.com/jdx/mise/v${mise_version}/LICENSE" \
  MISE_LICENSE_GIT_BLOB_SHA1 "$ROOT/third_party/components/mise/LICENSE"

python_locked_version="$(locked_tool_version python)"
python_default="$(docker_arg_default "$base_dockerfile" PYTHON_VERSION)"
python_version="${REMOTE_DEV_PYTHON_VERSION:-$python_default}"
if [[ "$python_default" != "$python_locked_version" ]]; then
  echo "ERROR: images/base/Dockerfile PYTHON_VERSION does not match mise.lock: $python_default != $python_locked_version" >&2
  exit 1
fi
if [[ "$python_version" != "$python_locked_version" ]]; then
  echo "ERROR: selected PYTHON_VERSION does not match mise.lock: $python_version != $python_locked_version" >&2
  exit 1
fi
verify_source_record \
  'CPython license' \
  "$ROOT/third_party/components/python/SOURCE.env" \
  CPYTHON_VERSION "$python_version" \
  CPYTHON_LICENSE_URL "https://raw.githubusercontent.com/python/cpython/v${python_version}/LICENSE" \
  CPYTHON_LICENSE_GIT_BLOB_SHA1 "$ROOT/third_party/components/python/LICENSE"

for source_record in \
  components/codex/SOURCE.env \
  components/github-cli/SOURCE.env \
  components/ttyd/SOURCE.env \
  components/mise/SOURCE.env \
  components/python/SOURCE.env; do
  require_text "$inventory" "\`$source_record\`"
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
for source_record in \
  components/codex/SOURCE.env \
  components/github-cli/SOURCE.env \
  components/ttyd/SOURCE.env \
  components/mise/SOURCE.env \
  components/python/SOURCE.env; do
  require_text "$ROOT/scripts/copy-runtime-notices.sh" "$source_record"
  require_text "$ROOT/scripts/remote-dev-notices.sh" "$source_record"
done
require_text "$ROOT/scripts/copy-runtime-notices.sh" 'components/python/LICENSE'
require_text "$ROOT/scripts/copy-runtime-notices.sh" 'LICENSE.cpython.txt'
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
