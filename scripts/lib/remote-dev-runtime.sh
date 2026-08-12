#!/usr/bin/env bash

if [[ -n "${REMOTE_DEV_RUNTIME_LIB_LOADED:-}" ]]; then
  return 0
fi
REMOTE_DEV_RUNTIME_LIB_LOADED=1

remote_dev_runtime_error() {
  printf 'ERROR: %s\n' "$*" >&2
}

remote_dev_validate_workspace_root() {
  local workspace="$1"
  local current=""
  local previous=""

  if [[ -z "$workspace" || "$workspace" != /* || "$workspace" == //* \
     || "$workspace" == *$'\n'* || "$workspace" == *$'\r'* \
     || "$workspace" == *'/../'* || "$workspace" == */.. \
     || "$workspace" == *'/./'* || "$workspace" == */. ]]; then
    remote_dev_runtime_error "WORKSPACE must be a safe absolute path"
    return 2
  fi

  case "$workspace" in
    /|/root|/home|/opt|/usr|/usr/local|/etc|/var|/tmp)
      remote_dev_runtime_error "WORKSPACE is too broad: $workspace"
      return 2
      ;;
  esac

  if [[ ! -d "$workspace" ]]; then
    remote_dev_runtime_error "WORKSPACE does not exist: $workspace"
    return 2
  fi

  current="$workspace"
  while [[ "$current" != / && "$current" != "$previous" ]]; do
    if [[ -L "$current" ]]; then
      remote_dev_runtime_error "WORKSPACE contains a symlinked path component: $current"
      return 2
    fi
    previous="$current"
    current="$(dirname "$current")"
  done

  printf '%s\n' "$workspace"
}

remote_dev_workspace_root() {
  remote_dev_validate_workspace_root "${WORKSPACE:-/workspace}"
}

remote_dev_validate_project_name() {
  local name="$1"

  if (( ${#name} == 0 || ${#name} > 128 )) \
     || [[ ! "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    remote_dev_runtime_error \
      "invalid project name: use 1-128 ASCII letters/digits plus '.', '_' or '-', starting with a letter or digit"
    return 2
  fi

  printf '%s\n' "$name"
}

remote_dev_project_path() {
  local workspace="$1"
  local name="$2"
  local project=""

  workspace="$(remote_dev_validate_workspace_root "$workspace")" || return $?
  remote_dev_validate_project_name "$name" >/dev/null || return $?
  project="$workspace/$name"

  if [[ ! -d "$project" ]]; then
    remote_dev_runtime_error "project does not exist: $name"
    return 2
  fi
  if [[ -L "$project" ]]; then
    remote_dev_runtime_error "project must not be a symlink: $name"
    return 2
  fi

  printf '%s\n' "$project"
}

remote_dev_list_projects() {
  local workspace="$1"
  local path=""
  local name=""

  workspace="$(remote_dev_validate_workspace_root "$workspace")" || return $?

  for path in "$workspace"/*; do
    [[ -d "$path" && ! -L "$path" ]] || continue
    name="${path##*/}"
    remote_dev_validate_project_name "$name" >/dev/null 2>&1 || continue
    printf '%s\n' "$name"
  done | LC_ALL=C sort
}

remote_dev_resolve_project() {
  local workspace="$1"
  local selector="${2:-${REMOTE_DEV_PROJECT:-}}"
  local -a projects=()

  workspace="$(remote_dev_validate_workspace_root "$workspace")" || return $?

  if [[ -n "$selector" ]]; then
    remote_dev_project_path "$workspace" "$selector"
    return $?
  fi

  mapfile -t projects < <(remote_dev_list_projects "$workspace")
  case "${#projects[@]}" in
    0)
      remote_dev_runtime_error \
        "no project directories found under $workspace; create a project before starting an agent"
      return 2
      ;;
    1)
      remote_dev_project_path "$workspace" "${projects[0]}"
      ;;
    *)
      remote_dev_runtime_error \
        "multiple projects found under $workspace; select one in the Projects menu or set REMOTE_DEV_PROJECT to one project name"
      return 2
      ;;
  esac
}

remote_dev_create_project() {
  local workspace="$1"
  local name="$2"
  local project=""

  workspace="$(remote_dev_validate_workspace_root "$workspace")" || return $?
  remote_dev_validate_project_name "$name" >/dev/null || return $?
  project="$workspace/$name"

  if [[ -e "$project" || -L "$project" ]]; then
    remote_dev_runtime_error "project path already exists: $name"
    return 2
  fi

  if ! mkdir -- "$project"; then
    remote_dev_runtime_error "failed to create project: $name"
    return 1
  fi

  printf '%s\n' "$project"
}

remote_dev_delete_project() {
  local workspace="$1"
  local name="$2"
  local confirmation="$3"
  local project=""

  workspace="$(remote_dev_validate_workspace_root "$workspace")" || return $?
  remote_dev_validate_project_name "$name" >/dev/null || return $?

  if [[ "$confirmation" != "$name" ]]; then
    remote_dev_runtime_error "project deletion confirmation did not match the exact project name"
    return 2
  fi

  project="$(remote_dev_project_path "$workspace" "$name")" || return $?
  if ! rm -rf -- "$project"; then
    remote_dev_runtime_error "failed to delete project: $name"
    return 1
  fi

  if [[ -e "$project" || -L "$project" ]]; then
    remote_dev_runtime_error "project deletion did not remove the expected path: $name"
    return 1
  fi
}

remote_dev_antigravity_experimental_enabled() {
  [[ "${REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY:-0}" == 1 ]]
}

remote_dev_resolve_role() {
  local role="${REMOTE_DEV_ROLE:-codex}"

  case "$role" in
    launcher|codex|shell)
      printf '%s\n' "$role"
      ;;
    antigravity)
      if ! remote_dev_antigravity_experimental_enabled; then
        remote_dev_runtime_error "REMOTE_DEV_ROLE=antigravity is experimental and blocked pending TrueNAS validation; set REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 only for the controlled validation deployment"
        return 2
      fi
      printf '%s\n' "$role"
      ;;
    claude)
      remote_dev_runtime_error "REMOTE_DEV_ROLE=$role is reserved but not implemented"
      return 2
      ;;
    *)
      remote_dev_runtime_error "unsupported REMOTE_DEV_ROLE=$role (implemented: launcher|codex|shell; experimental gated: antigravity; reserved: claude)"
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
      codex)
        [[ "$role" == codex ]] || {
          remote_dev_runtime_error "START_MODE=codex requires REMOTE_DEV_ROLE=codex"
          return 2
        }
        raw_mode=agent
        ;;
      antigravity)
        [[ "$role" == antigravity ]] || {
          remote_dev_runtime_error "START_MODE=antigravity requires REMOTE_DEV_ROLE=antigravity"
          return 2
        }
        raw_mode=agent
        ;;
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
