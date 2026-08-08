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

secure_private_tree() {
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
  codex_runtime_root="${REMOTE_DEV_CODEX_RUNTIME_ROOT:-/root/.local/share/remote-dev/codex-runtime}"
  secure_dir "$codex_home"
  secure_file "$codex_home/auth.json"
  secure_private_tree "$codex_runtime_root"
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

if [[ "$role" == antigravity ]]; then
  readonly paths_lib=/usr/local/lib/remote-dev/antigravity-paths.sh
  [[ -r "$paths_lib" && ! -L "$paths_lib" ]] || {
    echo "ERROR: immutable Antigravity path definitions are unavailable" >&2
    exit 1
  }
  # shellcheck source=/usr/local/lib/remote-dev/antigravity-paths.sh
  source "$paths_lib"

  secure_dir "$ANTIGRAVITY_BIN_DIR"
  if [[ -f "$ANTIGRAVITY_BINARY" && ! -L "$ANTIGRAVITY_BINARY" ]]; then
    chmod 700 "$ANTIGRAVITY_BINARY"
  fi
  secure_private_tree "$ANTIGRAVITY_STATE_DIR"
  secure_private_tree "$ANTIGRAVITY_VENDOR_STATE_DIR"
fi
