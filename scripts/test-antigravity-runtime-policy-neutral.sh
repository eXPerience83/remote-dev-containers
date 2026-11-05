#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

# Exercise the same admitted-runtime lifecycle under the managed guarded mode.
# The dedicated policy tests cover mode selection and guarded rejection cases.
REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE=guarded \
  bash "$root/scripts/test-antigravity-runtime.sh"
