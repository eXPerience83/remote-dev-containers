#!/usr/bin/env bash
set -euo pipefail

# Keep the historical pinned variable for compatibility with the direct-session
# smoke fixture. The runtime resolver may select a newer private package, while
# both names continue to identify the immutable image fallback.
readonly codex_binary=/usr/local/bin/codex
readonly bundled_codex_binary=/usr/local/bin/codex
readonly runtime_manager=/usr/local/bin/remote-dev-codex-runtime
readonly context7_manager=/usr/local/bin/remote-dev-context7
readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
readonly project_boundary_validator=/usr/local/bin/validate-codex-project-boundary
readonly sandbox_mode=danger-full-access
readonly default_approval_mode=autonomous

fail_usage() {
  printf 'ERROR: %s\n' "$1" >&2
  printf 'Usage: run-codex [--approval-mode autonomous|guarded] [--print-policy] [--] [codex arguments...]\n' >&2
  exit 2
}

validate_approval_mode() {
  local mode="$1"
  local source="$2"

  case "$mode" in
    autonomous|guarded)
      ;;
    *)
      fail_usage "unsupported $source approval mode: $mode (autonomous|guarded)"
      ;;
  esac
}

reject_policy_override() {
  local argument="$1"
  echo "ERROR: run-codex owns the sandbox, approval and project-boundary policy; refusing argument: $argument" >&2
  exit 2
}

is_policy_config_override() {
  local normalized="${1//[[:space:]]/}"
  local key="${normalized%%=*}"

  case "$key" in
    sandbox_mode|approval_policy|ask_for_approval|sandbox|projects|projects.*|profiles.*.sandbox_mode|profiles.*.approval_policy|profiles.*.projects|profiles.*.projects.*|shell_environment_policy|shell_environment_policy.*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

explicit_mode=""
explicit_mode_set=0
print_policy=0
forwarded=()

while (( $# > 0 )); do
  argument="$1"
  shift

  case "$argument" in
    --)
      forwarded+=(-- "$@")
      break
      ;;
    --approval-mode)
      if (( explicit_mode_set == 1 )); then
        fail_usage "--approval-mode may be specified only once"
      fi
      if (( $# == 0 )) || [[ "$1" == -- ]]; then
        fail_usage "--approval-mode requires autonomous or guarded"
      fi
      explicit_mode="$1"
      explicit_mode_set=1
      shift
      ;;
    --approval-mode=*)
      if (( explicit_mode_set == 1 )); then
        fail_usage "--approval-mode may be specified only once"
      fi
      explicit_mode="${argument#*=}"
      if [[ -z "$explicit_mode" ]]; then
        fail_usage "--approval-mode requires autonomous or guarded"
      fi
      explicit_mode_set=1
      ;;
    --print-policy)
      print_policy=1
      ;;
    *)
      forwarded+=("$argument")
      ;;
  esac
done

approval_mode=""
mode_source=""
if (( explicit_mode_set == 1 )); then
  validate_approval_mode "$explicit_mode" per-launch
  approval_mode="$explicit_mode"
  mode_source=per-launch
elif [[ -n "${REMOTE_DEV_CODEX_APPROVAL_MODE:-}" ]]; then
  validate_approval_mode "$REMOTE_DEV_CODEX_APPROVAL_MODE" deployment
  approval_mode="$REMOTE_DEV_CODEX_APPROVAL_MODE"
  mode_source=deployment
else
  approval_mode="$default_approval_mode"
  mode_source=default
fi

readonly approval_mode mode_source

if (( print_policy == 1 )); then
  if (( ${#forwarded[@]} > 0 )); then
    fail_usage "--print-policy cannot be combined with Codex arguments"
  fi
  printf '%s\n' \
    'Inner sandbox: disabled explicitly' \
    'Isolation boundary: outer container' \
    "Codex approval mode: $approval_mode"
  if [[ "$approval_mode" == guarded ]]; then
    printf '%s\n' \
      'Project trust: untrusted (launch-scoped)' \
      'Approval behavior: prompt for commands except explicit exec-policy allows'
  else
    printf '%s\n' 'Codex approval policy: never'
  fi
  printf '%s\n' "Mode source: $mode_source"
  exit 0
fi

expect_config_value=0
for argument in "${forwarded[@]}"; do
  if [[ "$argument" == "--" && $expect_config_value -eq 0 ]]; then
    break
  fi

  if (( expect_config_value == 1 )); then
    if is_policy_config_override "$argument"; then
      reject_policy_override "--config $argument"
    fi
    expect_config_value=0
    continue
  fi

  case "$argument" in
    --sandbox|--sandbox=*|-s|-s=*|-s?*)
      reject_policy_override "$argument"
      ;;
    --ask-for-approval|--ask-for-approval=*|--approval-policy|--approval-policy=*|-a|-a=*|-a?*)
      reject_policy_override "$argument"
      ;;
    --dangerously-bypass-approvals-and-sandbox|--dangerously-bypass-approvals-and-sandbox=*|--dangerously-auto-approve-everything|--yolo|--full-auto)
      reject_policy_override "$argument"
      ;;
    --profile|--profile=*|-p|-p=*|-p?*)
      reject_policy_override "$argument"
      ;;
    -c|--config)
      expect_config_value=1
      ;;
    -c=*|--config=*)
      config_value="${argument#*=}"
      if is_policy_config_override "$config_value"; then
        reject_policy_override "$argument"
      fi
      ;;
    -c?*)
      config_value="${argument#-c}"
      if is_policy_config_override "$config_value"; then
        reject_policy_override "$argument"
      fi
      ;;
  esac
done
if (( expect_config_value == 1 )); then
  fail_usage "--config requires a value"
fi

runtime_manager_command=("$runtime_manager" resolve)
resolved_codex_binary=""
if ! resolved_codex_binary="$("${runtime_manager_command[@]}")"; then
  echo "WARNING: Codex runtime resolver failed; using immutable bundled fallback" >&2
  resolved_codex_binary="$bundled_codex_binary"
elif [[ "$resolved_codex_binary" == /usr/local/bin/codex ]]; then
  # Normalize the resolver's bundled sentinel through the pinned fallback name.
  # This also keeps direct-session smoke fixtures independent of the host image.
  resolved_codex_binary="$codex_binary"
fi
if [[ ! -x "$resolved_codex_binary" ]]; then
  echo "WARNING: resolved Codex executable is unavailable; using immutable bundled fallback" >&2
  resolved_codex_binary="$bundled_codex_binary"
fi

configure_context7_environment() {
  local key_path="" manager_status=0 expected_key_path=""
  local codex_home="${CODEX_HOME:-/root/.codex}"
  local -a expected_key_path_command=(
    python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]) / ".remote-dev-context7" / "api-key")' "$codex_home"
  )
  local -a context7_key_command=("$context7_manager" key-file --active)
  local -a context7_read_key_command=()

  if ! expected_key_path="$("${expected_key_path_command[@]}" 2>/dev/null)"; then
    echo "WARNING: managed Context7 credential path could not be normalized safely; starting without the managed API key" >&2
    unset CONTEXT7_API_KEY
    return 0
  fi

  if key_path="$("${context7_key_command[@]}" 2>/dev/null)"; then
    if [[ "$key_path" != "$expected_key_path" ]]; then
      echo "WARNING: managed Context7 credential path failed validation; starting without the managed API key" >&2
      unset CONTEXT7_API_KEY
      return 0
    fi

    context7_read_key_command=(
      python3 -c '
import os
import stat
import sys

home = sys.argv[1]
directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
key_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
home_fd = state_fd = key_fd = None
try:
    home_fd = os.open(home, directory_flags)
    state_fd = os.open(".remote-dev-context7", directory_flags, dir_fd=home_fd)
    state_info = os.fstat(state_fd)
    if not stat.S_ISDIR(state_info.st_mode):
        raise SystemExit(2)
    if state_info.st_uid != os.geteuid() or stat.S_IMODE(state_info.st_mode) & 0o077:
        raise SystemExit(2)

    key_fd = os.open("api-key", key_flags, dir_fd=state_fd)
    key_info = os.fstat(key_fd)
    if not stat.S_ISREG(key_info.st_mode):
        raise SystemExit(2)
    if key_info.st_uid != os.geteuid() or stat.S_IMODE(key_info.st_mode) & 0o077:
        raise SystemExit(2)
    if key_info.st_size <= 0 or key_info.st_size > 16384:
        raise SystemExit(2)

    chunks = []
    remaining = 16385
    while remaining > 0:
        chunk = os.read(key_fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if not data or len(data) > 16384:
        raise SystemExit(2)
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SystemExit(2)
    if value != value.strip() or any(character.isspace() for character in value):
        raise SystemExit(2)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SystemExit(2)
    sys.stdout.write(value)
finally:
    if key_fd is not None:
        os.close(key_fd)
    if state_fd is not None:
        os.close(state_fd)
    if home_fd is not None:
        os.close(home_fd)
' "$codex_home"
    )
    if ! CONTEXT7_API_KEY="$("${context7_read_key_command[@]}" 2>/dev/null)"; then
      echo "WARNING: managed Context7 credential could not be read safely; starting without the managed API key" >&2
      unset CONTEXT7_API_KEY
      return 0
    fi
    export CONTEXT7_API_KEY
    return 0
  else
    manager_status=$?
  fi

  case "$manager_status" in
    4)
      # No Remote Dev-owned Context7 block. Preserve any explicitly user-managed
      # environment because the project does not own that configuration.
      ;;
    5)
      # A healthy Remote Dev-managed anonymous integration must not inherit an
      # unrelated/stale key from the container environment.
      unset CONTEXT7_API_KEY
      ;;
    *)
      unset CONTEXT7_API_KEY
      echo "WARNING: managed Context7 state is unavailable or unsafe; starting Codex without the managed API key" >&2
      ;;
  esac
}

configure_context7_environment

# Keep top-level informational commands usable even when no project is selected.
# They do not execute model-reachable shell commands and therefore do not need
# the project collection boundary.
informational_only=0
if (( ${#forwarded[@]} == 1 )); then
  case "${forwarded[0]}" in
    --help|-h|--version|-V) informational_only=1 ;;
  esac
fi

owned_policy_args=(--sandbox "$sandbox_mode")
if (( informational_only == 0 )); then
  [[ -f "$runtime_lib" && -r "$runtime_lib" && ! -L "$runtime_lib" ]] \
    || { echo "ERROR: Remote Dev project-boundary definitions are unavailable" >&2; exit 1; }
  # shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
  source "$runtime_lib"
  [[ -x "$project_boundary_validator" && ! -L "$project_boundary_validator" ]] \
    || { echo "ERROR: Codex project-boundary validator is unavailable" >&2; exit 1; }

  workspace="$(remote_dev_workspace_root)" || exit $?
  remote_dev_prepare_project_git_boundary "$workspace" || exit $?

  active_project=""
  expect_cd_value=0
  for argument in "${forwarded[@]}"; do
    if (( expect_cd_value == 1 )); then
      active_project="$argument"
      expect_cd_value=0
      continue
    fi
    case "$argument" in
      --) break ;;
      --cd|-C) expect_cd_value=1 ;;
      --cd=*) active_project="${argument#*=}" ;;
      -C?*) active_project="${argument#-C}" ;;
    esac
  done
  if (( expect_cd_value == 1 )); then
    fail_usage "--cd requires a project directory"
  fi
  if [[ -z "$active_project" ]]; then
    if ! active_project="$(pwd -P 2>/dev/null)"; then
      fail_usage "managed Codex launch requires a valid current project directory"
    fi
  elif [[ "$active_project" != /* ]]; then
    active_project="$PWD/$active_project"
  fi
  if ! active_project="$(cd -P -- "$active_project" 2>/dev/null && pwd -P)"; then
    fail_usage "managed Codex launch requires an existing project directory"
  fi

  remote_dev_assert_project_git_boundary "$workspace" "$active_project" || exit $?
  project_identity="$(stat -Lc '%d:%i' -- "$active_project" 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed during Codex launch: $active_project"
    exit 2
  }

  if ! "$project_boundary_validator" \
    --codex-binary "$resolved_codex_binary" \
    --cwd "$active_project" \
    --ceiling "$workspace"; then
    echo "ERROR: Codex effective configuration cannot preserve the required project Git boundary" >&2
    exit 2
  fi
  current_project_identity="$(stat -Lc '%d:%i' -- "$active_project" 2>/dev/null)" || {
    remote_dev_runtime_error "project path changed during Codex configuration validation: $active_project"
    exit 2
  }
  if [[ "$current_project_identity" != "$project_identity" ]]; then
    remote_dev_runtime_error "project path changed during Codex configuration validation: $active_project"
    exit 2
  fi
  remote_dev_assert_project_git_boundary "$workspace" "$active_project" || exit $?

  workspace_key="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$workspace")"
  owned_policy_args+=(-c "shell_environment_policy.set.GIT_CEILING_DIRECTORIES=$workspace_key")

  if [[ "$approval_mode" == guarded ]]; then
    project_key="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$active_project")"
    owned_policy_args+=(-c "projects={$project_key={trust_level=\"untrusted\"}}")
  fi
fi

if [[ "$approval_mode" == autonomous ]]; then
  owned_policy_args+=(--ask-for-approval never)
fi

exec "$resolved_codex_binary" "${owned_policy_args[@]}" "${forwarded[@]}"
