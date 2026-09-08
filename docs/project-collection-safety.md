# Project collection safety and recovery

This document defines the fail-closed project boundary owned by [#213](https://github.com/eXPerience83/remote-dev-containers/issues/213).

## The invariant

For each agent role, `/workspace` is a **project collection root**, never an implicit project repository. Managed Start/Resume/Continue actions operate from exactly one validated direct child:

```text
/workspace/                 collection root — must not be a Git repository
├── project-a/              selected project candidate
├── project-b/              sibling project
└── .remote-dev-tmp/        Remote Dev development scratch, not a project
```

A project can be an ordinary Git worktree, a linked Git worktree whose `.git` entry is a gitfile, or an empty/non-Git directory. If Git recognizes a repository for the selected project, its effective worktree top-level must be exactly `/workspace/<selected-project>`.

The collection itself is not allowed to contain a `.git` entry of any kind and must not be a bare Git repository. Remote Dev does not try to decide whether collection-root Git metadata was intentional, stale or accidental: managed project actions fail closed instead.

Doctor also audits the top-level collection layout. The expected entries are valid direct-child project directories plus the optional managed `.remote-dev-tmp` directory. Other files, symlinks, hidden directories or special entries are reported for manual inspection; Doctor never deletes or rewrites them.

## Git ancestor discovery

Managed Codex and experimental Antigravity project launches set:

```text
GIT_CEILING_DIRECTORIES=/workspace
```

using the validated collection path. This prevents an empty project such as `/workspace/new-project` from silently inheriting a Git repository above `/workspace`.

Remote Dev also refuses inherited `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR` and `GIT_OBJECT_DIRECTORY` assignments for managed agent launches, including variables that are present with an empty value, because those variables can route or alter Git outside the selected-project contract.

For Codex, setting the variable in the parent process is not sufficient: Codex can apply its own shell-environment policy before model-reachable commands run. The pre-launch boundary probe therefore reads Codex's **effective** configuration through the bundled/runtime app-server and fails closed unless the managed `GIT_CEILING_DIRECTORIES` value survives that policy. The probe is read-only and does not replace the user's other shell-environment restrictions.

## What happens when the collection is blocked

If `/workspace` contains `.git`, is recognized as a bare Git repository, or otherwise fails the collection safety check:

- Codex Start and Resume are blocked before Codex is invoked;
- experimental Antigravity Start and Continue are blocked before the vendor CLI is invoked;
- project discovery, Select, Create and Delete are blocked;
- an existing menu selection is discarded rather than reused as stale state;
- **Run diagnostics** remains available;
- **Open a login shell** remains available for manual inspection/cleanup;
- Remote Dev does not delete `.git`, run `git reset`, run `git clean`, move projects, or rewrite repository metadata automatically.

Doctor reports the collection as `CRITICAL`/`BLOCKED` without printing remotes, repository contents, credentials or other private data.

## Manual cleanup

Remote Dev deliberately does not automate cleanup. For a known disposable/experimental contamination such as the confirmed Antigravity incident, the operator may remove the exact `/workspace/.git` entry manually after checking that this is the unintended collection-root metadata. No other collection entry should be removed as part of that cleanup.

For data that matters, inspect or snapshot it before destructive repair. Never begin with collection-root `git clean -fd`, `git reset --hard`, forced checkout, or similar Git cleanup: if `/workspace` is accidentally the repository root, sibling project directories can be interpreted as untracked repository content and deleted.

After manual cleanup, run Doctor again. The collection must report that its Git root is clean; unexpected top-level entries should also be inspected until the layout contains only valid project directories plus optional `.remote-dev-tmp`.

## Deleted-current-directory recovery

An agent can rename or delete the project directory it was launched from. Post-session hardening therefore first recovers to a known-safe directory using shell builtins, then invokes external credential/state hardening helpers. The original agent exit status is preserved unless safe-cwd recovery or mandatory hardening itself fails.

This prevents a deleted cwd from turning the cleanup path into a secondary `getcwd` failure.

## Agent-specific behavior

The collection/Git boundary is a Remote Dev runtime contract shared by Codex and experimental Antigravity. It does not introduce a new nested sandbox and does not claim filesystem isolation from sibling projects that remain mounted in the same role container.

Codex keeps the established #36/#42 outer-container model and its existing autonomous/guarded policy. Antigravity keeps its existing experimental vendor launch behavior; #213 does not force or configure a vendor sandbox. Future agent integrations should reuse the common collection/project helpers rather than reimplementing Git-boundary logic independently.

## Validation expectations

The repository regression suite covers at least:

- clean collection + empty child;
- repository rooted exactly at a child;
- linked worktree rooted exactly at a child;
- ancestor Git repository above the collection not being inherited;
- collection-root `.git` directory, gitfile, symlink/special entry, malformed entry and bare repository;
- selected-project invalid Git metadata;
- the real root-level `git clean -fd` sibling-deletion mechanism in a disposable control fixture;
- sibling canaries remaining intact when the managed preflight blocks;
- deleted-cwd recovery before post-session hardening;
- Codex effective shell-environment policy preserving the ceiling;
- Antigravity using the same common collection entry/Git ceiling before vendor launch;
- Doctor reporting unexpected collection-root entries without modifying them.

The final TrueNAS evidence must use disposable A/B projects and canaries. Never reproduce the destructive control case against real user project data.
