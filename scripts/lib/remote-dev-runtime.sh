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
    codex|shell)
      printf '%s\n' "$role"
      ;;
    launcher|antigravity|claude)
      remote_dev_runtime_error "REMOTE_DEV_ROLE=$role is reserved but not implemented"
      return 2
      ;;
    *)
      remote_dev_runtime_error "unsupported REMOTE_DEV_ROLE=$role (implemented: codex|shell; reserved: launcher|antigravity|claude)"
      return 2
      ;;
  esac
}

remote_dev_resolve_start_mode() {
  local role="$1"
  local raw_mode=""
  local source_name=""
  local source_value=""

  if [[ -n "${REMOTE_DEV_START_MODE:-}" ]]; then
    raw_mode="$REMOTE_DEV_START_MODE"
    source_name=REMOTE_DEV_START_MODE
    source_value="$REMOTE_DEV_START_MODE"
  else
    raw_mode="${START_MODE:-menu}"
    source_name=START_MODE
    source_value="${START_MODE:-unset}"
    case "$raw_mode" in
      codex) raw_mode=agent ;;
      menu|shell) ;;
    esac
  fi

  case "$raw_mode" in
    menu|agent|shell) ;;
    *)
      remote_dev_runtime_error "unsupported $source_name=$source_value (neutral: menu|agent|shell; legacy START_MODE: menu|codex|shell)"
      return 2
      ;;
  esac

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
    shell) printf 'remote-dev-shell\n' ;;
    *)
      remote_dev_runtime_error "cannot derive tmux session for unsupported role: $role"
      return 2
      ;;
  esac
}
