#!/usr/bin/env bash
set -euo pipefail

readonly manager=/usr/local/lib/remote-dev/remote-dev-context7.py
readonly device_login=/usr/local/bin/remote-dev-context7-device-login
readonly python=/opt/remote-dev/mise/shims/python

delegate_manager() {
  exec "$python" "$manager" "$@"
}

command="${1:-}"
if [[ "$command" != install && "$command" != repair ]]; then
  delegate_manager "$@"
fi

# Explicit flags and automation retain the existing manager contract. The
# onboarding choice is only inserted for the plain interactive install/repair
# action used by the Remote Dev menu.
if (( $# > 1 )); then
  delegate_manager "$@"
fi
if [[ ! -t 0 || ! -t 1 ]]; then
  delegate_manager "$@"
fi

cat <<'MENU'
Context7 authentication
=======================
Context7 is an optional external service operated by Upstash.
Device-code sign-in transiently downloads/runs the pinned official ctx7 CLI
inside this Codex container as an unprivileged process; this is not a filesystem sandbox.
1) Sign in to Context7 with a device code (recommended)
2) Enter an existing Context7 API key
3) Keep the current API key, or stay anonymous if none exists
4) Use anonymous access and remove the Remote Dev-managed API key
5) Cancel
MENU

choice=""
if ! read -r -p "> " choice; then
  echo "ERROR: cancelled" >&2
  exit 2
fi

case "$choice" in
  1)
    exec "$device_login" --yes
    ;;
  2)
    delegate_manager "$command"
    ;;
  3)
    delegate_manager "$command" --yes
    ;;
  4)
    delegate_manager "$command" --yes --anonymous
    ;;
  5)
    echo "ERROR: cancelled" >&2
    exit 2
    ;;
  *)
    echo "ERROR: invalid Context7 authentication choice" >&2
    exit 2
    ;;
esac
