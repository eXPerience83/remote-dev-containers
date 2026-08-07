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
- #92 owns broad English/Spanish documentation and implementation-status synchronization.
- #96 owns compatible official-source Antigravity runtime admission and its reviewed/review-pending/damaged states.
- #83 owns scheduled Antigravity detection and human-review PR automation after #96; it must not gate runtime availability.
- #103 owns optional explicit Codex runtime updates while preserving the immutable bundled fallback.

If an issue and repository code disagree, report the discrepancy before expanding scope.

## Mandatory PR discipline

- Work on a branch and open a pull request. Never push implementation changes directly to `main`.
- Keep one focused objective per PR. Do not combine runtime migration, launcher routing, legal review, vendor installation, persistence migration, and real-login evidence.
- Stop and ask before adding a new subsystem or changing the agreed PR boundary.
- Do not build universal Dockerfile, shell, package-manager, license, or static-analysis parsers. Prefer explicit mappings and bounded validators for known repository inputs.
- Do not introduce speculative support for optional agents. Missing optional roles must remain unavailable and must never download silently.
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

### Launcher rules

- `REMOTE_DEV_ROLE=launcher` is navigation only. It must not execute an agent or relay/proxy agent terminal HTTP or WebSocket traffic unless a later PR has an explicit threat-model review.
- The launcher may link only to fixed, validated services declared by the stack.
- Keep the unauthenticated private-network default, optional launcher authentication, origin checks, CSP, method restrictions and secret-free health behavior covered by tests.
- Never embed credentials in launcher URLs, HTML, JavaScript, logs or diagnostics.
- By default the launcher service receives only its web/routing configuration and no password secret. A deployment may explicitly enable optional launcher authentication, but the launcher must never receive agent workspaces, agent state, GitHub/Git/SSH mounts, agent secrets or the Docker socket.
- Launcher and agent services must use the same final image reference/digest while retaining separate container roles and state boundaries.

### Antigravity runtime-admission rules

- Antigravity remains unbundled and must be downloaded only after an explicit user action from the fixed official Google installer endpoint.
- Normal startup, status and launch paths must never contact the installer endpoint or update the executable.
- `AGY_CLI_DISABLE_AUTO_UPDATE=true` is mandatory for candidate checks and normal sessions.
- Committed inspection evidence marks the exact reviewed version; it is not an execution allowlist. Absence from evidence is not revocation.
- A compatible official-source payload may run with `review pending` status when it was admitted by the hardened flow and still matches its private manifest.
- Installer and candidate execution must use a credential-free isolated home, bounded output/time and a private staging subtree. When the production container runs as root, drop to a fixed unprivileged identity before executing changed vendor bytes.
- Validate fixed/final origin, regular-file identity, ownership, size bounds, Bash contract, Linux AMD64 format, semantic version and bounded help before publication.
- Publish executable and manifest only after all checks pass. Failed or interrupted updates must preserve the previous pair.
- Launch must verify the local executable against its restrictive private manifest without installer/update network access. Missing, symlinked, malformed or identity-mismatched state is `damaged or locally modified` and must be blocked.
- Do not describe review-pending status as cryptographic vendor signing, Remote Dev certification, image-SBOM inclusion or Apache-2.0 coverage.
- A private manifest detects independent modification and accidental corruption; it is not protection from a process already controlling the service user or container root and able to replace both files coherently.
- Keep #96 runtime admission separate from #83 scheduled review automation and #103 Codex runtime updates with bundled fallback.

See `docs/antigravity-runtime-admission.md` and `docs/antigravity-runtime-admission.es.md` for the user-facing contract.

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

Antigravity runtime-admission changes must also test reviewed, review-pending and damaged states; no-installer-network launch; installer-origin/contract rejection; manifest and executable tampering; symlink/permission rejection; evidence changes across image replacement; and preservation of the previous installation after failed or interrupted updates.

Use synthetic credentials and state in tests. Never require a real vendor account in CI.

## Documentation and issue hygiene

- Update the owning issue with the exact completed slice and remaining work.
- Update #31 when a tracked phase or dependency changes state.
- Keep English and Spanish user documentation aligned when user-visible behavior changes.
- Record compatibility aliases, defaults, migration effects, authentication boundaries and removal points explicitly.
- Do not mark optional software as bundled, fully supported, certified, or covered by the project Apache-2.0 license before the relevant legal and real-environment gates are complete.
