#!/usr/bin/env bash
set -euo pipefail

readonly manager=/usr/local/lib/remote-dev/remote-dev-context7.py
readonly device_login=/usr/local/bin/remote-dev-context7-device-login
readonly python=/usr/local/lib/remote-dev/python

delegate_manager() {
  exec "$python" -I "$manager" "$@"
}

command="${1:-}"
if [[ "$command" != install && "$command" != repair ]]; then
  delegate_manager "$@"
fi

# The menu-only expected-state token preserves the interactive onboarding
# wizard while delivering its original consent precondition to every backend
# route, including the separately executed device-login helper.
menu_precondition=""
if (( $# == 2 )); then
  case "$2" in
    --menu-expect-absent) menu_precondition=--expect-absent ;;
    --menu-expect-healthy) menu_precondition=--expect-healthy ;;
  esac
fi
# Ordinary direct CLI invocations retain their previous semantics.
if (( $# > 1 )) && [[ -z "$menu_precondition" ]]; then
  delegate_manager "$@"
fi
if [[ ! -t 0 || ! -t 1 ]]; then
  if [[ -n "$menu_precondition" ]]; then
    delegate_manager "$command" "$menu_precondition"
  fi
  delegate_manager "$@"
fi

cat <<'MENU'
Context7 authentication
=======================
Context7 is an optional external service operated by Upstash.
Device-code sign-in transiently resolves/downloads an exact official ctx7 CLI
inside this Codex container as an unprivileged process; this is not a filesystem sandbox.
If a newer official CLI exists, Remote Dev lets you choose the reviewed version
or that exact latest version with a clear review-pending warning.
1) Sign in to Context7 with a device code (recommended)
2) Enter an existing Context7 API key
3) Keep the current API key, or stay anonymous if none exists
4) Use anonymous access and remove the Remote Dev-managed API key
0) Cancel
MENU

choice=""
if ! read -r -p "> " choice; then
  echo "ERROR: cancelled" >&2
  exit 2
fi

case "$choice" in
  1)
    if [[ -n "$menu_precondition" ]]; then
      exec "$device_login" --yes "$menu_precondition"
    fi
    exec "$device_login" --yes
    ;;
  2)
    if [[ -n "$menu_precondition" ]]; then
      delegate_manager "$command" "$menu_precondition"
    fi
    delegate_manager "$command"
    ;;
  3)
    if [[ -n "$menu_precondition" ]]; then
      delegate_manager "$command" --yes "$menu_precondition"
    fi
    delegate_manager "$command" --yes
    ;;
  4)
    if [[ -n "$menu_precondition" ]]; then
      delegate_manager "$command" --yes --anonymous "$menu_precondition"
    fi
    delegate_manager "$command" --yes --anonymous
    ;;
  0|5)
    # Preserve the historical 5 alias without displaying it.
    echo "ERROR: cancelled" >&2
    exit 2
    ;;
  *)
    echo "ERROR: invalid Context7 authentication choice" >&2
    exit 2
    ;;
esac
