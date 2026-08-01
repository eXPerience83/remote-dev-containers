# AGENTS.md

These instructions apply to the entire repository unless a more specific nested `AGENTS.md` is added later.

## Sources of truth

Before changing runtime architecture or support claims, read the current GitHub issues rather than relying on stale prose in a prompt:

- #31 is the roadmap and dependency tracker.
- #24 is the completed single-image, single-stack, isolated-service architecture contract.
- #25 is the role-neutral runtime and launcher epic.
- #26 and #53 define the third-party notice and recurring legal-review process.
- #36 records the completed TrueNAS outer-isolation and no-Bubblewrap decision.
- #42 covers later outer-container hardening and cross-service canaries.
- #46 covers configurable Codex approval modes and is intentionally separate from the first role-neutral runtime slice.

If an issue and repository code disagree, report the discrepancy before expanding scope.

## Mandatory PR discipline

- Work on a branch and open a pull request. Never push implementation changes directly to `main`.
- Keep one focused objective per PR. Do not combine runtime migration, launcher routing, legal review, vendor installation, persistence migration, and real-login evidence.
- Stop and ask before adding a new subsystem or changing the agreed PR boundary.
- Do not build universal Dockerfile, shell, package-manager, license, or static-analysis parsers. Prefer explicit mappings and bounded validators for known repository inputs.
- Do not introduce speculative support for Antigravity or Claude Code. Missing optional roles must remain unavailable and must never download silently.
- Do not change unrelated dependency pins, generated legal evidence, image names, Compose layouts, or persistent mounts unless the issue and PR explicitly include them.
- Preserve compatibility wrappers until their removal point is documented and reviewed.

A PR is ready to merge only when its exact final head has the required `build` check green, review findings have been evaluated, all valid findings are fixed, all review conversations are resolved, and the branch is up to date with `main`. Use squash merge.

## Security invariants

Never weaken these constraints to make a feature easier:

- no privileged containers;
- no Docker or Podman socket;
- no `SYS_ADMIN`;
- no host-root mount;
- no broad `/root`, `/home`, `/opt`, `/usr/local`, or parent data-root persistence;
- no shared writable agent credentials, GitHub CLI state, Git configuration, SSH state, caches, histories, or workspaces between role services;
- no launcher access to agent credentials or workspaces;
- no `eval`, sourced editable state, or user-controlled shell fragments for role, mode, installer, or command dispatch;
- no secret values in diagnostics, logs, tests, issues, or PR descriptions.

The supported TrueNAS isolation boundary is the outer container. Do not claim that Bubblewrap, Landlock, approvals, or another inner mechanism provides isolation unless a positive runtime test proves it.

## Runtime implementation rules

- Use fixed, validated enums for roles and start modes.
- Build command invocations with Bash arrays and preserve arguments without re-evaluating them.
- Reject unknown roles and modes with a deterministic non-zero exit status and a clear message.
- Keep product-specific variables such as `CODEX_HOME` inside the Codex role.
- Keep one canonical implementation. Compatibility commands must be thin wrappers around the canonical command, not copied implementations.
- Preserve command exit status and run persistent-state hardening after supported interactive sessions.
- Preserve ttyd authentication, origin checking, tmux reconnect behavior, image identity checks, and existing Codex login/start/resume behavior.

## Boundaries for issue #25

Implement #25 as separate reviewed slices:

1. role-neutral commands, validated role/start-mode resolution, and Codex compatibility wrappers;
2. configurable Codex approval modes under #46;
3. canonical image and variable naming with time-bounded aliases;
4. launcher/gateway and Codex services using the same image digest;
5. Compose and persistent-state migration;
6. outer hardening and cross-service canaries under #42.

The first slice must not add the launcher proxy, new Compose services, image renaming, data-root migration, Antigravity, Context7, or new persistent mounts.

## Validation expectations

Run the narrowest relevant tests during development and the repository's complete required CI before merge. Runtime changes must preserve or extend coverage for:

- role and start-mode validation;
- compatibility-wrapper equivalence;
- Codex version and fixed launch policy;
- start, resume, device-code login paths, and direct-session exit status;
- post-session credential hardening;
- ttyd authentication and origin checking;
- persistent and concurrent tmux attachment;
- embedded image version and source revision;
- bundled notices, SBOM generation, Trivy, and the no-fixable-critical gate.

Use synthetic credentials and state in tests. Never require a real vendor account in CI.

## Documentation and issue hygiene

- Update the owning issue with the exact completed slice and remaining work.
- Update #31 when a tracked phase or dependency changes state.
- Keep English and Spanish user documentation aligned when user-visible behavior changes.
- Record compatibility aliases, defaults, migration effects, and removal points explicitly.
- Do not mark optional software as shipped, installed, supported, or covered by the project Apache-2.0 license before the relevant legal and real-environment gates are complete.
