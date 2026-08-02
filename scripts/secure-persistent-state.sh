#!/usr/bin/env bash
set -euo pipefail

role="${REMOTE_DEV_ROLE:-codex}"
case "$role" in
  codex|shell|antigravity) ;;
  *)
    echo "ERROR: unsupported REMOTE_DEV_ROLE=$role while securing persistent state" >&2
    exit 2
    ;;
esac

codex_home="${CODEX_HOME:-/root/.codex}"
gh_config_dir="${GH_CONFIG_DIR:-/root/.config/gh}"
git_config_global="${GIT_CONFIG_GLOBAL:-/root/.config/git/config}"
git_config_dir="$(dirname "$git_config_global")"
ssh_dir=/root/.ssh

if [[ "${REMOTE_DEV_ANTIGRAVITY_TESTING:-0}" == "1" ]]; then
  antigravity_state_dir="${REMOTE_DEV_ANTIGRAVITY_STATE_DIR:?test Antigravity state directory is required}"
  antigravity_vendor_state_dir="${REMOTE_DEV_ANTIGRAVITY_VENDOR_STATE_DIR:?test Antigravity vendor state directory is required}"
  antigravity_bin_dir="${REMOTE_DEV_ANTIGRAVITY_BIN_DIR:?test Antigravity binary directory is required}"
else
  antigravity_state_dir=/root/.local/share/remote-dev/antigravity
  antigravity_vendor_state_dir=/root/.gemini/antigravity-cli
  antigravity_bin_dir=/root/.local/bin
fi

secure_dir() {
  local path="$1"
  if [[ -d "$path" ]]; then
    chmod 700 "$path"
  fi
}

secure_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    chmod 600 "$path"
  fi
}

secure_tree() {
  local root="$1"
  [[ -d "$root" ]] || return 0
  find "$root" -type d -exec chmod 700 {} +
  while IFS= read -r -d '' file; do
    if [[ -x "$file" ]]; then
      chmod 700 "$file"
    else
      chmod 600 "$file"
    fi
  done < <(find "$root" -type f -print0)
}

if [[ "$role" == codex ]]; then
  secure_dir "$codex_home"
  secure_file "$codex_home/auth.json"
fi
secure_dir "$gh_config_dir"
secure_dir "$git_config_dir"
secure_dir "$ssh_dir"

secure_file "$gh_config_dir/hosts.yml"
secure_file "$git_config_global"
secure_file "$ssh_dir/config"

for ssh_key in "$ssh_dir"/id_*; do
  [[ -f "$ssh_key" ]] || continue
  case "$ssh_key" in
    *.pub) chmod 644 "$ssh_key" ;;
    *) secure_file "$ssh_key" ;;
  esac
done

if [[ -f "$ssh_dir/known_hosts" ]]; then
  chmod 644 "$ssh_dir/known_hosts"
fi

# Antigravity remains optional. Harden only paths that already exist and never
# create or inspect account contents during normal Codex/Shell startup.
secure_dir "$antigravity_bin_dir"
if [[ -f "$antigravity_bin_dir/agy" && ! -L "$antigravity_bin_dir/agy" ]]; then
  chmod 700 "$antigravity_bin_dir/agy"
fi
secure_tree "$antigravity_state_dir"
secure_tree "$antigravity_vendor_state_dir"
