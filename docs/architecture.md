# Remote Dev architecture

## Status

This document records the accepted target architecture for the next Remote Dev
runtime. The current development image is still Codex-specific. Implementation
of the neutral runtime and launcher is tracked separately so this decision does
not imply that unfinished services are already supported.

Related work:

- issue #24 defines this architecture contract;
- issue #25 implements the neutral image roles, launcher and stack migration;
- issue #36 evaluates the TrueNAS outer-isolation model and Bubblewrap removal;
- issue #31 tracks the complete delivery sequence.

## User-facing contract

A supported installation consists of:

- one Remote Dev App or Compose stack;
- one final Remote Dev image digest;
- one primary browser entry point;
- one launcher service;
- one isolated service for each enabled coding agent.

Docker may instantiate several containers from the image, but it stores and
reuses the same immutable image layers. Users do not install or maintain a
separate image or TrueNAS App for every agent.

The current Codex deployment remains the reference implementation during the
migration.

## Target topology

```text
Remote Dev App / Compose stack
├── launcher service
├── Codex service
├── Antigravity service (optional, when supported)
└── Claude service (future)
```

Every service references the same reviewed image digest and starts with a fixed,
validated role. A conceptual selector is:

```text
REMOTE_DEV_ROLE=launcher|codex|antigravity|claude|shell
```

The exact variable and role names are settled by issue #25.

## One launcher, isolated execution

The launcher provides the normal user entry point and lists only available,
supported tools. Selecting an agent navigates or redirects the browser to that
agent service's own authenticated endpoint. The launcher does not execute the
agent or relay the agent terminal's HTTP or WebSocket traffic.

The launcher must:

- expose no Docker or Podman control socket;
- avoid dynamic container creation;
- contain no agent OAuth tokens, histories, workspaces or SSH keys;
- enforce the reviewed browser authentication and origin policy;
- link or redirect only to fixed services declared by the stack;
- remain usable when an optional agent service is unavailable.

Agent services may remain running but idle. This keeps navigation independent
from container-management privileges. Optional direct agent ports may be used
for troubleshooting during development. The documented normal workflow begins
at the single primary launcher entry point.

A future implementation may place a fixed reverse proxy in front of the agent
services to provide one browser origin. Such a proxy is a trusted transport
component because it can observe or alter terminal traffic. It must not mount
agent workspaces or at-rest credentials, but it cannot be described as unable to
inspect secrets entered into or displayed by a proxied terminal. That design
requires an explicit threat-model review in issue #25 before adoption.

## Shared immutable image

The final image contains the project-owned runtime and common development tools:

- Ubuntu base and Remote Dev scripts;
- Git, Git LFS, OpenSSH client and GitHub CLI executable;
- Python, Node.js, npm, uv and mise;
- ttyd, tmux, tini and common shell, build and search utilities;
- neutral diagnostics, health checks and version reporting;
- launcher runtime;
- reviewed managers for optional integrations.

Sharing executables through image layers does not share mutable user state.
Image version and source revision are reported independently from the selected
agent version.

## Service roles

### Launcher role

The launcher owns only the state required for its UI, authentication and fixed
navigation configuration. It does not mount an agent workspace or private agent
state and, in the default design, does not carry agent terminal traffic.

### Codex role

Codex remains built into the reference image and retains:

- device-code authentication;
- start and resume actions;
- persistent Codex sessions;
- Codex-specific diagnostics;
- post-session credential permission hardening.

### Optional agent roles

An optional proprietary agent is installed or updated only through an explicit,
reviewed action from an official vendor-controlled source unless redistribution
rights have been confirmed and documented.

A missing optional agent is reported as unavailable. It is never downloaded
silently during launcher startup or normal container startup.

Claude Code is a future role and is not advertised as supported until its own
installation, licensing, authentication, persistence and sandbox behavior have
been implemented and validated.

## Persistence boundaries

Each agent service receives only its own narrow mounts. A recommended logical
layout is:

```text
remote-dev-data/
├── launcher/
├── codex/
│   ├── workspace/
│   ├── agent/
│   ├── gh/
│   ├── git/
│   └── ssh/
├── antigravity/
│   ├── workspace/
│   ├── agent/
│   ├── gh/
│   ├── git/
│   └── ssh/
└── claude/
    └── ... future private state ...
```

The parent directory is an administrative layout, not a volume mounted into the
services. Compose or TrueNAS mounts only the required child paths into each
service.

| State | Shared in image | Shared between services | Persistent per agent service |
|---|---:|---:|---:|
| Common executables | Yes | Read-only image layers | No |
| Workspace or worktree | No | No by default | Yes |
| Agent authentication and configuration | No | No | Yes |
| Agent cache, history and sessions | No | No | Yes |
| GitHub CLI configuration | Executable only | No | Yes |
| Git global configuration | Executable only | No | Yes |
| SSH keys and configuration | Client only | No | Yes |
| MCP or integration credentials | Manager only | No | Yes |
| Launcher navigation configuration | Runtime only | Not mounted into agents | Launcher only |

The supported configuration does not mount these paths wholesale:

- `/root`;
- `/home`;
- `/opt`;
- `/usr/local`;
- the parent Remote Dev data directory.

Broad mounts could hide image-provided tools or expose another service's private
state.

## Workspace concurrency

The default stack does not mount one writable checkout into two agent services.
Users who intentionally work on the same repository from several agents should
use separate Git worktrees or separate clones and coordinate branches normally.
Sharing one writable checkout is an explicit advanced choice with documented
concurrency risk.

## Security and trust boundaries

The supported TrueNAS-first design treats each outer container as an isolation
boundary. An inner Bubblewrap, Landlock, nsjail or similar sandbox is reported as
active only after a positive runtime test.

The stack must not require:

- privileged mode;
- `SYS_ADMIN`;
- an unconfined seccomp or AppArmor profile;
- the Docker socket;
- host-root mounts;
- host security changes solely to start an inner sandbox.

Anyone with terminal or root access inside an agent service is trusted for all
state mounted into that service. Separate mounts are what prevent that user from
reading another agent service's credentials and workspace. Container separation
does not protect two users who share the same terminal credentials for one
service.

The launcher UI and process must not become a container-management control plane,
must not mount agent secrets and, in the default redirect-based design, must not
receive agent terminal traffic. Any proxy that terminates or relays that traffic
is separately treated as a trusted transport component.

## Versioning and updates

All stack services should reference the same exact image digest. Mutable channel
tags may locate a candidate, but reproducible deployments and rollback record the
published digest and embedded source revision.

Built-in components such as Codex are updated through reviewed image rebuilds.
Optional vendor-installed agents may have an independent persisted version. Their
installers and state remain scoped to their own agent service.

A broken optional agent must not make the launcher or Codex service unhealthy.
Health checks validate local role readiness without requiring credentials or a
successful vendor-service request.

## Migration from the Codex-only App

The migration implemented by issue #25 must:

- preserve the existing Codex workspace and credential data;
- avoid deleting or silently copying authentication state;
- map existing Codex paths only into the new Codex service;
- keep temporary compatibility names only when they call the canonical runtime;
- document rollback to the previous Codex-only deployment;
- avoid exposing Codex state to the launcher or future agent services.

The current `codex-remote-dev` package name may remain temporarily as a
compatibility tag pointing to the same digest. Its lifetime and the canonical
final image name are decided in the implementation PR.

## Validation contract

Before the architecture is advertised as implemented, automated and manual tests
must prove that:

- one stack deploys on generic Compose and TrueNAS;
- all services reference the same image ID or digest;
- the primary URL reaches the launcher and selecting Codex navigates or redirects
  to the authenticated Codex endpoint;
- launcher refresh and reconnect preserve the correct agent session;
- synthetic agent services cannot read one another's canary files;
- the launcher cannot read any agent canary, credential mount or workspace;
- the default launcher does not receive agent terminal traffic;
- invalid roles fail deterministically;
- current Codex login, start, resume, diagnostics and persistence still work;
- existing Codex data migrates without deletion or accidental sharing.

## Non-goals

This architecture does not include:

- a virtual-machine distribution;
- several agents running inside one agent container;
- one manually maintained TrueNAS App per agent;
- shared OAuth or token files between agents;
- dynamic privileged child containers;
- concurrent writes by several agents to one checkout by default;
- weakening TrueNAS or Docker security to force an inner sandbox;
- shipping Claude Code before a dedicated implementation and validation path.
