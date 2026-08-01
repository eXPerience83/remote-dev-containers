#!/usr/bin/env bash
set -euo pipefail

runtime_lib="${REMOTE_DEV_RUNTIME_LIB:-/usr/local/lib/remote-dev/remote-dev-runtime.sh}"
secure_state="${REMOTE_DEV_SECURE_STATE:-/usr/local/bin/secure-persistent-state}"
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"

assert_eq() {
  local expected="$1"
  local actual="$2"
  local label="$3"

  if [[ "$actual" != "$expected" ]]; then
    printf 'ERROR: %s: expected %q, got %q\n' "$label" "$expected" "$actual" >&2
    exit 1
  fi
}

assert_fails_with() {
  local expected_status="$1"
  local expected_text="$2"
  shift 2
  local output=""
  local status=0

  output="$("$@" 2>&1)" || status=$?
  if (( status != expected_status )); then
    printf 'ERROR: expected status %s, got %s from:' "$expected_status" "$status" >&2
    printf ' %q' "$@" >&2
    printf '\n%s\n' "$output" >&2
    exit 1
  fi
  if [[ "$output" != *"$expected_text"* ]]; then
    printf 'ERROR: expected failure containing %q, got:\n%s\n' "$expected_text" "$output" >&2
    exit 1
  fi
}

assert_mode() {
  local expected="$1"
  local path="$2"
  local label="$3"
  local actual=""

  actual="$(stat -c '%a' "$path")"
  assert_eq "$expected" "$actual" "$label"
}

assert_eq codex "$(env -u REMOTE_DEV_ROLE bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib")" "default role"
assert_eq shell "$(env REMOTE_DEV_ROLE=shell bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib")" "shell role"
assert_fails_with 2 "reserved but not implemented" env REMOTE_DEV_ROLE=launcher bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib"
assert_fails_with 2 "unsupported REMOTE_DEV_ROLE" env REMOTE_DEV_ROLE='codex;id' bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib"

assert_eq menu "$(env -u REMOTE_DEV_START_MODE START_MODE=menu bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib")" "legacy menu mode"
assert_eq agent "$(env -u REMOTE_DEV_START_MODE START_MODE=codex bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib")" "legacy codex mode"
assert_eq shell "$(env REMOTE_DEV_START_MODE=shell START_MODE=codex bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib")" "neutral mode precedence"
assert_fails_with 2 "unsupported REMOTE_DEV_START_MODE" env REMOTE_DEV_START_MODE='agent;id' bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib"
assert_fails_with 2 "unsupported START_MODE=agent" env -u REMOTE_DEV_START_MODE START_MODE=agent bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib"
assert_fails_with 2 "unsupported START_MODE=codex;id" env -u REMOTE_DEV_START_MODE START_MODE='codex;id' bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib"
assert_fails_with 2 "not available" env REMOTE_DEV_START_MODE=agent bash -c 'source "$1"; remote_dev_resolve_start_mode shell' _ "$runtime_lib"

assert_eq codex "$(remote_dev_default_tmux_session codex)" "codex compatibility session"
assert_eq remote-dev-shell "$(remote_dev_default_tmux_session shell)" "shell role session"

state_root="$(mktemp -d)"
trap 'rm -rf "$state_root"' EXIT
codex_home="$state_root/codex"
gh_dir="$state_root/gh"
git_dir="$state_root/git"
mkdir -p "$codex_home" "$gh_dir" "$git_dir"
printf 'synthetic\n' > "$codex_home/auth.json"
printf 'synthetic\n' > "$gh_dir/hosts.yml"
printf 'synthetic\n' > "$git_dir/config"
chmod 0777 "$codex_home" "$gh_dir" "$git_dir"
chmod 0666 "$codex_home/auth.json" "$gh_dir/hosts.yml" "$git_dir/config"

REMOTE_DEV_ROLE=shell \
CODEX_HOME="$codex_home" \
GH_CONFIG_DIR="$gh_dir" \
GIT_CONFIG_GLOBAL="$git_dir/config" \
  "$secure_state"
assert_mode 777 "$codex_home" "shell role Codex directory"
assert_mode 666 "$codex_home/auth.json" "shell role Codex credential"
assert_mode 700 "$gh_dir" "shell role GitHub directory"
assert_mode 600 "$gh_dir/hosts.yml" "shell role GitHub credential"
assert_mode 700 "$git_dir" "shell role Git directory"
assert_mode 600 "$git_dir/config" "shell role Git configuration"

REMOTE_DEV_ROLE=codex \
CODEX_HOME="$codex_home" \
GH_CONFIG_DIR="$gh_dir" \
GIT_CONFIG_GLOBAL="$git_dir/config" \
  "$secure_state"
assert_mode 700 "$codex_home" "Codex role directory"
assert_mode 600 "$codex_home/auth.json" "Codex role credential"

echo "Role-neutral runtime resolver and state-boundary tests: OK"
