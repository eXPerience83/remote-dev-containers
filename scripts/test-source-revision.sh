#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
helper="$ROOT/scripts/detect-source-revision.sh"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

assert_equal() {
  local expected="$1"
  local actual="$2"
  local label="$3"

  if [[ "$actual" != "$expected" ]]; then
    echo "ERROR: $label: expected $expected, got $actual" >&2
    exit 1
  fi
}

plain="$workdir/plain"
mkdir -p "$plain"
assert_equal local-untracked "$(bash "$helper" "$plain")" "non-Git source root"

outer="$workdir/outer"
mkdir -p "$outer/copied-source"
git -C "$outer" init -q
git -C "$outer" -c user.name=CI -c user.email=ci@example.invalid -c commit.gpgsign=false commit --allow-empty -qm initial
assert_equal local-untracked "$(bash "$helper" "$outer/copied-source")" "source root nested inside another Git worktree"

own="$workdir/own"
mkdir -p "$own"
git -C "$own" init -q
printf 'tracked\n' > "$own/tracked.txt"
git -C "$own" add tracked.txt
git -C "$own" -c user.name=CI -c user.email=ci@example.invalid -c commit.gpgsign=false commit -qm initial
head_revision="$(git -C "$own" rev-parse HEAD)"
assert_equal "$head_revision" "$(bash "$helper" "$own")" "clean source worktree"

printf 'modified\n' >> "$own/tracked.txt"
assert_equal "${head_revision}-dirty" "$(bash "$helper" "$own")" "dirty source worktree"

echo "Source revision detection: OK"
