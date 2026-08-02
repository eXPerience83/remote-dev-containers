#!/usr/bin/env bash

if [[ -n "${REMOTE_DEV_RUNTIME_LIB_LOADED:-}" ]]; then
  return 0
fi
REMOTE_DEV_RUNTIME_LIB_LOADED=1

remote_dev_runtime_error() {
  printf 'ERROR: %s\n' "$*" >&2
}

remote_dev_resolve_role() {
  local role="${REMOTE_DEV_ROLE:-codex}"

  case "$role" in
    launcher|codex|shell|antigravity)
      printf '%s\n' "$role"
      ;;
    claude)
      remote_dev_runtime_error "REMOTE_DEV_ROLE=$role is reserved but not implemented"
      return 2
      ;;
    *)
      remote_dev_runtime_error "unsupported REMOTE_DEV_ROLE=$role (implemented: launcher|codex|shell|antigravity; reserved: claude)"
      return 2
      ;;
  esac
}

remote_dev_resolve_start_mode() {
  local role="$1"
  local raw_mode=""

  if [[ -n "${REMOTE_DEV_START_MODE:-}" ]]; then
    case "$REMOTE_DEV_START_MODE" in
      menu|agent|shell)
        raw_mode="$REMOTE_DEV_START_MODE"
        ;;
      *)
        remote_dev_runtime_error "unsupported REMOTE_DEV_START_MODE=$REMOTE_DEV_START_MODE (menu|agent|shell)"
        return 2
        ;;
    esac
  else
    case "${START_MODE:-menu}" in
      menu) raw_mode=menu ;;
      codex|antigravity) raw_mode=agent ;;
      shell) raw_mode=shell ;;
      *)
        remote_dev_runtime_error "unsupported START_MODE=${START_MODE:-unset} (menu|codex|antigravity|shell)"
        return 2
        ;;
    esac
  fi

  if [[ "$role" == launcher && "$raw_mode" != menu ]]; then
    remote_dev_runtime_error "REMOTE_DEV_ROLE=launcher supports only REMOTE_DEV_START_MODE=menu"
    return 2
  fi
  if [[ "$role" == shell && "$raw_mode" == agent ]]; then
    remote_dev_runtime_error "REMOTE_DEV_START_MODE=agent is not available for REMOTE_DEV_ROLE=shell"
    return 2
  fi

  printf '%s\n' "$raw_mode"
}

remote_dev_default_tmux_session() {
  local role="$1"

  case "$role" in
    codex) printf 'codex\n' ;;
    antigravity) printf 'antigravity\n' ;;
    shell) printf 'remote-dev-shell\n' ;;
    launcher)
      remote_dev_runtime_error "the launcher role does not use tmux"
      return 2
      ;;
    *)
      remote_dev_runtime_error "cannot derive tmux session for unsupported role: $role"
      return 2
      ;;
  esac
}
