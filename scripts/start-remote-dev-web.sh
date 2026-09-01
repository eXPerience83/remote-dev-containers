#!/usr/bin/env bash
set -euo pipefail

runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"

role="$(remote_dev_resolve_role)"
start_mode="$(remote_dev_resolve_start_mode "$role")"
export REMOTE_DEV_ROLE="$role"
export REMOTE_DEV_START_MODE="$start_mode"

# Development scratch is a child-session default, never a startup or launcher
# trust boundary. Discard caller values before touching persistent state.
unset TMPDIR TMP TEMP UV_CACHE_DIR NPM_CONFIG_CACHE PIP_CACHE_DIR

if [[ "$role" == launcher ]]; then
  exec /usr/local/bin/remote-dev-launcher
fi

# Agent browser authentication is deployment configuration, but helper tools and
# terminal child processes do not need the raw environment variable. Capture it
# into a non-exported shell variable and remove it before invoking any external
# startup helper. ttyd receives only its required --credential argument.
web_password="${WEB_PASSWORD:-}"
unset WEB_PASSWORD

if [[ -z "${TMUX_SESSION:-}" ]]; then
  TMUX_SESSION="$(remote_dev_default_tmux_session "$role")"
  export TMUX_SESSION
fi

workspace="${WORKSPACE:-/workspace}"
gh_config_dir="${GH_CONFIG_DIR:-/root/.config/gh}"
git_config_global="${GIT_CONFIG_GLOBAL:-/root/.config/git/config}"

umask 077
if [[ "$role" == codex || "$role" == antigravity ]]; then
  workspace="$(remote_dev_validate_workspace_root "$workspace")" || exit $?
else
  mkdir -p "$workspace"
fi
mkdir -p "$gh_config_dir" "$(dirname "$git_config_global")" /root/.ssh
if [[ "$role" == codex ]]; then
  mkdir -p "${CODEX_HOME:-/root/.codex}"
elif [[ "$role" == antigravity ]]; then
  readonly paths_lib=/usr/local/lib/remote-dev/antigravity-paths.sh
  [[ -r "$paths_lib" && ! -L "$paths_lib" ]] || {
    echo "ERROR: immutable Antigravity path definitions are unavailable" >&2
    exit 1
  }
  # shellcheck source=/usr/local/lib/remote-dev/antigravity-paths.sh
  source "$paths_lib"
  mkdir -p \
    "$ANTIGRAVITY_BIN_DIR" \
    "$ANTIGRAVITY_STATE_DIR" \
    "$ANTIGRAVITY_VENDOR_STATE_DIR" \
    "$ANTIGRAVITY_CONFIG_STATE_DIR"
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
if [[ -n "$web_password" ]]; then
  if [[ "$web_password" == *$'\r'* || "$web_password" == *$'\n'* ]]; then
    echo "ERROR: web password must be a single line" >&2
    exit 1
  fi
  credential="${web_username}:${web_password}"
elif [[ "${ALLOW_INSECURE_WEB:-0}" != "1" ]]; then
  cat >&2 <<'MSG'
ERROR: web authentication is not configured.
Set WEB_PASSWORD for this endpoint.
Set ALLOW_INSECURE_WEB=1 only on an already protected private endpoint.
MSG
  exit 1
fi
unset web_password

if [[ "$role" == codex || "$role" == antigravity ]]; then
  remote_dev_prepare_development_environment "$role" "$workspace" || exit $?
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
  --index /usr/share/remote-dev/ttyd/index.html
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
