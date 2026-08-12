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
assert_eq launcher "$(env REMOTE_DEV_ROLE=launcher bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib")" "launcher role"
assert_eq shell "$(env REMOTE_DEV_ROLE=shell bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib")" "shell role"
assert_fails_with 2 "experimental and blocked pending TrueNAS validation" \
  env REMOTE_DEV_ROLE=antigravity bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib"
assert_eq antigravity "$(env REMOTE_DEV_ROLE=antigravity REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib")" "explicit experimental Antigravity role"
assert_fails_with 2 "experimental and blocked pending TrueNAS validation" \
  env REMOTE_DEV_ROLE=antigravity REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=yes bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib"
assert_fails_with 2 "reserved but not implemented" env REMOTE_DEV_ROLE=claude bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib"
assert_fails_with 2 "unsupported REMOTE_DEV_ROLE" env REMOTE_DEV_ROLE='codex;id' bash -c 'source "$1"; remote_dev_resolve_role' _ "$runtime_lib"

assert_eq menu "$(env -u REMOTE_DEV_START_MODE START_MODE=menu bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib")" "legacy menu mode"
assert_eq agent "$(env -u REMOTE_DEV_START_MODE START_MODE=codex bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib")" "legacy Codex mode"
assert_eq agent "$(env -u REMOTE_DEV_START_MODE START_MODE=antigravity bash -c 'source "$1"; remote_dev_resolve_start_mode antigravity' _ "$runtime_lib")" "legacy Antigravity mode"
assert_fails_with 2 "requires REMOTE_DEV_ROLE=codex" env -u REMOTE_DEV_START_MODE REMOTE_DEV_ROLE=antigravity START_MODE=codex bash -c 'source "$1"; remote_dev_resolve_start_mode antigravity' _ "$runtime_lib"
assert_fails_with 2 "requires REMOTE_DEV_ROLE=antigravity" env -u REMOTE_DEV_START_MODE REMOTE_DEV_ROLE=codex START_MODE=antigravity bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib"
assert_eq shell "$(env REMOTE_DEV_START_MODE=shell START_MODE=codex bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib")" "neutral mode precedence"
assert_eq menu "$(env -u REMOTE_DEV_START_MODE START_MODE=menu bash -c 'source "$1"; remote_dev_resolve_start_mode launcher' _ "$runtime_lib")" "launcher menu mode"
assert_fails_with 2 "supports only" env REMOTE_DEV_START_MODE=agent bash -c 'source "$1"; remote_dev_resolve_start_mode launcher' _ "$runtime_lib"
assert_fails_with 2 "supports only" env REMOTE_DEV_START_MODE=shell bash -c 'source "$1"; remote_dev_resolve_start_mode launcher' _ "$runtime_lib"
assert_fails_with 2 "unsupported REMOTE_DEV_START_MODE" env REMOTE_DEV_START_MODE='agent;id' bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib"
assert_fails_with 2 "unsupported START_MODE=agent" env -u REMOTE_DEV_START_MODE START_MODE=agent bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib"
assert_fails_with 2 "unsupported START_MODE=codex;id" env -u REMOTE_DEV_START_MODE START_MODE='codex;id' bash -c 'source "$1"; remote_dev_resolve_start_mode codex' _ "$runtime_lib"
assert_fails_with 2 "not available" env REMOTE_DEV_START_MODE=agent bash -c 'source "$1"; remote_dev_resolve_start_mode shell' _ "$runtime_lib"

assert_eq codex "$(remote_dev_default_tmux_session codex)" "Codex compatibility session"
assert_eq antigravity "$(remote_dev_default_tmux_session antigravity)" "Antigravity role session"
assert_eq remote-dev-shell "$(remote_dev_default_tmux_session shell)" "shell role session"
assert_fails_with 2 "does not use tmux" remote_dev_default_tmux_session launcher

test_root="$(mktemp -d)"
trap 'rm -rf "$test_root"' EXIT
workspace="$test_root/workspace"
mkdir -p "$workspace"

assert_eq "$workspace" "$(WORKSPACE="$workspace" remote_dev_workspace_root)" "workspace root"
assert_fails_with 2 "safe absolute path" remote_dev_validate_workspace_root ../workspace
assert_fails_with 2 "too broad" remote_dev_validate_workspace_root /
ln -s "$workspace" "$test_root/workspace-link"
assert_fails_with 2 "symlinked path component" remote_dev_validate_workspace_root "$test_root/workspace-link"

for invalid_name in '' '.hidden' '..' '../escape' 'nested/name' '-option' 'with space' $'line\nbreak'; do
  assert_fails_with 2 "invalid project name" remote_dev_validate_project_name "$invalid_name"
done
assert_eq pollenlevels "$(remote_dev_validate_project_name pollenlevels)" "valid project name"
assert_eq repo.v2_test-1 "$(remote_dev_validate_project_name repo.v2_test-1)" "valid punctuation project name"

assert_fails_with 2 "no project directories" remote_dev_resolve_project "$workspace"
alpha_path="$(remote_dev_create_project "$workspace" alpha)"
assert_eq "$workspace/alpha" "$alpha_path" "created project path"
assert_eq alpha "$(remote_dev_list_projects "$workspace")" "single project listing"
assert_eq "$workspace/alpha" "$(remote_dev_resolve_project "$workspace")" "single project auto-resolution"
assert_fails_with 2 "already exists" remote_dev_create_project "$workspace" alpha

beta_path="$(remote_dev_create_project "$workspace" beta)"
assert_eq "$workspace/beta" "$beta_path" "second created project path"
assert_eq $'alpha\nbeta' "$(remote_dev_list_projects "$workspace")" "sorted project listing"
assert_fails_with 2 "multiple projects found" remote_dev_resolve_project "$workspace"
assert_eq "$workspace/beta" "$(remote_dev_resolve_project "$workspace" beta)" "explicit project resolution"
assert_eq "$workspace/alpha" "$(REMOTE_DEV_PROJECT=alpha remote_dev_resolve_project "$workspace")" "environment project resolution"
assert_fails_with 2 "project does not exist" remote_dev_resolve_project "$workspace" missing

mkdir "$workspace/.hidden-manual" "$workspace/with space"
ln -s "$workspace/alpha" "$workspace/linked"
assert_eq $'alpha\nbeta' "$(remote_dev_list_projects "$workspace")" "invalid and symlink entries excluded"
assert_fails_with 2 "must not be a symlink" remote_dev_project_path "$workspace" linked

printf 'keep\n' > "$workspace/alpha/keep.txt"
printf 'delete\n' > "$workspace/beta/delete.txt"
assert_fails_with 2 "confirmation did not match" remote_dev_delete_project "$workspace" beta wrong
[[ -f "$workspace/beta/delete.txt" ]] || { echo "ERROR: wrong confirmation deleted project contents" >&2; exit 1; }
remote_dev_delete_project "$workspace" beta beta
[[ ! -e "$workspace/beta" ]] || { echo "ERROR: confirmed project deletion left project path" >&2; exit 1; }
[[ -f "$workspace/alpha/keep.txt" ]] || { echo "ERROR: project deletion modified sibling project" >&2; exit 1; }
assert_eq alpha "$(remote_dev_list_projects "$workspace")" "project listing after deletion"

echo "Role-neutral project resolver and destructive-operation guards: OK"

state_root="$test_root/state"
codex_home="$state_root/codex"
gh_dir="$state_root/gh"
git_dir="$state_root/git"
mkdir -p "$codex_home" "$gh_dir" "$git_dir"
printf 'synthetic\n' > "$codex_home/auth.json"
printf 'synthetic\n' > "$gh_dir/hosts.yml"
printf 'synthetic\n' > "$git_dir/config"
chmod 0777 "$codex_home" "$gh_dir" "$git_dir"
chmod 0666 "$codex_home/auth.json" "$gh_dir/hosts.yml" "$git_dir/config"

assert_fails_with 2 "unsupported REMOTE_DEV_ROLE=launcher" \
  env REMOTE_DEV_ROLE=launcher CODEX_HOME="$codex_home" GH_CONFIG_DIR="$gh_dir" \
    GIT_CONFIG_GLOBAL="$git_dir/config" "$secure_state"
assert_mode 777 "$codex_home" "launcher must not harden Codex directory"
assert_mode 666 "$codex_home/auth.json" "launcher must not touch Codex credential"

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

echo "Launcher, role-neutral runtime and state-boundary tests: OK"
