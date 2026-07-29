#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--print-policy" ]]; then
  cat <<'POLICY'
Inner sandbox: disabled explicitly
Isolation boundary: outer container
Codex approval policy: untrusted
POLICY
  exit 0
fi

exec /usr/local/bin/codex \
  --sandbox danger-full-access \
  --ask-for-approval untrusted \
  "$@"
