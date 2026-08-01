#!/usr/bin/env bash
set -euo pipefail

runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"

role="$(remote_dev_resolve_role)"
start_mode="$(remote_dev_resolve_start_mode "$role")"
export REMOTE_DEV_ROLE="$role"
export REMOTE_DEV_START_MODE="$start_mode"

if [[ -z "${TMUX_SESSION:-}" ]]; then
  TMUX_SESSION="$(remote_dev_default_tmux_session "$role")"
  export TMUX_SESSION
fi

workspace="${WORKSPACE:-/workspace}"
gh_config_dir="${GH_CONFIG_DIR:-/root/.config/gh}"
git_config_global="${GIT_CONFIG_GLOBAL:-/root/.config/git/config}"

umask 077
mkdir -p "$workspace" "$gh_config_dir" "$(dirname "$git_config_global")" /root/.ssh
if [[ "$role" == codex ]]; then
  mkdir -p "${CODEX_HOME:-/root/.codex}"
fi
/usr/local/bin/secure-persistent-state

# Shared-workspace defaults. Never trust every path globally.
git config --global core.filemode false || true
if [[ -n "${GIT_USER_NAME:-}" ]]; then
  git config --global user.name "$GIT_USER_NAME"
fi
if [[ -n "${GIT_USER_EMAIL:-}" ]]; then
  git config --global user.email "$GIT_USER_EMAIL"
fi

if gh auth status >/dev/null 2>&1; then
  gh auth setup-git >/dev/null 2>&1 || true
fi
/usr/local/bin/secure-persistent-state

credential=""
web_username="${WEB_USERNAME:-codex}"
if [[ -n "${WEB_PASSWORD_FILE:-}" ]]; then
  if [[ ! -r "$WEB_PASSWORD_FILE" ]]; then
    echo "ERROR: WEB_PASSWORD_FILE is not readable: $WEB_PASSWORD_FILE" >&2
    exit 1
  fi
  credential="${web_username}:$(<"$WEB_PASSWORD_FILE")"
elif [[ -n "${WEB_PASSWORD:-}" ]]; then
  credential="${web_username}:${WEB_PASSWORD}"
elif [[ "${ALLOW_INSECURE_WEB:-0}" != "1" ]]; then
  cat >&2 <<'MSG'
ERROR: web authentication is not configured.
Set WEB_PASSWORD_FILE (recommended) or WEB_PASSWORD.
Set ALLOW_INSECURE_WEB=1 only on an already protected private endpoint.
MSG
  exit 1
fi

cmd=(
  ttyd
  --writable
  --interface "${WEB_BIND:-0.0.0.0}"
  --port "${WEB_PORT:-7681}"
  --max-clients "${WEB_MAX_CLIENTS:-1}"
  --terminal-type xterm-256color
  --client-option "fontSize=15"
  --client-option "disableLeaveAlert=false"
)

if [[ "${WEB_CHECK_ORIGIN:-1}" == "1" ]]; then
  cmd+=(--check-origin)
fi
if [[ "${WEB_BASE_PATH:-/}" != "/" ]]; then
  cmd+=(--base-path "${WEB_BASE_PATH}")
fi
if [[ -n "$credential" ]]; then
  cmd+=(--credential "$credential")
fi

exec "${cmd[@]}" /usr/local/bin/attach-remote-dev-tmux
