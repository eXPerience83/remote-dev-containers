# Remote Dev architecture

## Status

The accepted architecture is one user-installed Remote Dev stack, one immutable image digest and one isolated service per enabled coding agent.

Implemented:

- one canonical Remote Dev image/package;
- fixed `launcher`, `codex` and `shell` runtime roles;
- one Compose/TrueNAS stack containing launcher and Codex services;
- one primary launcher URL;
- one image reference reused by both services;
- navigation from the stateless launcher to the independently authenticated Codex endpoint;
- optional file-backed launcher Basic authentication and required Codex terminal authentication;
- one canonical role-neutral persistent-data layout;
- one bounded role-neutral project resolver/manager below each private agent workspace mount;
- no agent-state mounts, agent credentials or Docker socket in the launcher.

Still pending:

- optional Antigravity and future Claude services;
- the later outer-hardening and cross-service canary phase under #42;
- optional TrueNAS SMB/ACL workspace integration under #71;
- any reviewed one-origin reverse-proxy design.

Related work:

- issue #24 defines the architecture contract;
- issue #25 tracks the role-neutral runtime and launcher epic;
- issue #36 records the TrueNAS outer-isolation and no-Bubblewrap decision;
- issue #70 owns the canonical data layout;
- issue #126 defines `/workspace` as a role-private project collection root and the common project-scoped launch contract;
- issue #31 tracks the complete delivery sequence.

## User-facing contract

A supported installation consists of:

- one Remote Dev App or Compose stack;
- one final Remote Dev image digest;
- one primary browser entry point;
- one launcher service;
- one isolated service for each enabled coding agent.

Docker may instantiate several containers from the image, but it stores and reuses the same immutable image layers. Users do not maintain a separate image or TrueNAS App for every agent.

## Current topology

```text
Remote Dev App / Compose stack
├── launcher service  (primary port 7680, no password by default)
└── Codex service     (terminal port 7681, independently authenticated)
```

Both services reference the same `REMOTE_DEV_IMAGE` value. Implemented roles are:

```text
REMOTE_DEV_ROLE=launcher|codex|shell
```

`antigravity` and `claude` remain reserved and fail without downloading anything.

## One launcher, isolated execution

The launcher provides the normal browser entry point and lists only reviewed services. Selecting Codex navigates to the Codex service's own authenticated endpoint. The launcher does not execute Codex and does not relay terminal HTTP or WebSocket traffic.

The launcher:

- is a project-owned Python standard-library HTTP service;
- drops permanently to UID/GID `65532` before serving;
- requires no password by default in localhost/LAN/Tailscale examples;
- supports optional file-backed Basic authentication through `compose/launcher-auth.yml`;
- validates its fixed destination host, scheme, port and path;
- checks matching origins when an `Origin` header is present;
- sends a restrictive nonce-based Content Security Policy;
- accepts only `GET` and `HEAD`;
- exposes a secret-free health endpoint;
- receives no agent workspace, state, OAuth token, GitHub configuration, SSH key or Docker/Podman socket.

The base launcher has no mounts. The optional authentication overlay adds only its dedicated read-only launcher password secret; it never receives an agent password or agent state.

The Codex endpoint uses its own password source and authenticates independently. Credentials are never shared, embedded into the navigation URL or forwarded by the launcher.

## Shared immutable image

The final image contains Ubuntu and Remote Dev scripts, Git/Git LFS/OpenSSH/GitHub CLI, Python, Node.js, npm, uv, mise, ttyd, tmux, tini, the launcher runtime and Codex CLI as the built-in reference agent.

Sharing executable layers does not share mutable state or secrets. Runtime and Compose tests assert that launcher and Codex use the same image reference/ID while retaining separate service boundaries.

## Service roles

### Launcher

`REMOTE_DEV_ROLE=launcher` accepts only the `menu` start mode. It does not initialize a workspace, GitHub configuration, Git configuration, SSH state, agent state or tmux session.

### Codex

Codex retains device-code authentication, start/resume actions, persistent tmux sessions, autonomous/guarded approval modes, diagnostics and post-session credential hardening. Start and Resume resolve a concrete project below `/workspace` and pass that directory through the project-owned `run-codex` wrapper, so repository discovery and repository-scoped instructions are not anchored accidentally at the collection root.

### Shell

The shell role remains available for direct troubleshooting and uses ttyd/tmux without inspecting Codex-specific state. General shell mode opens at the role workspace collection root rather than requiring an active project.

### Optional agents

A proprietary optional agent may be installed or updated only through an explicit reviewed action using an official vendor-controlled source. Missing agents are reported as unavailable and are never downloaded during launcher or container startup.

## Project-scoped workspace contract

The host mount for an agent role is exposed inside that container as `/workspace`. That mount is a **project collection root**, not an implicit repository. A normal agent project is one validated immediate child:

```text
/workspace/
├── pollenlevels/
├── remote-dev-containers/
└── another-project/
```

The role-neutral runtime owns one bounded resolver/manager:

- discover non-symlink immediate child directories only;
- validate one-component repository-friendly project names;
- auto-resolve exactly one project;
- require explicit selection when several projects exist;
- create only a validated empty direct child;
- recursively delete only a validated direct child after exact-name confirmation;
- reject traversal, arbitrary absolute project selectors and symlink projects.

The interactive selection is transient to the current menu/tmux session. Direct `agent` mode may use `REMOTE_DEV_PROJECT=<name>`; without it, direct mode requires exactly one valid project. It never silently falls back to running an agent at `/workspace` when the project is ambiguous or missing.

Project selection is a working-directory and routing contract, not an intra-service access-control boundary. The entire role-private `/workspace` mount remains visible to processes in that agent container, so selecting one child does not isolate sibling projects. Filesystem isolation is provided by the outer container and its mount set; use separate services or mounts if stronger separation between projects is required.

This contract is shared code only. Codex and any future supported agent continue to receive separate writable workspace mounts. Antigravity reuses this project wiring only as an experimental integration; that reuse does not establish supported deployment status, and real TrueNAS project/session validation remains deferred to #131. The same logical repository should use separate clones or Git worktrees across agent services rather than one concurrently writable checkout.

## Canonical persistence boundaries

Generic Compose derives all persistent paths from one variable:

```text
REMOTE_DEV_DATA_ROOT
```

The canonical administrative layout is:

```text
REMOTE_DEV_DATA_ROOT/
├── workspaces/
│   └── codex/
│       └── <project>/
├── state/
│   └── codex/
│       ├── agent/
│       ├── runtime/
│       ├── gh/
│       ├── git/
│       └── ssh/
└── secrets/
    └── codex/
        └── web_password.txt
```

The Codex service receives only these child paths:

| Host child path | Container target |
|---|---|
| `workspaces/codex` | `/workspace` |
| `state/codex/agent` | `/root/.codex` |
| `state/codex/runtime` | `/root/.local/share/remote-dev/codex-runtime` |
| `state/codex/gh` | `/root/.config/gh` |
| `state/codex/git` | `/root/.config/git` |
| `state/codex/ssh` | `/root/.ssh` |
| `secrets/codex/web_password.txt` | `/run/secrets/web_password` |

The base launcher remains mount-free. The parent data root, `/root`, `/home`, `/mnt`, host root and container-engine sockets are never mounted wholesale.

Before deployment, `scripts/preflight-data-layout.py` validates that every canonical directory exists, that none is a symlink, and that the password path is a non-empty regular file with restrictive permissions. This host-side preflight is authoritative. Compose bind mounts additionally request `create_host_path: false` as defense-in-depth, but the design does not rely on every Compose implementation enforcing that option.

There is no data-layout compatibility alias, automatic migration, copying, symlink or deletion. Existing experimental directories must be recreated or moved manually before deploying the new stack.

Optional SMB sharing is not part of this contract. If evaluated later under #71, it should target explicitly selected concrete project directories below the `workspaces` boundary rather than exposing the whole collection root by default; `state` and `secrets` must remain private.

## Workspace concurrency

The default stack does not mount one writable checkout into two agent services. Future multi-agent users should use separate clones or Git worktrees and coordinate branches normally.

## Security and trust boundaries

Each outer container is a separate boundary. Anyone with terminal/root access inside an agent service is trusted for the state mounted into that service. The launcher cannot see or authenticate to agent state because neither the state nor the agent password is mounted there.

The stack does not require privileged mode, `SYS_ADMIN`, host PID/networking, unconfined security profiles, container-engine sockets or host-root mounts.

Both deployment definitions enforce the same outer-container hardening: read-only root filesystems, `no-new-privileges`, `cap_drop: [ALL]`, bounded private `/tmp` and `/run` tmpfs filesystems and PID ceilings of 64 for launcher and 1024 per agent. Launcher restores only `DAC_READ_SEARCH` to read a host-owned mode-`0600` file-backed secret and `SETGID`/`SETUID` for its permanent UID/GID 65532 drop; Codex and Antigravity restore only `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `KILL`, `SETGID` and `SETUID` for role-private host-ownership compatibility, persistent-state hardening and bounded UID/GID 65534 candidate execution. The live isolation canary verifies the effective launcher identity/capability drop, exact configured agent capabilities, transient mounts, same image ID and distinct writable sources.

Project selection neither broadens nor narrows that container boundary. The project resolver accepts only validated direct children of the already-mounted role workspace, rejects symlink project entries, and never converts an editable project name into a shell fragment; the rest of that mounted workspace remains accessible inside the service.

## Versioning and updates

All stack services use the same image reference. The image-bundled Codex release remains the reviewed, tested fallback. Codex may also use a newer official release only after an explicit project-owned admission into its private `state/codex/runtime` mount; that optional runtime never replaces the bundled executable and normal startup performs no update network access. Other built-in components continue to be updated through reviewed image rebuilds, while future vendor-installed agents may keep an independent persisted version only inside their own private service state.

A broken optional agent must not make the launcher or Codex unhealthy. Healthchecks validate role readiness without requiring user login.

`ghcr.io/experience83/remote-dev` is the sole published runtime package. The legacy `CODEX_IMAGE` variable remains a configuration fallback through `v0.1.x`, but it should point to the canonical package; the old `codex-remote-dev` GHCR package is retired. Local compatibility tags may still use the old name without creating a registry package.

## Validation contract

Automated tests cover:

- fixed role/start-mode validation;
- bounded project-name/path validation, zero/one/multiple resolution, symlink exclusion and create/delete guards;
- selected-project Codex start/resume and direct-agent launch behavior;
- launcher optional authentication, origin policy, CSP and fixed navigation;
- launcher absence of agent mounts and container-engine sockets;
- one image reference across launcher and Codex;
- exact role-scoped Codex mount targets and canonical source suffixes;
- host-side rejection of missing, symlinked or malformed canonical paths;
- restrictive file-password permissions;
- absence of legacy data-root names and paths;
- role-aware health checks;
- existing Codex start, resume, policy, diagnostics, ttyd and tmux behavior.

Manual TrueNAS validation is performed after the related implementation slices are ready and includes the host preflight, persistence, sessions, credentials, project selection/create/delete safety, isolation and recreation. Windows/SMB testing remains separate under #71.

## Non-goals

This architecture does not include:

- a virtual-machine distribution;
- several agents in one agent container;
- one manually maintained TrueNAS App per agent;
- shared OAuth/token, web-password, GitHub, Git, SSH or workspace state between agents;
- dynamic privileged child containers;
- weakening TrueNAS/Docker security to force an inner sandbox;
- shipping Antigravity or Claude before dedicated legal, installation and isolation validation.
