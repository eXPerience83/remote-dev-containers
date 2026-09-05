#!/usr/bin/env bash
set -euo pipefail

runtime_lib="${REMOTE_DEV_RUNTIME_LIB:-/usr/local/lib/remote-dev/remote-dev-runtime.sh}"
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

assert_eq() {
  local expected="$1"
  local actual="$2"
  local label="$3"
  [[ "$actual" == "$expected" ]] || fail "$label: expected '$expected', got '$actual'"
}

assert_fails_with() {
  local expected_status="$1"
  local expected_text="$2"
  shift 2
  local output=""
  local status=0

  output="$("$@" 2>&1)" || status=$?
  (( status == expected_status )) || fail "expected status $expected_status, got $status from $*; output: $output"
  [[ "$output" == *"$expected_text"* ]] || fail "expected failure containing '$expected_text', got: $output"
}

root="$(mktemp -d)"
trap 'rm -rf -- "$root"' EXIT

# Clean collection + empty project: Remote Dev owns the Git discovery ceiling,
# so an empty child cannot accidentally inherit repository state from a parent.
workspace="$root/clean/workspace"
mkdir -p "$workspace/empty"
assert_eq "$workspace" "$(remote_dev_assert_project_collection "$workspace")" "clean collection"
remote_dev_prepare_project_git_boundary "$workspace"
assert_eq "$workspace" "$GIT_CEILING_DIRECTORIES" "managed Git ceiling"
remote_dev_assert_project_git_boundary "$workspace" "$workspace/empty"
if git -C "$workspace/empty" rev-parse --show-toplevel >/dev/null 2>&1; then
  fail "empty project unexpectedly resolved a Git worktree"
fi

# A normal repository rooted at the selected child remains valid.
git -C "$workspace/empty" init -q
remote_dev_assert_project_git_boundary "$workspace" "$workspace/empty"
assert_eq "$workspace/empty" "$(git -C "$workspace/empty" rev-parse --show-toplevel)" "child Git root"

# The common entry helper must establish both physical-cwd and Git boundaries.
(
  remote_dev_enter_project "$workspace" "$workspace/empty"
  assert_eq "$workspace/empty" "$PWD" "entered project cwd"
  assert_eq "$workspace" "$GIT_CEILING_DIRECTORIES" "entered project ceiling"
)

# Explicit Git routing variables can bypass selected-project semantics and are
# therefore rejected, while ordinary Git authentication/config variables are
# intentionally not owned here.
assert_fails_with 2 "inherited GIT_DIR" \
  env GIT_DIR="$workspace/empty/.git" bash -c 'source "$1"; remote_dev_prepare_project_git_boundary "$2"' _ "$runtime_lib" "$workspace"
assert_fails_with 2 "inherited GIT_WORK_TREE" \
  env GIT_WORK_TREE="$workspace/empty" bash -c 'source "$1"; remote_dev_prepare_project_git_boundary "$2"' _ "$runtime_lib" "$workspace"
assert_fails_with 2 "inherited GIT_COMMON_DIR" \
  env GIT_COMMON_DIR="$workspace/empty/.git" bash -c 'source "$1"; remote_dev_prepare_project_git_boundary "$2"' _ "$runtime_lib" "$workspace"

# Managed Git ceiling entries are colon-separated on Linux. Reject a collection
# path containing ':' for agent execution instead of creating an ambiguous
# boundary, while keeping ordinary workspace validation/recovery available.
colon_workspace="$root/with:colon/workspace"
mkdir -p "$colon_workspace/project"
assert_eq "$colon_workspace" "$(remote_dev_validate_workspace_root "$colon_workspace")" "colon path remains shell-recoverable"
assert_fails_with 2 "cannot contain ':'" remote_dev_prepare_project_git_boundary "$colon_workspace"

# Collection-root .git contamination is fail-closed for every project action.
contaminated="$root/contaminated/workspace"
mkdir -p "$contaminated/alpha" "$contaminated/beta"
printf 'keep\n' > "$contaminated/beta/canary"
git -C "$contaminated" init -q
assert_fails_with 2 "CRITICAL: project collection root contains .git" remote_dev_assert_project_collection "$contaminated"
assert_fails_with 2 "CRITICAL: project collection root contains .git" remote_dev_list_projects "$contaminated"
assert_fails_with 2 "CRITICAL: project collection root contains .git" remote_dev_resolve_project "$contaminated" alpha
assert_fails_with 2 "CRITICAL: project collection root contains .git" remote_dev_create_project "$contaminated" gamma
assert_fails_with 2 "CRITICAL: project collection root contains .git" remote_dev_delete_project "$contaminated" beta beta
[[ -f "$contaminated/beta/canary" ]] || fail "blocked deletion modified sibling contents"

# Any .git entry is unsafe at the collection root, including dangling symlinks
# and malformed gitfiles. Never follow or repair it automatically.
symlink_root="$root/symlink/workspace"
mkdir -p "$symlink_root/project"
ln -s "$root/does-not-exist" "$symlink_root/.git"
assert_fails_with 2 "CRITICAL: project collection root contains .git" remote_dev_assert_project_collection "$symlink_root"

malformed_root="$root/malformed/workspace"
mkdir -p "$malformed_root/project"
printf 'not a gitfile\n' > "$malformed_root/.git"
assert_fails_with 2 "CRITICAL: project collection root contains .git" remote_dev_assert_project_collection "$malformed_root"

# A bare repository at the collection root has no .git child, so detect it
# independently through bounded Git plumbing.
bare_root="$root/bare/workspace"
mkdir -p "$(dirname "$bare_root")"
git init --bare -q "$bare_root"
assert_fails_with 2 "bare Git repository" remote_dev_assert_project_collection "$bare_root"

# Malformed Git metadata at the selected child is not silently treated as a
# newly-created non-repository project.
invalid_child_root="$root/invalid-child/workspace"
mkdir -p "$invalid_child_root/project"
printf 'broken\n' > "$invalid_child_root/project/.git"
remote_dev_prepare_project_git_boundary "$invalid_child_root"
assert_fails_with 2 "invalid Git metadata" remote_dev_assert_project_git_boundary "$invalid_child_root" "$invalid_child_root/project"

# Reproduce the important destructive mechanism only inside a disposable
# control fixture: once the collection itself is the repository, an explicit
# root-level clean treats sibling project directories as untracked content.
control="$root/unprotected-control/workspace"
mkdir -p "$control/project-a" "$control/project-b"
printf 'canary\n' > "$control/project-b/DO_NOT_DELETE"
git -C "$control" init -q
git -C "$control" clean -fdq
[[ ! -e "$control/project-b/DO_NOT_DELETE" ]] || fail "control fixture did not reproduce root-level sibling cleanup"

# Under the managed contract, the same contaminated layout is rejected before
# any agent command can execute, so the canary remains intact.
protected="$root/protected/workspace"
mkdir -p "$protected/project-a" "$protected/project-b"
printf 'canary\n' > "$protected/project-b/DO_NOT_DELETE"
git -C "$protected" init -q
agent_marker="$root/agent-ran"
if (
  remote_dev_prepare_project_git_boundary "$protected"
  printf 'ran\n' > "$agent_marker"
); then
  fail "contaminated collection unexpectedly passed managed preflight"
fi
[[ ! -e "$agent_marker" ]] || fail "fake agent executed after contaminated preflight"
assert_eq canary "$(<"$protected/project-b/DO_NOT_DELETE")" "protected sibling canary"

# Safe-cwd recovery is a shell builtin and still works when the original cwd
# pathname has been removed by an agent.
deleted_cwd="$root/deleted-cwd"
mkdir -p "$deleted_cwd"
(
  cd "$deleted_cwd"
  rmdir "$deleted_cwd"
  remote_dev_recover_safe_cwd
  assert_eq / "$PWD" "safe cwd recovery"
)

echo "Project collection Git-boundary regressions: OK"
