#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
versions_file="$ROOT/versions.env"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

curl_args=(
  --fail
  --silent
  --show-error
  --location
  --retry 3
  --retry-all-errors
  --connect-timeout 10
  --max-time 300
)

read_pin() {
  local key="$1"
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
    ' "$versions_file"
  )"; then
    echo "ERROR: versions.env must contain exactly one non-empty $key value" >&2
    exit 1
  fi

  printf '%s\n' "$value"
}

refresh_record() {
  local label="$1"
  local url="$2"
  local destination="$3"
  local record="$4"
  local version_key="$5"
  local version="$6"
  local url_key="$7"
  local blob_key="$8"
  local temporary="$workdir/${label//[^A-Za-z0-9_.-]/_}"
  local blob=""

  curl "${curl_args[@]}" "$url" -o "$temporary"
  if [[ ! -s "$temporary" ]]; then
    echo "ERROR: downloaded $label source is empty: $url" >&2
    exit 1
  fi

  install -D -m 0644 "$temporary" "$destination"
  blob="$(git hash-object "$destination")"
  if [[ ! "$blob" =~ ^[0-9a-f]{40}$ ]]; then
    echo "ERROR: could not calculate a Git blob identity for $destination" >&2
    exit 1
  fi

  install -d -m 0755 "$(dirname "$record")"
  {
    printf '# Exact reviewed source record for the %s copied into this image.\n' "$label"
    printf '%s=%s\n' "$version_key" "$version"
    printf '%s=%s\n' "$url_key" "$url"
    printf '%s=%s\n' "$blob_key" "$blob"
  } > "$record"
  chmod 0644 "$record"
}

codex_release_tag="$(read_pin CODEX_RELEASE_TAG)"
gh_version="$(read_pin GH_VERSION)"
ttyd_version="$(read_pin TTYD_VERSION)"
mise_version="$(read_pin MISE_VERSION)"
python_version="$(read_pin PYTHON_VERSION)"

refresh_record \
  'Codex NOTICE' \
  "https://raw.githubusercontent.com/openai/codex/${codex_release_tag}/NOTICE" \
  "$ROOT/third_party/components/codex/NOTICE" \
  "$ROOT/third_party/components/codex/SOURCE.env" \
  CODEX_RELEASE_TAG "$codex_release_tag" \
  CODEX_NOTICE_URL CODEX_NOTICE_GIT_BLOB_SHA1

refresh_record \
  'GitHub CLI license' \
  "https://raw.githubusercontent.com/cli/cli/v${gh_version}/LICENSE" \
  "$ROOT/third_party/components/github-cli/LICENSE" \
  "$ROOT/third_party/components/github-cli/SOURCE.env" \
  GH_VERSION "$gh_version" \
  GH_LICENSE_URL GH_LICENSE_GIT_BLOB_SHA1

refresh_record \
  'ttyd license' \
  "https://raw.githubusercontent.com/tsl0922/ttyd/${ttyd_version}/LICENSE" \
  "$ROOT/third_party/components/ttyd/LICENSE" \
  "$ROOT/third_party/components/ttyd/SOURCE.env" \
  TTYD_VERSION "$ttyd_version" \
  TTYD_LICENSE_URL TTYD_LICENSE_GIT_BLOB_SHA1

refresh_record \
  'mise license' \
  "https://raw.githubusercontent.com/jdx/mise/v${mise_version}/LICENSE" \
  "$ROOT/third_party/components/mise/LICENSE" \
  "$ROOT/third_party/components/mise/SOURCE.env" \
  MISE_VERSION "$mise_version" \
  MISE_LICENSE_URL MISE_LICENSE_GIT_BLOB_SHA1

refresh_record \
  'CPython license' \
  "https://raw.githubusercontent.com/python/cpython/v${python_version}/LICENSE" \
  "$ROOT/third_party/components/python/LICENSE" \
  "$ROOT/third_party/components/python/SOURCE.env" \
  CPYTHON_VERSION "$python_version" \
  CPYTHON_LICENSE_URL CPYTHON_LICENSE_GIT_BLOB_SHA1

printf 'Refreshed reviewed third-party source records for selected releases.\n'
