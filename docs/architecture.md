# Remote Dev architecture

## Status

This document records the accepted target architecture and the portion now implemented by the experimental edge stack.

Implemented:

- one canonical Remote Dev image/package;
- fixed `launcher`, `codex` and `shell` runtime roles;
- one Compose/TrueNAS stack containing launcher and Codex services;
- one primary launcher URL;
- one image reference reused by both services;
- navigation from the stateless launcher to the independently authenticated Codex endpoint;
- optional file-backed launcher Basic authentication and required Codex terminal authentication;
- no agent-state mounts, agent credentials or Docker socket in the launcher.

Still pending under issues #25 and #31:

- the neutral persistent-data layout and migration from the Codex-only paths;
- optional Antigravity and future Claude services;
- the later outer-hardening and cross-service canary phase;
- any reviewed one-origin reverse-proxy design.

Related work:

- issue #24 defines this architecture contract;
- issue #25 implements the neutral image roles, launcher and stack migration;
- issue #36 evaluates the TrueNAS outer-isolation model;
- issue #31 tracks the complete delivery sequence.

## User-facing contract

A supported installation consists of:

- one Remote Dev App or Compose stack;
- one final Remote Dev image digest;
- one primary browser entry point;
- one launcher service;
- one isolated service for each enabled coding agent.

Docker may instantiate several containers from the image, but it stores and reuses the same immutable image layers. Users do not install or maintain a separate image or TrueNAS App for every agent.

The current implementation includes the launcher and Codex services. Codex remains the reference agent during the migration.

## Current topology

```text
Remote Dev App / Compose stack
├── launcher service  (primary port 7680, no password by default)
└── Codex service     (terminal port 7681, independently authenticated)
```

Both services reference the same `REMOTE_DEV_IMAGE` value. The fixed roles are:

```text
REMOTE_DEV_ROLE=launcher|codex|shell
```

`antigravity` and `claude` remain reserved and fail without downloading anything.

## One launcher, isolated execution

The launcher provides the normal user entry point and lists only available, supported tools. Selecting Codex navigates the browser to the Codex service's own authenticated endpoint. The launcher does not execute Codex and does not relay the terminal's HTTP or WebSocket traffic.

The implemented launcher:

- is a project-owned Python standard-library HTTP service bundled in the final image;
- reads an optional launcher password during startup when configured and then clears supplementary groups and drops permanently to UID/GID `65532` before binding or serving;
- requires no password by default in the localhost/LAN/Tailscale examples;
- supports optional HTTP Basic authentication through the separate file-backed generic Compose override;
- does not mount or know the Codex terminal password;
- validates DNS names and IPv4/IPv6 literals and rejects an embedded destination port because the port has its own setting;
- validates its fixed destination scheme, port and path settings;
- restricts paths to safe RFC 3986 URL-path characters before embedding them in the page;
- uses the browser hostname and scheme when no explicit public host/scheme is configured;
- checks same-origin requests when an `Origin` header is present;
- sends a restrictive nonce-based Content Security Policy;
- accepts only `GET` and `HEAD`;
- exposes an unauthenticated, secret-free health endpoint;
- contains no agent OAuth tokens, histories, workspaces, GitHub state or SSH keys;
- receives no Docker/Podman socket and creates no containers.

The Codex endpoint uses its own mounted password secret and authenticates independently. Credentials are never shared, embedded into the navigation URL or forwarded by the launcher. Enabling optional launcher Basic authentication does not replace the Codex password.

The direct Codex port remains published because the navigation design does not proxy terminal traffic. It is the normal navigation destination and can also be used for troubleshooting. The documented workflow still begins at the launcher URL.

A future fixed reverse proxy could provide one browser origin, but it would become a trusted transport component capable of observing terminal traffic. That requires a separate threat-model review and is not part of the current implementation.

## Shared immutable image

The final image contains:

- Ubuntu and Remote Dev scripts;
- Git, Git LFS, OpenSSH client and GitHub CLI executable;
- Python, Node.js, npm, uv and mise;
- ttyd, tmux, tini and common shell/build/search utilities;
- launcher runtime;
- neutral diagnostics, health checks and version reporting;
- Codex CLI as the built-in reference agent.

Sharing executables through image layers does not share mutable state or secrets. Runtime tests and Compose validation assert that launcher and Codex use the same image reference/ID, while only the Codex service requires an agent-terminal password source by default.

## Service roles

### Launcher role

`REMOTE_DEV_ROLE=launcher` starts `remote-dev-launcher` directly. It accepts only the `menu` start mode and does not initialize a workspace, GitHub configuration, Git configuration, SSH state, Codex state or tmux session.

Launcher diagnostics report image identity, fixed routing configuration and available roles without reading agent state. Its healthcheck calls the secret-free `/healthz` endpoint.

### Codex role

Codex retains:

- device-code authentication;
- start and resume actions;
- persistent tmux sessions;
- autonomous and guarded approval modes;
- Codex-specific diagnostics;
- post-session credential permission hardening;
- the existing narrow persistent mounts.

### Shell role

The shell role remains available for direct troubleshooting and uses ttyd/tmux without inspecting Codex state.

### Optional agent roles

An optional proprietary agent will be installed or updated only through an explicit reviewed action from an official vendor-controlled source unless redistribution rights are confirmed.

A missing optional agent is reported as unavailable. It is never downloaded during launcher or container startup. Claude remains unavailable until its dedicated path is implemented and validated.

## Persistence boundaries

The launcher service is stateless. It receives no agent data mounts and requires no password file, secret or dataset by default. An advanced generic Compose deployment may explicitly add `compose/launcher-auth.yml`, which mounts one separate file-backed launcher password as a Compose secret. That value must never be reused as an agent password and is not rendered into the service environment.

The Codex service temporarily retains the existing layout:

```text
CODEX_DATA_ROOT/
├── workspace/
├── codex/
├── gh/
├── git/
└── ssh/
```

The TrueNAS reference keeps the existing Codex secret at:

```text
/mnt/Pool1/codex/secrets/web_password.txt
```

No launcher dataset or launcher password file is required by the default TrueNAS deployment.

The later migration slice will introduce the neutral administrative layout without deleting or sharing existing Codex state:

```text
remote-dev-data/
├── launcher/
├── codex/
│   ├── workspace/
│   ├── agent/
│   ├── gh/
│   ├── git/
│   └── ssh/
└── future-agent/
    └── private state
```

The parent data directory is never mounted wholesale. Agent services receive only their own child paths.

| State | Shared in image | Shared between services | Persistent per service |
|---|---:|---:|---:|
| Common executables | Yes | Read-only image layers | No |
| Workspace or worktree | No | No by default | Agent only |
| Agent authentication/configuration | No | No | Agent only |
| Agent web password | No | No | Agent only |
| Optional launcher password | No | No | Only when advanced override is enabled |
| GitHub CLI configuration | Executable only | No | Agent only |
| Git global configuration | Executable only | No | Agent only |
| SSH keys/configuration | Client only | No | Agent only |
| Launcher navigation configuration | Runtime only | Not mounted into agents | Launcher only |

The supported configuration does not mount `/root`, `/home`, `/opt`, `/usr/local`, the parent data directory or Docker/Podman sockets.

## Workspace concurrency

The default stack does not mount one writable checkout into two agent services. Future multi-agent users should use separate Git worktrees or clones and coordinate branches normally.

## Security and trust boundaries

Each outer container is a separate boundary. Anyone with terminal/root access inside the Codex service is trusted for the state mounted into Codex, but the launcher cannot see that state or authenticate to the terminal because neither the state nor the Codex password is mounted there.

The launcher may be unauthenticated only on a trusted private endpoint such as localhost, a LAN binding or Tailscale. Neither port is intended for direct Internet exposure.

The stack does not require:

- privileged mode;
- `SYS_ADMIN`;
- unconfined seccomp/AppArmor;
- Docker or Podman sockets;
- host networking;
- host-root mounts;
- host security changes to start an inner sandbox.

The launcher is navigation, not a container-management control plane and not a terminal proxy.

## Versioning and updates

All stack services use the same image reference. Immutable deployments record the published digest and embedded source revision.

Built-in components are updated through reviewed image rebuilds. Future vendor-installed agents may keep an independent persisted version only inside their own service state.

A broken optional agent must not make the launcher or Codex unhealthy. Healthchecks validate role readiness without requiring user login.

## Migration from the Codex-only App

The launcher slice preserves the existing Codex service name, container name, `CODEX_DATA_ROOT` variable and mount paths. Existing data and the Codex terminal password are not copied, renamed or exposed to the launcher.

The launcher introduces no required dataset or password file. Existing deployments created from the first launcher example may remove the obsolete launcher password mount and use the current password-free base Compose. Operators who deliberately retain launcher Basic authentication must use the separate `compose/launcher-auth.yml` file-backed secret override rather than an inline environment value.

The later data-migration slice must:

- preserve the existing workspace and credentials;
- avoid deleting or silently copying authentication state;
- map existing Codex paths only into the Codex service;
- document rollback;
- avoid exposing Codex state or credentials to the launcher or future agents.

The `codex-remote-dev` package and `CODEX_IMAGE` variable remain compatibility aliases through `v0.1.x` and will not be removed before `v0.2.0`.

## Validation contract

Automated tests now cover:

- fixed launcher-role resolution and invalid-mode rejection;
- both unauthenticated and optional Basic-auth launcher behavior;
- malformed credentials, origin checking, CSP and method restrictions;
- launcher privilege drop before serving when startup begins as root;
- fixed Codex navigation configuration without password exposure;
- structural DNS/IP validation and rejection of an embedded route port;
- rejection of unsafe configured URL paths;
- absence of a required launcher password source and preservation of the Codex password source;
- one file-backed launcher password source only when the optional override is enabled;
- absence of the launcher password value from rendered Compose configuration;
- separation of launcher and Codex authentication sources;
- rejection of host networking, added capabilities, privileged mode and Docker/Podman socket mounts for both services;
- role-aware healthchecks;
- launcher diagnostics without agent-state access;
- generic and TrueNAS Compose topology rendered from deterministic defaults;
- one image reference across launcher and Codex;
- absence of workspace/Codex/GitHub/Git/SSH configuration in the launcher;
- launcher and Codex containers reusing the same image ID in runtime smoke tests;
- existing Codex start, resume, policy, diagnostics, ttyd and tmux smoke tests.

Still required before the architecture is advertised as stable:

- real TrueNAS launcher-to-Codex navigation;
- browser refresh/reconnect behavior;
- existing-data migration;
- later synthetic cross-service canaries and outer hardening;
- optional-agent service validation.

## Non-goals

This architecture does not include:

- a virtual-machine distribution;
- several agents in one agent container;
- one manually maintained TrueNAS App per agent;
- shared OAuth/token or web-password files between services;
- dynamic privileged child containers;
- concurrent writes by several agents to one checkout by default;
- weakening TrueNAS/Docker security to force an inner sandbox;
- shipping Claude before dedicated implementation and validation.
