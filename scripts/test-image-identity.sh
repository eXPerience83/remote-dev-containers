#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=scripts/lib/remote-dev-image-identity.sh
source "$ROOT/scripts/lib/remote-dev-image-identity.sh"

expect_ok() {
  local channel="$1"
  local version="$2"
  local source_revision="$3"
  remote_dev_validate_image_identity "$channel" "$version" "$source_revision"
}

expect_fail() {
  local channel="$1"
  local version="$2"
  local source_revision="$3"
  if remote_dev_validate_image_identity "$channel" "$version" "$source_revision" >/dev/null 2>&1; then
    echo "ERROR: identity unexpectedly passed: $channel / $version / $source_revision" >&2
    exit 1
  fi
}

edge_sha=0123456789abcdef0123456789abcdef01234567
other_sha=89abcdef0123456789abcdef0123456789abcdef

expect_ok local 0.1.0-dev local-untracked
expect_ok local 0.1.0-dev "$edge_sha"
expect_ok dev candidate-pr-188 "$edge_sha"
expect_ok edge edge-2026.08.27-0123456 "$edge_sha"
expect_ok stable v0.1.0 "$edge_sha"

expect_fail dev dev-pr-188-0123456 "$edge_sha"
expect_fail edge edge-2026.08.27-89abcde "$edge_sha"
expect_fail edge edge-2026.02.30-0123456 "$edge_sha"
expect_fail stable 0.1.0 "$edge_sha"
expect_fail unknown edge-2026.08.27-0123456 "$other_sha"

echo "Image identity contract tests: OK"
