#!/usr/bin/env bash
set -euo pipefail

readonly sandbox_mode=danger-full-access
readonly approval_policy=untrusted

if [[ "${1:-}" == "--print-policy" ]]; then
  printf '%s\n' \
    'Inner sandbox: disabled explicitly' \
    'Isolation boundary: outer container' \
    "Codex approval policy: $approval_policy"
  exit 0
fi

exec codex \
  --sandbox "$sandbox_mode" \
  --ask-for-approval "$approval_policy" \
  "$@"
