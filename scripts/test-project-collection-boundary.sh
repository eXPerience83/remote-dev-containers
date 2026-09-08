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

# The ceiling must also stop an empty project from inheriting a Git repository
# that exists above the collection root. This is distinct from rejecting a
# repository whose own top-level is the collection itself.
ancestor_repo="$root/ancestor-repo"
ancestor_workspace="$ancestor_repo/workspace"
mkdir -p "$ancestor_workspace/empty"
git -C "$ancestor_repo" init -q
remote_dev_prepare_project_git_boundary "$ancestor_workspace"
remote_dev_assert_project_git_boundary "$ancestor_workspace" "$ancestor_workspace/empty"
if git -C "$ancestor_workspace/empty" rev-parse --show-toplevel >/dev/null 2>&1; then
  fail "empty project inherited a Git repository above the managed collection ceiling"
fi

# A normal repository rooted at the selected child remains valid.
git -C "$workspace/empty" init -q
remote_dev_assert_project_git_boundary "$workspace" "$workspace/empty"
assert_eq "$workspace/empty" "$(git -C "$workspace/empty" rev-parse --show-toplevel)" "child Git root"
env GIT_OBJECT_DIRECTORY= bash -c \
  'source "$1"; remote_dev_assert_project_git_boundary "$2" "$3"' \
  _ "$runtime_lib" "$workspace" "$workspace/empty"

# A legitimate linked worktree rooted at the selected child uses a .git file,
# not a directory. Preserve that topology when its effective top-level is still
# exactly the selected project.
linked_source="$root/linked-source"
linked_workspace="$root/linked/workspace"
linked_project="$linked_workspace/project"
mkdir -p "$linked_source" "$linked_workspace"
git -C "$linked_source" init -q
printf 'tracked\n' >"$linked_source/tracked.txt"
git -C "$linked_source" add tracked.txt
git -C "$linked_source" -c user.name=remote-dev-test -c user.email=test@example.invalid \
  commit -qm initial
git -C "$linked_source" worktree add -q --detach "$linked_project" HEAD
[[ -f "$linked_project/.git" ]] || fail "linked-worktree fixture did not create a child .git file"
remote_dev_prepare_project_git_boundary "$linked_workspace"
remote_dev_assert_project_git_boundary "$linked_workspace" "$linked_project"
assert_eq "$linked_project" \
  "$(GIT_CEILING_DIRECTORIES="$linked_workspace" git -C "$linked_project" rev-parse --show-toplevel)" \
  "linked child worktree root"

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
assert_fails_with 2 "inherited GIT_OBJECT_DIRECTORY" \
  env GIT_OBJECT_DIRECTORY="$root/redirected-objects" bash -c 'source "$1"; remote_dev_prepare_project_git_boundary "$2"' _ "$runtime_lib" "$workspace"
for variable in GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_OBJECT_DIRECTORY; do
  assert_fails_with 2 "inherited $variable" \
    env "$variable=" bash -c 'source "$1"; remote_dev_prepare_project_git_boundary "$2"' _ "$runtime_lib" "$workspace"
done

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

# Any .git entry is unsafe at the collection root, including dangling symlinks,
# special filesystem entries and malformed gitfiles. Never follow or repair it.
symlink_root="$root/symlink/workspace"
mkdir -p "$symlink_root/project"
ln -s "$root/does-not-exist" "$symlink_root/.git"
assert_fails_with 2 "CRITICAL: project collection root contains .git" remote_dev_assert_project_collection "$symlink_root"

fifo_root="$root/fifo/workspace"
mkdir -p "$fifo_root/project"
mkfifo "$fifo_root/.git"
assert_fails_with 2 "CRITICAL: project collection root contains .git" remote_dev_assert_project_collection "$fifo_root"

malformed_root="$root/malformed/workspace"
mkdir -p "$malformed_root/project"
printf 'not a gitfile\n' > "$malformed_root/.git"
assert_fails_with 2 "CRITICAL: project collection root contains .git" remote_dev_assert_project_collection "$malformed_root"

# A valid linked-worktree gitfile at the collection root is still forbidden: the
# collection is never itself a project even when Git metadata is well formed.
root_gitfile_source="$root/root-gitfile-source"
root_gitfile_workspace="$root/root-gitfile/workspace"
mkdir -p "$root_gitfile_source" "$(dirname "$root_gitfile_workspace")"
git -C "$root_gitfile_source" init -q
printf 'tracked\n' >"$root_gitfile_source/tracked.txt"
git -C "$root_gitfile_source" add tracked.txt
git -C "$root_gitfile_source" -c user.name=remote-dev-test -c user.email=test@example.invalid \
  commit -qm initial
git -C "$root_gitfile_source" worktree add -q --detach "$root_gitfile_workspace" HEAD
[[ -f "$root_gitfile_workspace/.git" ]] || fail "root gitfile fixture did not create .git file"
assert_fails_with 2 "CRITICAL: project collection root contains .git" \
  remote_dev_assert_project_collection "$root_gitfile_workspace"

# A bare repository at the collection root has no .git child, so detect it
# independently through bounded Git plumbing.
bare_root="$root/bare/workspace"
mkdir -p "$(dirname "$bare_root")"
git init --bare -q "$bare_root"
assert_fails_with 2 "bare Git repository" remote_dev_assert_project_collection "$bare_root"
assert_fails_with 2 "bare Git repository" \
  env GIT_OBJECT_DIRECTORY= bash -c \
    'source "$1"; remote_dev_assert_project_collection "$2"' \
    _ "$runtime_lib" "$bare_root"

# Malformed Git metadata at the selected child is not silently treated as a
# newly-created non-repository project.
invalid_child_root="$root/invalid-child/workspace"
mkdir -p "$invalid_child_root/project"
printf 'broken\n' > "$invalid_child_root/project/.git"
remote_dev_prepare_project_git_boundary "$invalid_child_root"
assert_fails_with 2 "invalid Git metadata" remote_dev_assert_project_git_boundary "$invalid_child_root" "$invalid_child_root/project"

# A selected project's .git entry must itself be a safe filesystem object. Git
# follows a .git symlink and can report the selected directory as the worktree
# root even when repository metadata belongs to a sibling, so reject it before
# invoking Git rather than trusting rev-parse alone.
symlink_child_root="$root/symlink-child/workspace"
mkdir -p "$symlink_child_root/project-a" "$symlink_child_root/project-b"
git -C "$symlink_child_root/project-b" init -q
ln -s "$symlink_child_root/project-b/.git" "$symlink_child_root/project-a/.git"
remote_dev_prepare_project_git_boundary "$symlink_child_root"
assert_fails_with 2 ".git must not be a symlink" \
  remote_dev_assert_project_git_boundary "$symlink_child_root" "$symlink_child_root/project-a"

# Special .git entries can make Git block while opening metadata. The preflight
# must reject them by type before any repository probe. Run through timeout so a
# future regression fails deterministically instead of hanging CI.
special_child_root="$root/special-child/workspace"
mkdir -p "$special_child_root/project"
mkfifo "$special_child_root/project/.git"
assert_fails_with 2 ".git must be a regular file or directory" \
  timeout 5 bash -c 'source "$1"; remote_dev_assert_project_git_boundary "$2" "$3"' \
    _ "$runtime_lib" "$special_child_root" "$special_child_root/project"

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
# any agent command can execute, so the canary remains intact. Use an explicit
# command chain here because Bash disables errexit inside an `if` condition.
protected="$root/protected/workspace"
mkdir -p "$protected/project-a" "$protected/project-b"
printf 'canary\n' > "$protected/project-b/DO_NOT_DELETE"
git -C "$protected" init -q
agent_marker="$root/agent-ran"
if remote_dev_prepare_project_git_boundary "$protected" \
  && printf 'ran\n' > "$agent_marker"; then
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

# Doctor must preserve the helper's distinction between an unavailable Git
# binary (status 1) and actual/ambiguous collection contamination (status 2).
doctor_source="${REMOTE_DEV_DOCTOR:-}"
if [[ -z "$doctor_source" ]]; then
  if [[ -f ./scripts/remote-dev-doctor.sh ]]; then
    doctor_source=./scripts/remote-dev-doctor.sh
  elif [[ -f /usr/local/bin/remote-dev-doctor ]]; then
    doctor_source=/usr/local/bin/remote-dev-doctor
  fi
fi
[[ -n "$doctor_source" && -f "$doctor_source" ]] || fail "Doctor source is unavailable: ${doctor_source:-<unset>}"
doctor_runtime="$root/doctor-runtime.sh"
doctor_fixture="$root/remote-dev-doctor"
doctor_workspace="$root/doctor-workspace"
mkdir -p "$doctor_workspace"
cat >"$doctor_runtime" <<'DOCTOR_RUNTIME'
remote_dev_resolve_role() {
  printf 'codex\n'
}
remote_dev_validate_workspace_root() {
  printf '%s\n' "$1"
}
remote_dev_assert_project_collection() {
  return "${REMOTE_DEV_TEST_COLLECTION_STATUS:?}"
}
DOCTOR_RUNTIME
python3 - "$doctor_source" "$doctor_fixture" "$doctor_runtime" <<'PY'
from pathlib import Path
import sys

source, destination, runtime = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
anchor = "runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh"
if anchor not in text:
    raise SystemExit("missing Doctor runtime-lib anchor")
text = text.replace(anchor, f"runtime_lib={runtime}", 1)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$doctor_fixture"

doctor_unavailable_output="$root/doctor-git-unavailable"
env WORKSPACE="$doctor_workspace" REMOTE_DEV_TEST_COLLECTION_STATUS=1 \
  "$doctor_fixture" >"$doctor_unavailable_output" 2>&1 || true
grep -Fq 'Workspace collection: BLOCKED (Git is unavailable; collection safety cannot be verified)' \
  "$doctor_unavailable_output" \
  || fail "Doctor did not report unavailable Git distinctly"
if grep -Fq 'Workspace collection: CRITICAL — collection root is Git-contaminated or ambiguous' \
  "$doctor_unavailable_output"; then
  fail "Doctor mislabeled unavailable Git as collection contamination"
fi
if grep -Fq 'Recovery: stop affected agent sessions' "$doctor_unavailable_output"; then
  fail "Doctor printed Git-contamination recovery for unavailable Git"
fi

doctor_contaminated_output="$root/doctor-git-contaminated"
env WORKSPACE="$doctor_workspace" REMOTE_DEV_TEST_COLLECTION_STATUS=2 \
  "$doctor_fixture" >"$doctor_contaminated_output" 2>&1 || true
grep -Fq 'Workspace collection: CRITICAL — collection root is Git-contaminated or ambiguous' \
  "$doctor_contaminated_output" \
  || fail "Doctor did not preserve the contamination diagnostic for status 2"
grep -Fq 'Recovery: stop affected agent sessions' "$doctor_contaminated_output" \
  || fail "Doctor omitted contamination recovery guidance for status 2"

echo "Project collection Git-boundary regressions: OK"
