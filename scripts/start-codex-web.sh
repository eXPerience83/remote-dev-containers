#!/usr/bin/env bash
set -euo pipefail

umask 077
mkdir -p "$WORKSPACE" "$CODEX_HOME" "$GH_CONFIG_DIR" "$(dirname "$GIT_CONFIG_GLOBAL")" /root/.ssh
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
if [[ -n "${WEB_PASSWORD_FILE:-}" ]]; then
  if [[ ! -r "$WEB_PASSWORD_FILE" ]]; then
    echo "ERROR: WEB_PASSWORD_FILE is not readable: $WEB_PASSWORD_FILE" >&2
    exit 1
  fi
  credential="${WEB_USERNAME}:$(<"$WEB_PASSWORD_FILE")"
elif [[ -n "${WEB_PASSWORD:-}" ]]; then
  credential="${WEB_USERNAME}:${WEB_PASSWORD}"
elif [[ "${ALLOW_INSECURE_WEB}" != "1" ]]; then
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
  --interface "$WEB_BIND"
  --port "$WEB_PORT"
  --max-clients "$WEB_MAX_CLIENTS"
  --terminal-type xterm-256color
  --client-option "fontSize=15"
  --client-option "disableLeaveAlert=false"
)

if [[ "$WEB_CHECK_ORIGIN" == "1" ]]; then
  cmd+=(--check-origin)
fi
if [[ "$WEB_BASE_PATH" != "/" ]]; then
  cmd+=(--base-path "$WEB_BASE_PATH")
fi
if [[ -n "$credential" ]]; then
  cmd+=(--credential "$credential")
fi

case "$START_MODE" in
  menu)
    child=(tmux new-session -A -s "$TMUX_SESSION" /usr/local/bin/codex-menu)
    ;;
  codex)
    child=(tmux new-session -A -s "$TMUX_SESSION" "cd '$WORKSPACE' && exec codex")
    ;;
  shell)
    child=(tmux new-session -A -s "$TMUX_SESSION" "cd '$WORKSPACE' && exec bash --login")
    ;;
  *)
    echo "ERROR: unsupported START_MODE=$START_MODE (menu|codex|shell)" >&2
    exit 2
    ;;
esac

exec "${cmd[@]}" "${child[@]}"
