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
     || "$workspace" == *'//'* \
     || ( "$workspace" != / && "$workspace" == */ ) \
     || "$workspace" == *[[:cntrl:]]* \
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

# /workspace is a collection boundary, never a normal Git repository. Keep
# this assertion separate from remote_dev_validate_workspace_root(): the web
# terminal and login shell must remain available when an operator needs to
# recover a contaminated collection.
remote_dev_assert_project_collection() {
  local workspace="$1"
  local bare_state=""

  workspace="$(remote_dev_validate_workspace_root "$workspace")" || return $?

  if [[ -e "$workspace/.git" || -L "$workspace/.git" ]]; then
    remote_dev_runtime_error \
      "CRITICAL: project collection root contains .git: $workspace; agent project actions are blocked"
    return 2
  fi

  if ! command -v git >/dev/null 2>&1; then
    remote_dev_runtime_error "Git is unavailable; project collection safety cannot be verified"
    return 1
  fi

  # Clear only repository-routing variables for this read-only inspection.
  # Authentication/configuration variables are intentionally preserved.
  if bare_state="$(
    env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR \
      GIT_CEILING_DIRECTORIES="$workspace" \
      git -C "$workspace" rev-parse --is-bare-repository 2>/dev/null
  )"; then
    case "$bare_state" in
      true)
        remote_dev_runtime_error \
          "CRITICAL: project collection root is a bare Git repository: $workspace; agent project actions are blocked"
        return 2
        ;;
      false) ;;
      *)
        remote_dev_runtime_error \
          "project collection Git state is ambiguous; agent project actions are blocked"
        return 2
        ;;
    esac
  fi

  printf '%s\n' "$workspace"
}

remote_dev_prepare_project_git_boundary() {
  local workspace="$1"
  local variable=""

  workspace="$(remote_dev_assert_project_collection "$workspace")" || return $?

  if [[ "$workspace" == *:* ]]; then
    remote_dev_runtime_error \
      "WORKSPACE cannot contain ':' for managed agent execution because Git ceiling entries are colon-separated"
    return 2
  fi

  for variable in GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR; do
    if [[ -n "${!variable:-}" ]]; then
      remote_dev_runtime_error \
        "inherited $variable would bypass the selected-project Git boundary"
      return 2
    fi
  done

  export GIT_CEILING_DIRECTORIES="$workspace"
}

remote_dev_recover_safe_cwd() {
  if ! builtin cd -P -- /; then
    remote_dev_runtime_error "unable to recover a safe current directory"
    return 1
  fi
}

remote_dev_prepare_development_environment() {
  local role="$1"
  local workspace="$2"
  local scratch_root=""
  local -r preparer=/usr/local/bin/remote-dev-prepare-development-scratch

  case "$role" in
    codex|antigravity) ;;
    *)
      remote_dev_runtime_error "development scratch is unavailable for REMOTE_DEV_ROLE=$role"
      return 2
      ;;
  esac

  workspace="$(remote_dev_validate_workspace_root "$workspace")" || return $?
  if [[ ! -x "$preparer" || -L "$preparer" ]]; then
    remote_dev_runtime_error "development scratch preparer is unavailable: $preparer"
    return 1
  fi
  "$preparer" "$workspace" || return $?

  scratch_root="$workspace/.remote-dev-tmp"
  export TMPDIR="$scratch_root/tmp"
  export TMP="$scratch_root/tmp"
  export TEMP="$scratch_root/tmp"
  export UV_CACHE_DIR="$scratch_root/uv-cache"
  export NPM_CONFIG_CACHE="$scratch_root/npm-cache"
  export PIP_CACHE_DIR="$scratch_root/pip-cache"
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

remote_dev_assert_project_git_boundary() {
  local workspace="$1"
  local project="$2"
  local name=""
  local expected=""
  local physical_project=""
  local inside_state=""
  local bare_state=""
  local top=""
  local physical_top=""

  workspace="$(remote_dev_validate_workspace_root "$workspace")" || return $?
  name="${project##*/}"
  expected="$(remote_dev_project_path "$workspace" "$name")" || return $?
  if [[ "$project" != "$expected" ]]; then
    remote_dev_runtime_error "selected project is not an exact direct child of the collection"
    return 2
  fi
  physical_project="$(cd -P -- "$project" 2>/dev/null && pwd -P)" || {
    remote_dev_runtime_error "project path changed during Git-boundary validation: $project"
    return 2
  }
  if [[ "$physical_project" != "$project" ]]; then
    remote_dev_runtime_error "selected project physical path does not match its collection path"
    return 2
  fi

  if inside_state="$(
    env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR \
      GIT_CEILING_DIRECTORIES="$workspace" \
      git -C "$project" rev-parse --is-inside-work-tree 2>/dev/null
  )"; then
    case "$inside_state" in
      true)
        top="$(
          env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR \
            GIT_CEILING_DIRECTORIES="$workspace" \
            git -C "$project" rev-parse --show-toplevel 2>/dev/null
        )" || {
          remote_dev_runtime_error "unable to resolve the selected project's Git worktree root"
          return 2
        }
        physical_top="$(cd -P -- "$top" 2>/dev/null && pwd -P)" || {
          remote_dev_runtime_error "selected project's Git worktree root is unavailable"
          return 2
        }
        if [[ "$physical_top" != "$physical_project" ]]; then
          remote_dev_runtime_error \
            "selected project resolves to a different Git worktree root; agent launch is blocked"
          return 2
        fi
        ;;
      false)
        bare_state="$(
          env -u GIT_DIR -u GIT_WORK_TREE -u GIT_COMMON_DIR \
            GIT_CEILING_DIRECTORIES="$workspace" \
            git -C "$project" rev-parse --is-bare-repository 2>/dev/null
        )" || {
          remote_dev_runtime_error "selected project Git state is ambiguous; agent launch is blocked"
          return 2
        }
        if [[ "$bare_state" != true ]]; then
          remote_dev_runtime_error "selected project Git state is ambiguous; agent launch is blocked"
          return 2
        fi
        ;;
      *)
        remote_dev_runtime_error "selected project Git state is ambiguous; agent launch is blocked"
        return 2
        ;;
    esac
    return 0
  fi

  if [[ -e "$project/.git" || -L "$project/.git" ]]; then
    remote_dev_runtime_error "selected project contains invalid Git metadata; agent launch is blocked"
    return 2
  fi

  # A newly-created/non-Git project is valid. With the ceiling active, Git
  # commands inside it fail as non-repository instead of inheriting the parent.
  return 0
}

remote_dev_enter_project() {
  local workspace="$1"
  local project="$2"
  local name=""
  local expected=""
  local before_identity=""
  local entered_identity=""
  local current_path_identity=""

  remote_dev_prepare_project_git_boundary "$workspace" || return $?
  workspace="$(remote_dev_validate_workspace_root "$workspace")" || return $?
  name="${project##*/}"
  expected="$(remote_dev_project_path "$workspace" "$name")" || return $?
  if [[ "$project" != "$expected" ]]; then
    remote_dev_runtime_error "selected project is not an exact direct child of the collection"
    return 2
  fi

  before_identity="$(stat -Lc '%d:%i' -- "$project" 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed during launch: $project"
    return 2
  }
  if ! builtin cd -P -- "$project" || [[ "$PWD" != "$project" ]]; then
    remote_dev_runtime_error "project path changed during launch: $project"
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  fi
  entered_identity="$(stat -Lc '%d:%i' -- . 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed during launch: $project"
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  }
  current_path_identity="$(stat -Lc '%d:%i' -- "$project" 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed during launch: $project"
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  }
  if [[ "$entered_identity" != "$before_identity" || "$current_path_identity" != "$before_identity" ]]; then
    remote_dev_runtime_error "project path changed during launch: $project"
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  fi
  if ! remote_dev_assert_project_git_boundary "$workspace" "$project"; then
    remote_dev_recover_safe_cwd >/dev/null 2>&1 || true
    return 2
  fi
}

remote_dev_list_projects() {
  local workspace="$1"
  local path=""
  local name=""

  workspace="$(remote_dev_assert_project_collection "$workspace")" || return $?

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
  local listing=""
  local -a projects=()

  workspace="$(remote_dev_assert_project_collection "$workspace")" || return $?

  if [[ -n "$selector" ]]; then
    remote_dev_project_path "$workspace" "$selector"
    return $?
  fi

  listing="$(remote_dev_list_projects "$workspace")" || return $?
  if [[ -n "$listing" ]]; then
    mapfile -t projects <<<"$listing"
  fi
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

  workspace="$(remote_dev_assert_project_collection "$workspace")" || return $?
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

  workspace="$(remote_dev_assert_project_collection "$workspace")" || return $?
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
