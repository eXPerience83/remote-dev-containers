#!/usr/bin/env bash
set -euo pipefail

if (( $# != 1 )); then
  echo "Usage: detect-source-revision.sh <source-root>" >&2
  exit 2
fi

source_root="$1"
if ! source_root_physical="$(cd "$source_root" 2>/dev/null && pwd -P)"; then
  echo "ERROR: source root is not accessible: $source_root" >&2
  exit 1
fi

git_root="$(git -C "$source_root_physical" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$git_root" ]]; then
  printf 'local-untracked\n'
  exit 0
fi

if ! git_root_physical="$(cd "$git_root" 2>/dev/null && pwd -P)"; then
  printf 'local-untracked\n'
  exit 0
fi

if [[ "$git_root_physical" != "$source_root_physical" ]]; then
  printf 'local-untracked\n'
  exit 0
fi

revision="$(git -C "$source_root_physical" rev-parse --verify HEAD 2>/dev/null || true)"
if [[ -z "$revision" ]]; then
  printf 'local-untracked\n'
  exit 0
fi

worktree_status=""
if ! worktree_status="$(git -C "$source_root_physical" status --porcelain --untracked-files=normal 2>/dev/null)"; then
  echo "ERROR: unable to inspect Git worktree status for $source_root_physical" >&2
  exit 1
fi

if [[ -n "$worktree_status" ]]; then
  revision="${revision}-dirty"
fi

printf '%s\n' "$revision"
