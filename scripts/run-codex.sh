#!/usr/bin/env bash
set -euo pipefail

readonly codex_binary=/usr/local/bin/codex
readonly sandbox_mode=danger-full-access
readonly approval_policy=untrusted

if [[ "${1:-}" == "--print-policy" ]]; then
  printf '%s\n' \
    'Inner sandbox: disabled explicitly' \
    'Isolation boundary: outer container' \
    "Codex approval policy: $approval_policy"
  exit 0
fi

reject_policy_override() {
  local argument="$1"
  echo "ERROR: run-codex fixes the sandbox and approval policy; refusing argument: $argument" >&2
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

expect_config_value=0
for argument in "$@"; do
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

exec "$codex_binary" \
  --sandbox "$sandbox_mode" \
  --ask-for-approval "$approval_policy" \
  "$@"
