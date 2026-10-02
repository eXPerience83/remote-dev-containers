#!/usr/bin/env bash

# Read command names as data. Publish nothing until the complete file is valid.
remote_dev_read_common_tool_baseline() {
  local manifest="${1:-/usr/share/remote-dev/common-tool-baseline.txt}"
  local cmd=""
  local -a commands=()
  local -A seen=()
  if [[ ! -f "$manifest" || -L "$manifest" || ! -r "$manifest" ]]; then
    echo 'ERROR: common tool baseline must be a readable regular non-symlink file' >&2
    return 1
  fi
  while IFS= read -r cmd || [[ -n "$cmd" ]]; do
    if [[ ! "$cmd" =~ ^[a-z][a-z0-9-]*$ ]]; then
      echo 'ERROR: common tool baseline contains an invalid command name' >&2
      return 1
    fi
    if [[ -n "${seen[$cmd]:-}" ]]; then
      echo 'ERROR: common tool baseline contains a duplicate command' >&2
      return 1
    fi
    seen[$cmd]=1
    commands+=("$cmd")
  done < "$manifest"
  if (( ${#commands[@]} == 0 )); then
    echo 'ERROR: common tool baseline is empty' >&2
    return 1
  fi
  printf '%s\n' "${commands[@]}"
}
