# AGENTS.md

These instructions apply to the entire repository unless a more specific nested `AGENTS.md` is added later.

## Sources of truth

Before changing runtime architecture or support claims, read the current code and owning GitHub issues rather than relying on stale prose.

Current high-level ownership:

- #31 is the experimental-release/support tracker and should list only genuinely remaining release blockers.
- #24/#25 are completed single-image, single-stack, isolated-service/role-neutral runtime foundations.
- #36 records the completed TrueNAS outer-isolation and no-system-Bubblewrap decision.
- #42 records completed outer-container hardening and cross-service canaries.
- #53 is the standing third-party/license/vendor-policy review log. Automation provides evidence, never legal approval.
- #69 is the completed browser-authentication decision: one configuration-backed `WEB_PASSWORD` runtime contract; `WEB_PASSWORD_FILE` is retired.
- #70/#167 define the canonical persistent-data layout and deterministic TrueNAS bootstrap/preflight.
- #186 defines the completed TrueNAS Generic/POSIX private-state ACL audit/migration contract.
- #92 owns broad English/Spanish documentation and implementation-status synchronization.
- #96 owns the completed Antigravity reviewed/review-pending/damaged runtime-admission model.
- #83 owns the shipped Antigravity scheduled static discovery plus explicit executable-review automation; it must not gate or revoke an intact admitted runtime merely because review state changes.
- #103 owns optional explicit Codex runtime updates while preserving the immutable bundled fallback.
- #120 owns the permanent `dev -> edge -> stable = latest` channel contract.
- #168 owns dated edge build identity and grouped-upstream changelog provenance.
- #189 owns the completed Renovate Ubuntu runtime-image changelog provenance boundary.

If issue prose and repository code disagree, resolve the discrepancy explicitly before broadening scope.

## Mandatory PR discipline

- Work on a branch and open a pull request. Never push implementation changes directly to `main`.
- Keep one focused objective per PR.
- Do not add a new subsystem or broaden a security/distribution boundary without an owning issue and explicit review.
- Prefer explicit mappings and bounded validators for known repository inputs; do not build speculative universal parsers.
- Do not introduce speculative support for optional agents. Missing optional runtimes remain unavailable and must never download silently during normal startup.
- Do not change unrelated dependency pins, generated legal evidence, image names, Compose layouts or persistent mounts unless the PR owns those changes.
- Preserve documented compatibility aliases until their reviewed removal point.

A PR is ready to merge only when its **exact final head** has the required repository CI green, valid review findings are fixed, review conversations are resolved and the branch remains mergeable/up to date according to the repository's current merge policy. Use squash merge.

## Security invariants

Never weaken these constraints merely to make a feature easier:

- no privileged containers;
- no Docker or Podman socket;
- no `SYS_ADMIN`;
- no host-root mount;
- no broad `/root`, `/home`, `/opt`, `/usr/local`, `/mnt` or parent data-root persistence;
- no shared writable agent credentials, GitHub CLI state, Git configuration, SSH state, histories or workspaces between role services;
- no launcher access to agent credentials/workspaces/passwords;
- no `eval`, sourced editable state or user-controlled shell fragments for role/mode/installer/routing/command dispatch;
- no secret values in diagnostics, logs, tests, issues or PR descriptions.

The supported TrueNAS isolation boundary is the outer role container. Approval prompts are not a sandbox. Do not claim an inner sandbox is active unless a positive runtime test proves that exact mechanism is operational.

Host TrueNAS/Docker root/admin is trusted and can inspect deployment configuration. Remote Dev does not claim administrator secrecy for `WEB_PASSWORD` or other configuration-backed values.

## Runtime implementation rules

- Use fixed validated enums for roles/start modes.
- Build process invocations with argument arrays and preserve literal arguments without shell re-evaluation.
- Reject unknown roles/modes deterministically with a clear non-zero result.
- Keep product-specific variables/state inside the owning role.
- Keep one canonical implementation; compatibility commands are thin wrappers, not copied logic.
- Preserve command exit status and persistent-state hardening after supported interactive sessions.
- Preserve ttyd authentication for agent terminals, origin checking, tmux reconnect behavior, image identity checks and supported Codex/Antigravity project-scoped launch behavior.

### Launcher rules

- `REMOTE_DEV_ROLE=launcher` is navigation only.
- It must not execute an agent, proxy/relay terminal HTTP/WebSocket traffic or manage containers without a separately reviewed threat-model change.
- It may link only to fixed validated services declared by the stack.
- Keep the reviewed private-network unauthenticated default, optional launcher authentication, origin checks, CSP, method restrictions and secret-free health behavior covered by tests.
- Never embed credentials in launcher URLs/HTML/JavaScript/logs/diagnostics.
- Optional launcher authentication may add its own configuration-backed password but no agent password/state/mount/socket.
- Enabled services must use the intended common image reference while retaining disjoint mutable state.

### Browser-authentication rules

- Protected endpoints use `WEB_PASSWORD` only.
- Codex and Antigravity values are independent.
- Optional launcher authentication uses a distinct launcher value.
- Do not reintroduce `WEB_PASSWORD_FILE`, `/run/secrets/web_password`, browser-password Compose secrets or a persistent password-file tree without a new explicit architecture decision.
- Never log or derive reusable metadata from password contents.

### Antigravity runtime-admission rules

- Antigravity remains unbundled and optional/experimental.
- Use only the reviewed official Google installer/runtime path; no alternative service client/protocol implementation.
- Do not reuse/export Google/Antigravity OAuth for Codex, Claude Code, OpenCode, OpenClaw or another third-party agent/service.
- Normal startup/status/launch must not contact the installer/update endpoint.
- `AGY_CLI_DISABLE_AUTO_UPDATE=true` remains mandatory for supported sessions.
- Committed evidence marks reviewed versions but is not an execution allowlist or revocation mechanism.
- A compatible official-source runtime may remain runnable with `review pending` when it was admitted through the hardened flow and still matches its private manifest.
- Explicit install/update must validate the fixed network/origin, bounded installer/runtime contract, architecture/version/help identity and preserve the previous working pair on failure/interruption.
- Informational status stays lightweight/offline; explicit verify/Doctor and the mandatory pre-launch gate own full integrity checks according to the shipped #153/#96 contract.
- Do not describe review-pending state as Google signing, Remote Dev certification, image-SBOM inclusion or Apache-2.0 coverage.
- Keep #96 runtime admission separate from #83 review automation and #103 Codex runtime updates.

### Antigravity review-automation rules

- Scheduled discovery is read-only and must execute **zero vendor code**.
- It may download only bounded reviewed-origin installer/manifest/archive bytes as data, validate schema/origin/integrity and compute exact installer/payload identities.
- Changed identities cross the scheduled boundary as metadata only.
- Executable inspection remains an explicit trusted workflow and must verify the exact pending pair before any vendor execution.
- Raw proprietary installer/archive/runtime bytes and raw vendor output must not become repository artifacts/evidence unless a separately reviewed policy explicitly allows it.
- Automation never makes legal/vendor-support decisions and must not auto-merge review changes.

See `docs/antigravity-runtime-admission.md` / `.es.md` and `docs/dependency-automation.md`.

### TrueNAS data/ACL rules

- `compose/truenas.yml` remains the canonical supported TrueNAS YAML path.
- The operator creates the root dataset explicitly; bootstrap never creates a missing root/parent/dataset.
- `scripts/lib/data_layout.py` is the shared path contract consumed by initializer/preflight.
- The reference Host Path private-state security model is Generic/POSIX; use `scripts/truenas-acl-audit.py` from the same source revision for authoritative host ACL checks.
- `remote-dev-doctor` may report container-visible mount modes but must not pretend to infer host TrueNAS ACL type.
- Do not rely on comments or `${...}` interpolation surviving a TrueNAS Custom App edit/save round-trip.

## Validation expectations

Run the narrowest relevant tests during development and the repository's complete required CI before merge.

Runtime/deployment changes should preserve or extend coverage for, where affected:

- role/start-mode validation and wrapper equivalence;
- launcher authentication/origin/CSP/fixed navigation plus absence of agent mounts/socket;
- intended common image identity across enabled roles;
- role-private mount sources and canonical host layout;
- bootstrap/preflight/ACL-audit behavior;
- independent `WEB_PASSWORD` agent authentication and absence of the retired file-backed path;
- role-aware health checks;
- Codex project-scoped Start/Resume, approval policy and bundled/optional runtime fallback;
- Antigravity project-scoped Start/Resume, admission/integrity/review states and no-installer-network launch;
- Context7 managed credential/device-login boundaries when changed;
- embedded image version/channel/source revision;
- bundled notices, SBOM generation, vulnerability scanning and the no-fixable-critical gate.

Use synthetic credentials/state in automated tests. Never require a real vendor account in CI.

## Documentation and issue hygiene

- Update the owning issue with the completed slice and genuinely remaining work.
- Update #31 when a tracked release dependency changes state.
- Keep English/Spanish user documentation equivalent in meaning for user-visible behavior.
- Record compatibility aliases, defaults, migration effects, authentication boundaries and removal points explicitly.
- Do not mark optional software as bundled, vendor-supported, certified or covered by the project Apache-2.0 license unless that exact claim has completed the corresponding review.
- Keep `CHANGELOG.md` machine-owned sections bounded; human documentation changes must preserve the grouped-upstream and Renovate markers/state anchors exactly.
