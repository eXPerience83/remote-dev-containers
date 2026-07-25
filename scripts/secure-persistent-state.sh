#!/usr/bin/env bash
set -euo pipefail

codex_home="${CODEX_HOME:-/root/.codex}"
gh_config_dir="${GH_CONFIG_DIR:-/root/.config/gh}"
git_config_global="${GIT_CONFIG_GLOBAL:-/root/.config/git/config}"
git_config_dir="$(dirname "$git_config_global")"
ssh_dir=/root/.ssh

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

secure_dir "$codex_home"
secure_dir "$gh_config_dir"
secure_dir "$git_config_dir"
secure_dir "$ssh_dir"

secure_file "$codex_home/auth.json"
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
