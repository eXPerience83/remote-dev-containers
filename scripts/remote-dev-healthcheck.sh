#!/usr/bin/env bash
set -euo pipefail

runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"

role="$(remote_dev_resolve_role)"

case "$role" in
  launcher)
    base_path="${WEB_BASE_PATH:-/}"
    if [[ "$base_path" != /* || "$base_path" == *$'\n'* || "$base_path" == *$'\r'* ]]; then
      echo "ERROR: invalid WEB_BASE_PATH for launcher health check" >&2
      exit 2
    fi
    while [[ "$base_path" != / && "$base_path" == */ ]]; do
      base_path="${base_path%/}"
    done
    if [[ -z "$base_path" || "$base_path" == / ]]; then
      health_path=/healthz
    else
      health_path="${base_path}/healthz"
    fi
    curl --fail --silent --show-error \
      --connect-timeout 2 --max-time 4 \
      "http://127.0.0.1:${WEB_PORT:-7680}${health_path}" >/dev/null
    ;;
  codex)
    pgrep -x ttyd >/dev/null
    codex --version >/dev/null
    ;;
  shell)
    pgrep -x ttyd >/dev/null
    ;;
  *)
    echo "ERROR: internal unsupported health-check role: $role" >&2
    exit 2
    ;;
esac
