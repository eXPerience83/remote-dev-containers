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
- #46 covers configurable Codex approval modes.
- #83 defines the official-source optional-agent update and review model.

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
- no `eval`, sourced editable state, or user-controlled shell fragments for role, mode, installer, routing, or command dispatch;
- no secret values in diagnostics, logs, tests, issues, or PR descriptions.

The supported TrueNAS isolation boundary is the outer container. Approval prompts are never a sandbox or an isolation boundary. Do not claim that Bubblewrap, Landlock, or another inner sandbox is active unless a positive runtime test proves that exact mechanism is operational.

## Runtime implementation rules

- Use fixed, validated enums for roles and start modes.
- Build command invocations with Bash arrays and preserve arguments without re-evaluating them.
- Reject unknown roles and modes with a deterministic non-zero exit status and a clear message.
- Keep product-specific variables such as `CODEX_HOME` inside the Codex role.
- Keep one canonical implementation. Compatibility commands must be thin wrappers around the canonical command, not copied implementations.
- Preserve command exit status and run persistent-state hardening after supported interactive sessions.
- Preserve mandatory ttyd authentication for agent terminals, origin checking for all web endpoints, tmux reconnect behavior, image identity checks, and existing Codex login/start/resume behavior.

### Official-source agent installation and updates

The Docker image must not be the sole availability gate for software that Remote Dev is not permitted to redistribute.

- Installation and update are always explicit user actions. Normal startup, health checks, diagnostics and agent launch must never download or update software.
- Antigravity may be downloaded only from the fixed official Google HTTPS installer endpoint. Never add a mirror, fallback host, `curl | sh`, editable URL, or caller-provided installer command.
- Save network responses to a private bounded staging file, verify the final origin and minimum live contract, and run the installer with a credential-free isolated home.
- Keep `AGY_CLI_DISABLE_AUTO_UPDATE=true` during validation and every normal Antigravity launch.
- Validate the staged executable before publication, write a private local integrity manifest, and publish only through the canonical manager.
- A locally intact installation created by the hardened official-source flow may run even when its version/hash is newer than committed Remote Dev review evidence. Report it as review pending rather than unverified.
- Committed inspection evidence records the latest human-reviewed snapshot; it informs status and compatibility review but does not invalidate an intact official-source installation merely because the image is older.
- Local executable/manifest mismatch, missing integrity data, malformed manifests, unsafe paths and incompatible installer contracts must still fail closed.
- Updating an image must not force an agent update. Updating an agent must preserve the current working copy until the candidate has passed validation, and retain one local rollback copy where implemented.
- Do not claim that TLS origin validation alone is equivalent to Remote Dev's manual payload review. Distinguish `official, reviewed`, `official, review pending`, and damaged/locally modified states.
- A revocation must identify a specific unsafe version or hash, be explicit in repository data, and have dedicated tests. Absence from the review catalogue is not revocation.

Codex remains bundled in the image as the guaranteed fallback. Any future optional Codex runtime updater must use an official OpenAI source, store the candidate outside immutable image paths, verify it independently, and automatically fall back to the bundled executable when the optional copy is absent or invalid. Implement that in a dedicated focused issue/PR rather than silently replacing the bundled binary.

### Launcher rules

- `REMOTE_DEV_ROLE=launcher` is navigation only. It must not execute an agent or relay/proxy agent terminal HTTP or WebSocket traffic unless a later PR has an explicit threat-model review.
- The launcher may link only to fixed, validated services declared by the stack.
- Keep the unauthenticated private-network default, optional launcher authentication, origin checks, CSP, method restrictions and secret-free health behavior covered by tests.
- Never embed credentials in launcher URLs, HTML, JavaScript, logs or diagnostics.
- By default the launcher service receives only its web/routing configuration and no password secret. A deployment may explicitly enable optional launcher authentication, but the launcher must never receive agent workspaces, agent state, GitHub/Git/SSH mounts, agent secrets or the Docker socket.
- Launcher and agent services must use the same final image reference/digest while retaining separate container roles and state boundaries.

## Boundaries for issue #25

Implement #25 as separate reviewed slices:

1. role-neutral commands, validated role/start-mode resolution, and Codex compatibility wrappers;
2. configurable Codex approval modes under #46;
3. canonical image and variable naming with time-bounded aliases;
4. launcher and Codex services using the same image digest;
5. Compose and persistent-state migration;
6. outer hardening and cross-service canaries under #42.

The launcher slice uses the accepted navigation/redirect design. Do not silently turn it into a reverse proxy, container-management plane, persistent-state migration or optional-agent implementation.

## Validation expectations

Run the narrowest relevant tests during development and the repository's complete required CI before merge. Runtime changes must preserve or extend coverage for:

- role and start-mode validation;
- compatibility-wrapper equivalence;
- launcher unauthenticated-default behavior, optional authentication, origin policy, CSP and fixed navigation;
- launcher absence of agent mounts and Docker socket;
- launcher and Codex same-image reference/ID;
- role-aware health checks;
- Codex version and fixed launch policy;
- start, resume, device-code login paths, and direct-session exit status;
- post-session credential hardening;
- mandatory ttyd authentication for agent terminals and origin checking;
- persistent and concurrent tmux attachment;
- embedded image version and source revision;
- bundled notices, SBOM generation, Trivy, and the no-fixable-critical gate.

Official-source optional-agent changes must additionally test cancellation before download, exact-origin enforcement, response bounds, incompatible installer-contract rejection, isolated staging, candidate validation, local-manifest integrity, review-pending launch, failed-update preservation, rollback, old-manifest compatibility and absence of downloads during normal launch/status.

Use synthetic credentials and state in tests. Never require a real vendor account in CI.

## Documentation and issue hygiene

- Update the owning issue with the exact completed slice and remaining work.
- Update #31 when a tracked phase or dependency changes state.
- Keep English and Spanish user documentation aligned when user-visible behavior changes.
- Record compatibility aliases, defaults, migration effects, authentication boundaries and removal points explicitly.
- Do not mark optional software as bundled, redistributed, stable, or covered by the project Apache-2.0 license before the relevant legal and real-environment gates are complete.
- Review status is not an availability status: an official-source installation may be usable while Remote Dev's human review is pending.
