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

The Codex endpoint uses its own password source and authenticates independently. Credentials are never shared, embedded into the navigation URL or forwarded by the launcher.

## Shared immutable image

The final image contains Ubuntu and Remote Dev scripts, Git/Git LFS/OpenSSH/GitHub CLI, Python, Node.js, npm, uv, mise, ttyd, tmux, tini, the launcher runtime and Codex CLI as the built-in reference agent.

Sharing executable layers does not share mutable state or secrets. Runtime and Compose tests assert that launcher and Codex use the same image reference/ID while retaining separate service boundaries.

## Service roles

### Launcher

`REMOTE_DEV_ROLE=launcher` accepts only the `menu` start mode. It does not initialize a workspace, GitHub configuration, Git configuration, SSH state, agent state or tmux session.

### Codex

Codex retains device-code authentication, start/resume actions, persistent tmux sessions, autonomous/guarded approval modes, diagnostics and post-session credential hardening.

### Shell

The shell role remains available for direct troubleshooting and uses ttyd/tmux without inspecting Codex-specific state.

### Optional agents

A proprietary optional agent may be installed or updated only through an explicit reviewed action using an official vendor-controlled source. Missing agents are reported as unavailable and are never downloaded during launcher or container startup.

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
├── state/
│   └── codex/
│       ├── agent/
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
| `state/codex/gh` | `/root/.config/gh` |
| `state/codex/git` | `/root/.config/git` |
| `state/codex/ssh` | `/root/.ssh` |
| `secrets/codex/web_password.txt` | `/run/secrets/web_password` |

The launcher remains mount-free. The parent data root, `/root`, `/home`, `/mnt`, host root and container-engine sockets are never mounted wholesale.

Compose bind mounts set `create_host_path: false`. Required host directories must be created deliberately; an incorrect path fails instead of creating an ambiguous directory.

There is no data-layout compatibility alias, automatic migration, copying, symlink or deletion. Existing experimental directories must be recreated or moved manually before deploying the new stack.

Optional SMB sharing is not part of this contract. Only the `workspaces` boundary may be evaluated later under #71; `state` and `secrets` must remain private.

## Workspace concurrency

The default stack does not mount one writable checkout into two agent services. Future multi-agent users should use separate clones or Git worktrees and coordinate branches normally.

## Security and trust boundaries

Each outer container is a separate boundary. Anyone with terminal/root access inside an agent service is trusted for the state mounted into that service. The launcher cannot see or authenticate to agent state because neither the state nor the agent password is mounted there.

The stack does not require privileged mode, `SYS_ADMIN`, host PID/networking, unconfined security profiles, container-engine sockets or host-root mounts.

## Versioning and updates

All stack services use the same image reference. Built-in components are updated through reviewed image rebuilds. Future vendor-installed agents may keep an independent persisted version only inside their own private service state.

A broken optional agent must not make the launcher or Codex unhealthy. Healthchecks validate role readiness without requiring user login.

The `codex-remote-dev` package and `CODEX_IMAGE` variable remain image-name compatibility aliases through `v0.1.x`; they do not preserve the removed Codex-specific data layout.

## Validation contract

Automated tests cover:

- fixed role/start-mode validation;
- launcher optional authentication, origin policy, CSP and fixed navigation;
- launcher absence of mounts and container-engine sockets;
- one image reference across launcher and Codex;
- exact role-scoped Codex mount targets and canonical source suffixes;
- failure to create missing bind paths silently;
- absence of legacy data-root names and paths;
- role-aware health checks;
- existing Codex start, resume, policy, diagnostics, ttyd and tmux behavior.

Manual TrueNAS validation is performed after the related implementation slices are ready and includes persistence, sessions, credentials, isolation and recreation. Windows/SMB testing remains separate under #71.

## Non-goals

This architecture does not include:

- a virtual-machine distribution;
- several agents in one agent container;
- one manually maintained TrueNAS App per agent;
- shared OAuth/token, web-password, GitHub, Git, SSH or workspace state between agents;
- dynamic privileged child containers;
- weakening TrueNAS/Docker security to force an inner sandbox;
- shipping Antigravity or Claude before dedicated legal, installation and isolation validation.
