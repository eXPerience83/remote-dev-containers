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

## Git ancestor discovery

Managed Codex and experimental Antigravity project launches set:

```text
GIT_CEILING_DIRECTORIES=/workspace
```

using the validated collection path. This prevents an empty project such as `/workspace/new-project` from silently inheriting a Git repository above `/workspace`.

Remote Dev also refuses inherited `GIT_DIR`, `GIT_WORK_TREE` and `GIT_COMMON_DIR` values for managed agent launches because those variables can route Git outside the selected-project contract.

For Codex, setting the variable in the parent process is not sufficient: Codex can apply its own shell-environment policy before model-reachable commands run. The pre-launch boundary probe therefore reads Codex's **effective** configuration through the bundled/runtime app-server and fails closed unless the managed `GIT_CEILING_DIRECTORIES` value survives that policy. The probe is read-only and does not replace the user's other shell-environment restrictions.

## What happens when the collection is blocked

If `/workspace` contains `.git`, is recognized as a bare Git repository, or otherwise fails the collection safety check:

- Codex Start and Resume are blocked before Codex is invoked;
- experimental Antigravity Start and Continue are blocked before the vendor CLI is invoked;
- project discovery, Select, Create and Delete are blocked;
- an existing menu selection is discarded rather than reused as stale state;
- **Run diagnostics** remains available;
- **Open a login shell** remains available for manual recovery;
- Remote Dev does not delete `.git`, run `git reset`, run `git clean`, move projects, or rewrite repository metadata automatically.

Doctor reports the collection as `CRITICAL`/`BLOCKED` without printing remotes, repository contents, credentials or other private data.

## Recovery procedure

Treat a collection-root Git repository as a data-safety incident until you understand its origin.

1. Stop managed agent work in the affected role. Do not start another agent session against that collection.
2. Preserve the current data first. On TrueNAS, take an appropriate dataset snapshot or equivalent backup before destructive repair.
3. Use **Run diagnostics** to confirm that the collection boundary is what is blocking launch.
4. Use **Open a login shell** only for inspection. Determine whether `/workspace/.git` is a directory, gitfile, symlink/special entry, or whether `/workspace` is a bare repository.
5. Identify which project, if any, the Git metadata actually belongs to before moving or removing anything.
6. Repair the layout manually so `/workspace` is only a collection and every repository is rooted at its intended `/workspace/<project>` child.
7. Run diagnostics again. Managed launches should remain blocked until the collection and selected-project checks both pass.

Do **not** use a collection-root `git clean -fd`, `git reset --hard`, forced checkout, or similar cleanup as a first recovery step. If `/workspace` is accidentally the repository root, sibling project directories can be interpreted as untracked repository content and deleted.

## Deleted-current-directory recovery

An agent can rename or delete the project directory it was launched from. Post-session hardening therefore first recovers to a known-safe directory using shell builtins, then invokes external credential/state hardening helpers. The original agent exit status is preserved unless safe-cwd recovery or mandatory hardening itself fails.

This prevents a deleted cwd from turning the cleanup path into a secondary `getcwd` failure.

## Experimental Antigravity confinement

Antigravity remains experimental and does not become a supported TrueNAS integration merely because the common collection checks pass.

For the managed experimental path, Remote Dev currently:

- forces the vendor's documented session-scoped `--sandbox` flag;
- rejects caller attempts to disable/replace the sandbox or use the dangerous permission-skip flag;
- validates `~/.gemini/antigravity-cli/settings.json` **read-only** and byte-preservingly;
- requires `allowNonWorkspaceAccess` to be disabled;
- requires `permissions.deny` to contain `unsandboxed(*)`;
- rejects persistent `unsandboxed(...)` allow grants;
- rejects `read_file(...)` / `write_file(...)` allow grants that lexically escape the selected project or traverse an existing symlink from the project to an outside path.

Google's current CLI documentation states that `--sandbox` forces sandboxing for the session, that filesystem mounts are derived from `read_file`/`write_file` permissions, and that permission precedence is `Deny > Ask > Allow`. It also documents `unsandboxed(...)` as the sandbox escape resource. See the upstream [Sandbox](https://antigravity.google/docs/cli/sandbox/) and [Permissions](https://antigravity.google/docs/permissions/) documentation.

Those documented semantics are necessary but not sufficient evidence for this project. The exact admitted Antigravity runtime still has to pass the disposable TrueNAS acceptance matrix from #213. If the exact runtime cannot demonstrate sibling and private-state confinement under the supported outer-container topology, managed Antigravity remains blocked; the Codex/common fix does not wait for that proof.

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
- experimental Antigravity persistent-settings validation remaining read-only.

The final TrueNAS evidence must use disposable A/B projects and canaries. Never reproduce the destructive control case against real user project data.
