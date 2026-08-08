#!/usr/bin/env bash
set -euo pipefail

readonly bundled_codex_binary=/usr/local/bin/codex
readonly runtime_manager=/usr/local/bin/remote-dev-codex-runtime
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
  echo "ERROR: run-codex owns the sandbox and approval policy; refusing argument: $argument" >&2
  exit 2
}

is_policy_config_override() {
  local normalized="${1//[[:space:]]/}"
  local key="${normalized%%=*}"

  case "$key" in
    sandbox_mode|approval_policy|ask_for_approval|sandbox|profiles.*.sandbox_mode|profiles.*.approval_policy)
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

case "$approval_mode" in
  autonomous) approval_policy=never ;;
  guarded) approval_policy=untrusted ;;
  *)
    echo "ERROR: internal unsupported Codex approval mode: $approval_mode" >&2
    exit 2
    ;;
esac
readonly approval_mode approval_policy mode_source

if (( print_policy == 1 )); then
  if (( ${#forwarded[@]} > 0 )); then
    fail_usage "--print-policy cannot be combined with Codex arguments"
  fi
  printf '%s\n' \
    'Inner sandbox: disabled explicitly' \
    'Isolation boundary: outer container' \
    "Codex approval mode: $approval_mode" \
    "Codex approval policy: $approval_policy" \
    "Mode source: $mode_source"
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

codex_binary=""
if ! codex_binary="$($runtime_manager resolve)"; then
  echo "WARNING: Codex runtime resolver failed; using immutable bundled fallback" >&2
  codex_binary="$bundled_codex_binary"
fi
if [[ ! -x "$codex_binary" ]]; then
  echo "WARNING: resolved Codex executable is unavailable; using immutable bundled fallback" >&2
  codex_binary="$bundled_codex_binary"
fi

exec "$codex_binary" \
  --sandbox "$sandbox_mode" \
  --ask-for-approval "$approval_policy" \
  "${forwarded[@]}"
