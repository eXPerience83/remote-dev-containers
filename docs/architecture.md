# Remote Dev architecture

## Status

The implemented architecture is one user-installed Remote Dev stack, one canonical image reference and one isolated service per enabled coding agent.

```text
Remote Dev stack
├── launcher      7680 — navigation only
├── codex         7681 — independently authenticated terminal
└── antigravity   7682 — optional/experimental independently authenticated terminal
```

Implemented foundations include:

- one canonical `ghcr.io/experience83/remote-dev` image/package reused by fixed roles;
- `launcher`, `codex`, `antigravity` and `shell` runtime roles;
- one primary launcher URL that navigates to independent agent endpoints rather than proxying terminal traffic;
- one configuration-backed `WEB_PASSWORD` runtime contract for protected browser endpoints, with distinct values per role;
- role-private workspace, agent/runtime, GitHub, Git, SSH and integration state;
- one canonical persistent-data layout with shared bootstrap/preflight code;
- one bounded project resolver/manager below each role-private `/workspace` collection root;
- no agent workspace/state/password or Docker/Podman socket in the launcher;
- hardened outer-container boundaries and cross-service isolation canaries validated on TrueNAS;
- deterministic TrueNAS bootstrap plus Generic/POSIX ACL audit/migration guidance;
- Codex as the bundled reference agent with immutable fallback plus explicit optional runtime admission;
- Antigravity as an optional **experimental** official-CLI integration with explicit install/update, private persistence and reviewed admission/integrity controls;
- Context7 for Codex plus reviewed transient device-code onboarding;
- `dev -> edge -> stable = latest` channel semantics with dated edge build identity separate from channel/provenance.

Still optional/future rather than part of the current core architecture: #181 stronger browser access, #170 native Community App research, #124 inbound key-only SSH, #71 SMB, #95 Context7 for Antigravity, #159 Antigravity autonomous mode, #112 ARM64, #121 broader tooling, #148 concurrent sessions/worktrees, #151 isolated container build/test tooling and separate frontend/mobile work.

Claude remains reserved and unimplemented until a dedicated implementation, licensing and isolation path is reviewed.

## User-facing contract

A normal deployment consists of one App/Compose stack, one intended image reference, one navigation-only launcher and one isolated service for each enabled agent. Docker may instantiate several containers from the same image, but immutable executable layers are shared while mutable state remains isolated by service mounts.

The launcher selects only fixed reviewed destinations. It does not execute the agent, relay ttyd HTTP/WebSocket traffic, receive an agent password or manage containers.

## Launcher boundary

The launcher:

- runs directly as UID/GID `65532` in the reviewed production Compose profiles;
- restores no capabilities after `cap_drop: [ALL]`;
- receives no bind/persistent/agent-state mounts;
- receives no Codex/Antigravity OAuth/config, GitHub/Git/SSH state or optional runtime state;
- receives no Docker/Podman socket;
- exposes fixed reviewed navigation only;
- validates destination/path inputs and matching origins;
- applies a restrictive Content Security Policy;
- supports optional configuration-backed Basic authentication without introducing agent credentials or persistent browser-password files.

The normal private-network launcher is deliberately password-free because it is navigation only and carries no agent secret. Agent endpoints remain independently authenticated. A stronger single-origin/auth-gateway design, if adopted later, requires its own threat-model review under #181.

## Agent roles

### Codex

Codex is the bundled reference implementation. Supported paths include device-code authentication, project-scoped Start/Resume, tmux persistence, autonomous/guarded approval selection, explicit optional official runtime updates with immutable bundled fallback, Context7 for Codex and diagnostics/version/trust reporting.

The default image does not install system Bubblewrap. The supported project-owned Codex launcher explicitly disables the unsupported inner sandbox; the outer container plus its mounts are the isolation boundary. Guarded prompts add confirmation friction but are not a filesystem sandbox.

### Antigravity

Antigravity is an **optional experimental** role with its own workspace, configuration, vendor runtime and other role-private state.

Remote Dev does not redistribute Google's proprietary installer/CLI bytes. The `agy` runtime is installed or updated only by explicit user action through the reviewed official-source path into private persisted state; normal startup does not download it and supported sessions keep vendor automatic update disabled.

The current runtime contract includes review-pending admission, private manifest/provenance state, lightweight offline status, explicit full verification/Doctor checks, exactly one mandatory full integrity gate before execution, project-scoped Start/Resume and completed TrueNAS update/rollback/persistence/isolation evidence.

The #53 human terms/policy disposition is complete. The project deliberately keeps Antigravity experimental because the official-CLI container/wrapper model is a project interpretation of current vendor policy, not Google approval, certification or endorsement. Remote Dev must not implement an alternative Antigravity service client or reuse/export Antigravity/Google OAuth credentials for other coding agents/services.

The scheduled #83 review path keeps detection and execution separate: scheduled discovery treats bounded vendor bytes as data and executes no vendor code; changed candidates require the explicit trusted review workflow before executable evidence is admitted.

See `docs/antigravity-runtime-admission.md` / `.es.md` and `third_party/optional-agents.md`.

### Shell

The shell role remains available for troubleshooting and opens at the role workspace collection root.

## Project-scoped workspace contract

Each agent service receives a private host workspace collection mounted at `/workspace`. That mount is not an implicit repository. A normal project is one validated immediate child such as `/workspace/pollenlevels`.

The common resolver/manager discovers only non-symlink immediate children, validates conservative one-component names, auto-resolves exactly one project, requires explicit selection when several exist, creates only validated direct children and deletes only after exact-name confirmation.

Project selection is a working-directory/session contract, **not** isolation from sibling projects already mounted into the same role container. Codex and Antigravity keep separate writable workspace mounts; use independent clones/worktrees across roles.

Normal agent sessions use the hidden role-private `/workspace/.remote-dev-tmp` tree for development temporary/cache state. It is excluded from project discovery and is not a trusted staging area for credential/admission operations.

## Persistent-data boundaries

Generic Compose derives persistent paths from `REMOTE_DEV_DATA_ROOT`, but that parent root is never mounted wholesale into a container.

The Codex service receives narrow children such as:

```text
workspaces/codex    -> /workspace
state/codex/agent   -> /root/.codex
state/codex/runtime -> /root/.local/share/remote-dev/codex-runtime
state/codex/gh      -> /root/.config/gh
state/codex/git     -> /root/.config/git
state/codex/ssh     -> /root/.ssh
```

Antigravity receives its own disjoint corresponding children. Browser-terminal passwords are deployment configuration, not persisted data files. The former file-backed browser-authentication path is not part of the canonical layout.

`scripts/lib/data_layout.py` is the canonical host-side directory contract. Both `scripts/init-data-layout.py` and `scripts/preflight-data-layout.py` consume it. The initializer requires the administrative root to exist, rejects symlink ancestry, creates only missing canonical descendants and preserves existing content/mountpoints. Preflight validates the same layout before deployment.

## TrueNAS dataset and ACL contract

For the supported reference Host Path deployment, the normal layout is one administrator-created root dataset such as `/mnt/Pool1/remote-dev` plus ordinary directories below it unless the operator deliberately chooses child datasets.

The reference private-state security contract uses **Generic/POSIX**, not Apps-preset NFSv4 inheritance. `scripts/truenas-acl-audit.py` is the authoritative read-only host audit; `remote-dev-doctor` intentionally checks only container-visible mount modes and does not claim to infer the host ACL type.

See `docs/truenas-acl-contract.md` / `.es.md` for rationale and migration/rollback guidance.

## Browser authentication contract

Protected browser endpoints use one runtime variable:

```text
WEB_PASSWORD
```

Codex and Antigravity receive distinct configured values. Optional launcher authentication uses its own value and the launcher never receives an agent password. The previous file-backed browser-password mechanism is retired.

Host TrueNAS/Docker root/admin can inspect deployment configuration and is inside the trust boundary. The primary product boundary is private-network exposure plus container/mount/credential isolation, not secrecy from the host administrator.

## Security and isolation

Each outer container is a separate boundary. Anyone with terminal/root access inside an agent service is trusted for the state mounted into that service.

Reviewed production Compose profiles apply read-only root filesystems, `no-new-privileges`, `cap_drop: [ALL]`, no supplementary groups, bounded private tmpfs/PID controls, launcher UID/GID `65532` with zero restored capabilities and only the exact reviewed agent capability minimum where required.

The stack does not require privileged mode, `SYS_ADMIN`, host PID/networking, unconfined profiles, container-engine sockets or host-root mounts. See `docs/security.md` for the exact capability/tmpfs/mount contract.

## Updates and release identity

All enabled services use the same intended `REMOTE_DEV_IMAGE` reference. The image-bundled Codex release remains the reviewed fallback. Optional Codex and Antigravity runtimes persist only in their role-private state and are not immutable image contents.

Release maturity and build identity are separate:

```text
dev -> edge -> stable = latest
```

An edge publication embeds a build identity such as:

```text
edge-YYYY.MM.DD-<short-sha>
Channel: edge
```

The full source revision and OCI digest remain stronger provenance. `latest` is only an alias of an explicit stable release and never points to `dev` or `edge`.

## Validation contract

Automated and real-system validation together cover, where relevant, role/start-mode validation, project safety, Codex/Antigravity project-scoped launch, launcher fixed navigation and isolation, intended common image identity, exact role-private mounts, deterministic bootstrap/preflight/ACL audit, independent agent authentication, outer-container hardening, Codex optional-runtime fallback, Antigravity admission/integrity/review automation, Context7 credential/device-login boundaries, notices/SBOM/vulnerability gates and publication identity.

Manual TrueNAS validation remains required when a change affects real deployment behavior; completed lifecycle evidence should not be relisted as future work merely because the repository remains pre-stable.

## Non-goals

The current architecture does not include enterprise multi-tenant RBAC, administrator secrecy, several agents in one container, shared mutable credentials/state between roles, one writable checkout shared by agents by default, dynamic privileged child containers, engine-socket access, weakened host/container security to force an inner sandbox, or Claude support before dedicated review.
