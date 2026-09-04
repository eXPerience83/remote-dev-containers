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
- one primary launcher URL that navigates to independent agent endpoints rather than proxying their terminal traffic;
- one configuration-backed `WEB_PASSWORD` runtime contract for protected browser endpoints, with distinct values per role;
- role-private workspace, agent/runtime, GitHub, Git, SSH and integration state;
- one canonical persistent-data layout with shared bootstrap/preflight code;
- one bounded project resolver/manager below each role-private `/workspace` collection root;
- no agent workspace/state/password or Docker/Podman socket in the launcher;
- hardened outer-container boundaries and cross-service isolation canaries validated on TrueNAS;
- deterministic TrueNAS bootstrap plus Generic/POSIX ACL audit/migration guidance;
- Codex as the bundled reference agent with an immutable fallback plus explicit optional runtime admission;
- Antigravity as an optional **experimental** official-CLI integration with explicit install/update, private persistence and reviewed admission/integrity controls;
- Context7 for Codex plus reviewed transient device-code onboarding;
- `dev -> edge -> stable = latest` channel semantics with dated edge build identity separate from channel/provenance.

Still optional/future rather than part of the current core architecture:

- #181 stronger browser/remote-access security (private mesh/Tailscale, HTTPS, reviewed auth gateway, identity headers, passkeys/MFA);
- #170 native TrueNAS Community App/ixVolumes research;
- #124 role-scoped inbound key-only SSH;
- #71 optional SMB project access;
- #95 Context7 for Antigravity;
- #159 optional Antigravity autonomous mode;
- #112 ARM64;
- #121 broader tooling;
- #148 concurrent sessions/worktrees;
- #151 isolated container build/test tooling;
- frontend/mobile work tracked separately.

Claude remains reserved and unimplemented until a dedicated implementation, licensing and isolation path is reviewed.

## User-facing contract

A normal deployment consists of:

- one Remote Dev App or Compose stack;
- one intended Remote Dev image reference used by enabled services;
- one navigation-only launcher service;
- one isolated service for each enabled coding agent.

Docker may instantiate several containers from the same image, but immutable executable layers are shared while mutable state remains isolated by service mounts.

The launcher is the normal browser entry point. Selecting an agent navigates the browser to that agent's own endpoint. The launcher does not execute the agent, relay ttyd HTTP/WebSocket traffic, receive an agent password or manage containers.

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
- supports optional configuration-backed Basic authentication without introducing password files or agent credentials.

The normal private-network launcher is deliberately password-free because it is navigation only and carries no agent secret. Agent endpoints remain independently authenticated. A stronger single-origin/auth-gateway design, if adopted later, requires its own threat-model review under #181 rather than silently expanding launcher privilege.

## Agent roles

### Codex

Codex is the bundled reference implementation.

Supported paths include:

- device-code authentication and persistent Codex state;
- project-scoped Start and Resume;
- tmux persistence and browser-terminal reconnection;
- deployment/default plus one-launch autonomous/guarded approval selection;
- explicit optional official runtime install/update/removal;
- immutable bundled CLI fallback;
- Context7 hosted MCP management and optional device-code onboarding;
- diagnostics and version/trust reporting.

The default image does not install system Bubblewrap. The supported project-owned Codex launcher explicitly disables the unsupported inner sandbox; the outer container plus its mounts are the isolation boundary. Guarded prompts add confirmation friction but are not a filesystem sandbox.

### Antigravity

Antigravity is implemented as an **optional experimental** role with its own workspace, configuration, vendor runtime and other role-private state.

Remote Dev does not redistribute Google's proprietary installer/CLI bytes. The `agy` runtime is installed or updated only by explicit user action through the reviewed official-source path into private persisted state; normal startup does not download it and supported sessions keep vendor automatic update disabled.

The current runtime contract includes:

- review-pending admission of compatible official-source payloads;
- private manifest/provenance state;
- lightweight offline status;
- explicit full `verify`/Doctor checks;
- exactly one mandatory full integrity gate immediately before real execution;
- project-scoped Start/Resume and vendor-native conversation continuity;
- completed TrueNAS update/rollback/persistence/isolation evidence.

The #53 human terms/policy disposition is also complete. The project deliberately keeps Antigravity experimental because the official-CLI container/wrapper model is a project interpretation of current vendor policy, not Google approval, certification or endorsement. Remote Dev must not implement an alternative Antigravity service client or reuse/export Antigravity/Google OAuth credentials for other coding agents/services.

The scheduled #83 review path keeps detection and execution separate: scheduled discovery treats bounded vendor bytes as data and executes no vendor code; changed candidates require the explicit trusted review workflow before executable evidence is admitted.

See `docs/antigravity-runtime-admission.md` / `.es.md` and `third_party/optional-agents.md` for the detailed trust/distribution boundary.

### Shell

The shell role remains available for troubleshooting and uses ttyd/tmux without inspecting agent-specific state unless that state is explicitly part of the role's mount set. General shell mode opens at the role workspace collection root.

## Project-scoped workspace contract

Each agent service receives a private host workspace collection mounted at `/workspace`.

`/workspace` is not an implicit repository. A normal project is one validated immediate child:

```text
/workspace/
├── .remote-dev-tmp/
├── pollenlevels/
├── remote-dev-containers/
└── another-project/
```

The role-neutral project manager/resolver:

- discovers only non-symlink immediate child directories;
- validates conservative single-component project names;
- auto-resolves exactly one project;
- requires explicit selection when several exist;
- can create an empty validated direct child;
- can delete only a validated direct child after exact-name confirmation;
- rejects traversal, arbitrary absolute selectors and symlink projects.

Normal Start/Resume and direct-agent mode run from a selected `/workspace/<project>`. Project selection is a working-directory/session contract, **not** isolation from sibling projects already mounted into the same role container.

Codex and Antigravity keep separate writable workspace mounts. Sharing the resolver code does not share one checkout between agents. Use independent clones/worktrees if the same logical repository is needed by more than one agent service.

Normal agent sessions use the fixed hidden `/workspace/.remote-dev-tmp` tree for development temporary/cache state. It is role-private, persists with that workspace, is excluded from project discovery and is not a trusted staging area for credential/admission operations.

## Persistent-data boundaries

Generic Compose derives persistent paths from one administrative root:

```text
REMOTE_DEV_DATA_ROOT
```

That parent root is never mounted wholesale into a container.

The Codex service receives narrow children such as:

```text
workspaces/codex    -> /workspace
state/codex/agent   -> /root/.codex
state/codex/runtime -> /root/.local/share/remote-dev/codex-runtime
state/codex/gh      -> /root/.config/gh
state/codex/git     -> /root/.config/git
state/codex/ssh     -> /root/.ssh
```

Antigravity receives its own disjoint corresponding children. Its project configuration and vendor runtime/settings state remain separate; the stack does not make all of `/root/.gemini` writable by mounting it wholesale.

Browser-terminal passwords are deployment configuration, not persisted data files. The retired `WEB_PASSWORD_FILE`/browser-password secrets-tree model is not part of the canonical layout.

`scripts/lib/data_layout.py` is the canonical host-side directory contract. Both `scripts/init-data-layout.py` and `scripts/preflight-data-layout.py` consume it.

The initializer:

- requires the administrative root to exist already;
- rejects symlink roots/intermediate components;
- creates only missing canonical descendants;
- applies initial modes only to paths it creates;
- does not migrate/delete/replace or recursively chmod/chown existing content;
- preserves pre-existing required child-dataset mountpoints.

The preflight validates the same layout before deployment. Compose additionally requests `create_host_path: false` as defense-in-depth rather than relying on implicit bind-source creation.

## TrueNAS dataset and ACL contract

For the supported reference TrueNAS Host Path deployment, the normal layout is one administrator-created root dataset such as `/mnt/Pool1/remote-dev` plus ordinary directories below it unless the operator deliberately chooses child datasets for snapshots/quotas/replication.

The reference private-state security contract uses **Generic/POSIX**, not the Apps-preset NFSv4 inheritance model. Real #186 validation showed that NFSv4 inheritance can grant effective access beyond what simple `0700` mode output suggests.

`scripts/truenas-acl-audit.py` is the authoritative read-only host audit for this contract. `remote-dev-doctor` intentionally checks only container-visible mount modes and does not claim to infer the host ACL type.

See:

- `docs/truenas-acl-contract.md`
- `docs/truenas-acl-contract.es.md`

for the rationale, audit command and safe migration/rollback guidance.

## Browser authentication contract

Protected browser endpoints use one runtime variable:

```text
WEB_PASSWORD
```

- Codex and Antigravity receive distinct non-empty configured values.
- Optional launcher authentication uses its own distinct configured value.
- The launcher never receives an agent password.
- `WEB_PASSWORD_FILE`, browser-password Compose secrets and `/run/secrets/web_password` are retired.
- Host TrueNAS/Docker root/admin can inspect deployment configuration and is inside the trust boundary.

The primary product boundary is therefore private-network exposure plus container/mount/credential isolation, not secrecy from the host administrator. Stronger external access belongs behind a reviewed private-mesh/HTTPS/auth-gateway design rather than another home-grown password storage mode.

## Security and isolation

Each outer container is a separate boundary. Anyone with terminal/root access inside an agent service is trusted for the state mounted into that service.

The stack does not require privileged mode, `SYS_ADMIN`, host PID/networking, unconfined profiles, container-engine sockets or host-root mounts.

Reviewed production Compose profiles apply:

- read-only root filesystems;
- `no-new-privileges`;
- `cap_drop: [ALL]`;
- no supplementary groups;
- bounded private tmpfs and PID ceilings;
- launcher UID/GID `65532` with zero restored capabilities;
- only the exact reviewed agent capability minimum where root-agent state initialization/admission requires it.

Cross-service canaries verify the expected role identity/capability/mount separation and intended common image identity.

See `docs/security.md` for the exact capability/tmpfs/mount contract.

## Updates and release identity

All enabled services use the same intended `REMOTE_DEV_IMAGE` reference.

The image-bundled Codex release remains the reviewed fallback. Optional Codex runtime and Antigravity vendor runtime updates persist only in their own role-private state and are not treated as immutable image contents.

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

Automated and real-system validation together cover, where relevant:

- fixed role/start-mode validation;
- project path/name/selection/create/delete safety;
- Codex/Antigravity project-scoped Start/Resume behavior;
- launcher origin/CSP/fixed-navigation behavior and absence of agent mounts/sockets;
- intended common image identity across enabled services;
- exact role-private mount topology;
- deterministic bootstrap/preflight and ACL-audit contracts;
- independent configuration-backed agent authentication;
- absence of the retired password-file browser-auth design;
- read-only-root/capability/tmpfs/PID/shm hardening and cross-service canaries;
- Codex bundled fallback plus optional runtime trust selection;
- Antigravity explicit install/update, private admission/integrity and review automation boundaries;
- Context7 private managed credential and transient device-login behavior;
- notices, SBOM, vulnerability and publication gates.

Manual TrueNAS validation is still required when a change affects real deployment behavior; already completed lifecycle evidence should not be relisted as future work merely because the repository remains pre-stable.

## Non-goals

The current architecture does not include:

- enterprise multi-tenant RBAC;
- hiding deployment configuration from TrueNAS/Docker administrators;
- several coding agents in one agent container;
- shared OAuth/token/browser-password/GitHub/Git/SSH state between agent roles;
- one writable checkout mounted into several agents by default;
- dynamic privileged child containers;
- Docker/Podman socket access for agents or launcher;
- weakening TrueNAS/Docker security to force an inner sandbox;
- shipping Claude before dedicated review;
- treating optional/future #181/#170/#124/#95/#159/#71/#112/#121/#148/#151 work as a prerequisite for the existing private-network YAML deployment.
