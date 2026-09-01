# Remote Dev architecture

## Status

The accepted architecture is one user-installed Remote Dev stack, one immutable image digest and one isolated service per enabled coding agent.

Implemented:

- one canonical Remote Dev image/package;
- fixed `launcher`, `codex`, `antigravity` and `shell` runtime roles, with Antigravity still optional/experimental;
- one Compose/TrueNAS stack containing launcher, Codex and optional Antigravity services;
- one primary launcher URL;
- one image reference reused by enabled services;
- navigation from the stateless launcher to independently authenticated agent endpoints;
- one configuration-backed `WEB_PASSWORD` runtime contract for browser authentication;
- one canonical role-neutral persistent-data layout;
- one bounded role-neutral project resolver/manager below each private agent workspace mount;
- no agent-state mounts, agent credentials or Docker socket in the launcher.

Still pending or optional:

- final Antigravity support/policy/documentation reconciliation tracked by #31/#53/#69/#92/#96;
- optional TrueNAS SMB/ACL workspace integration under #71;
- future stronger private-network/HTTPS/auth-gateway access under #181;
- any reviewed one-origin reverse-proxy design.

Related work:

- issue #24 defines the architecture contract;
- issue #25 tracks the role-neutral runtime and launcher epic;
- issue #36 records the TrueNAS outer-isolation and no-Bubblewrap decision;
- issue #70 owns the canonical data layout;
- issue #167 owns deterministic bootstrap/preflight for the current TrueNAS YAML host layout;
- issue #126 defines `/workspace` as a role-private project collection root and the common project-scoped launch contract;
- issue #69 owns browser-terminal authentication;
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
├── launcher service     (primary port 7680, no password by default)
├── Codex service        (terminal port 7681, independently authenticated)
└── Antigravity service  (optional port 7682, independently authenticated)
```

All enabled services reference the same `REMOTE_DEV_IMAGE` value. Implemented roles are:

```text
REMOTE_DEV_ROLE=launcher|codex|antigravity|shell
```

`claude` remains reserved and unavailable.

## One launcher, isolated execution

The launcher provides the normal browser entry point and lists only reviewed services. Selecting an agent navigates to that service's own authenticated endpoint. The launcher does not execute the agent and does not relay terminal HTTP or WebSocket traffic.

The launcher:

- is a project-owned Python standard-library HTTP service;
- runs directly as UID/GID `65532` in the reviewed Compose profiles and restores no capabilities after `cap_drop: [ALL]`;
- requires no password by default in localhost/LAN/Tailscale examples;
- supports optional configuration-backed Basic authentication through `compose/launcher-auth.yml`;
- validates its fixed destination host, scheme, port and path;
- checks matching origins when an `Origin` header is present;
- sends a restrictive nonce-based Content Security Policy;
- accepts only `GET` and `HEAD`;
- exposes a secret-free health endpoint;
- receives no agent workspace, state, OAuth token, GitHub configuration, SSH key or Docker/Podman socket.

The base launcher deliberately uses `ALLOW_INSECURE_WEB=1` only for this navigation-only private-network profile. The optional launcher-auth override sets it to `0` and requires the launcher's independent password.

The launcher remains free of bind, persistent and agent-state mounts when optional authentication is enabled. It never receives an agent password or agent state.

Each agent endpoint uses its own `WEB_PASSWORD` value and authenticates independently. Credentials are never shared, embedded into the navigation URL or forwarded by the launcher. The external Compose variables that populate those per-service values remain distinct so changing one role does not change another. Reviewed agent profiles keep `ALLOW_INSECURE_WEB=0`; an insecure override is an explicit per-endpoint escape only for a separately protected private deployment.

## Shared immutable image

The final image contains Ubuntu and Remote Dev scripts, Git/Git LFS/OpenSSH/GitHub CLI, Python, Node.js, npm, uv, mise, ttyd, tmux, tini, the launcher runtime and Codex CLI as the built-in reference agent.

Sharing executable layers does not share mutable state or secrets. Runtime and Compose tests assert that enabled services use the same image reference/ID while retaining separate service boundaries.

## Service roles

### Launcher

`REMOTE_DEV_ROLE=launcher` accepts only the `menu` start mode. It does not initialize a workspace, GitHub configuration, Git configuration, SSH state, agent state or tmux session.

### Codex

Codex retains device-code authentication, start/resume actions, persistent tmux sessions, autonomous/guarded approval modes, diagnostics and post-session credential hardening. Start and Resume resolve a concrete project below `/workspace` and pass that directory through the project-owned `run-codex` wrapper, so repository discovery and repository-scoped instructions are not anchored accidentally at the collection root.

### Antigravity

Antigravity is an optional experimental role with its own workspace/state/configuration mounts. Its vendor runtime is installed explicitly into private persisted state and normal startup does not download or update it automatically. Project-scoped Start/Resume and lifecycle evidence are tracked independently from Codex support status.

### Shell

The shell role remains available for direct troubleshooting and uses ttyd/tmux without inspecting Codex-specific state. General shell mode opens at the role workspace collection root rather than requiring an active project.

### Optional agents

A proprietary optional agent may be installed or updated only through an explicit reviewed action using an official vendor-controlled source. Missing agents are reported as unavailable and are never downloaded during launcher or container startup.

## Project-scoped workspace contract

The host mount for an agent role is exposed inside that container as `/workspace`. That mount is a **project collection root**, not an implicit repository. A normal agent project is one validated immediate child:

```text
/workspace/
├── .remote-dev-tmp/          # hidden development scratch; never a project
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

Before an agent web/session boundary is created, a separate bounded helper prepares the fixed hidden scratch root and its `tmp`, `uv-cache`, `npm-cache` and `pip-cache` children. It uses descriptor-relative no-symlink checks, requires the current service UID/GID and applies mode `0700` to those fixed directories without recursively changing their contents. Normal child sessions receive this disk-backed tree through generic temporary and package-cache variables. Its leading-dot name is naturally absent from direct-child discovery and is invalid under the project-name grammar, so selection, creation and deletion cannot treat it as a project. Launcher and Remote Dev-owned credential onboarding do not receive these defaults.

The interactive selection is transient to the current menu/tmux session. Direct `agent` mode may use `REMOTE_DEV_PROJECT=<name>`; without it, direct mode requires exactly one valid project. It never silently falls back to running an agent at `/workspace` when the project is ambiguous or missing.

Project selection is a working-directory and routing contract, not an intra-service access-control boundary. The entire role-private `/workspace` mount remains visible to processes in that agent container, so selecting one child does not isolate sibling projects. Filesystem isolation is provided by the outer container and its mount set; use separate services or mounts if stronger separation between projects is required.

This contract is shared code only. Codex and Antigravity continue to receive separate writable workspace mounts. The same logical repository should use separate clones or Git worktrees across agent services rather than one concurrently writable checkout.

## Canonical persistence boundaries

Generic Compose derives all persistent paths from one variable:

```text
REMOTE_DEV_DATA_ROOT
```

The canonical Codex administrative layout is:

```text
REMOTE_DEV_DATA_ROOT/
├── workspaces/
│   └── codex/
│       └── <project>/
└── state/
    └── codex/
        ├── agent/
        ├── runtime/
        ├── gh/
        ├── git/
        └── ssh/
```

Browser-terminal passwords are deployment configuration rather than persisted data files.

The Codex service receives only these child paths:

| Host child path | Container target |
|---|---|
| `workspaces/codex` | `/workspace` |
| `state/codex/agent` | `/root/.codex` |
| `state/codex/runtime` | `/root/.local/share/remote-dev/codex-runtime` |
| `state/codex/gh` | `/root/.config/gh` |
| `state/codex/git` | `/root/.config/git` |
| `state/codex/ssh` | `/root/.ssh` |

When the experimental Antigravity service is enabled, it receives a disjoint set of role-private children. In particular, `state/antigravity/config -> /root/.gemini/config` supplies project state below `projects/`, while `state/antigravity/vendor -> /root/.gemini/antigravity-cli` remains a separate vendor/settings boundary. Neither Codex nor the launcher receives either path, and `/root/.gemini` is never mounted wholesale.

The base launcher remains free of bind, persistent and agent-state mounts. The parent data root, `/root`, `/home`, `/mnt`, host root and container-engine sockets are never mounted wholesale.

`scripts/lib/data_layout.py` is the canonical host-side directory contract for bootstrap and validation. `scripts/init-data-layout.py` and `scripts/preflight-data-layout.py` both consume it instead of carrying independent path lists. The initializer requires the configured root to exist already, rejects symlink roots/intermediate components, creates only missing canonical descendants and applies initial modes only to paths it creates. Existing required paths are left untouched, including any descendant deliberately created by a TrueNAS administrator as a child-dataset mountpoint.

For the current TrueNAS YAML, the normal model is one administrator-created root dataset such as `/mnt/Pool1/remote-dev` plus ordinary directories below it. Additional child datasets are optional operator policy for boundaries such as snapshots, quotas or replication; they are not required by Remote Dev. Bootstrap never creates the root dataset, and neither bootstrap nor preflight creates browser-password files or a password `secrets/` tree.

Before deployment, run the initializer and then `scripts/preflight-data-layout.py` from the same source revision as the selected image/YAML. Preflight validates that every canonical persistent directory exists and that none is a symlink. Browser-password validation belongs to endpoint startup, not host-layout preflight. Compose bind mounts additionally request `create_host_path: false` as defense-in-depth, but the design does not rely on every Compose implementation enforcing that option.

There is no data-layout compatibility alias, automatic migration, copying, symlink or deletion. Existing experimental directories must be recreated or moved manually before deploying the new stack.

Optional SMB sharing is not part of this contract. If evaluated later under #71, it should target explicitly selected concrete project directories below the `workspaces` boundary rather than exposing the whole collection root by default; `state` must remain private.

## Workspace concurrency

The default stack does not mount one writable checkout into two agent services. Future multi-agent users should use separate clones or Git worktrees and coordinate branches normally.

## Security and trust boundaries

Each outer container is a separate boundary. Anyone with terminal/root access inside an agent service is trusted for the state mounted into that service. The launcher cannot see or authenticate to agent state because neither the state nor the agent password is mounted or copied there.

The stack does not require privileged mode, `SYS_ADMIN`, host PID/networking, unconfined security profiles, container-engine sockets or host-root mounts.

Both deployment definitions enforce the same outer-container hardening: read-only root filesystems, `no-new-privileges`, `cap_drop: [ALL]`, bounded private `/tmp` and `/run` tmpfs filesystems and PID ceilings of 64 for launcher and 1024 per agent. The launcher runs directly as UID/GID `65532` and restores no capabilities; Codex and Antigravity restore only `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `KILL`, `SETGID` and `SETUID` for role-private host-ownership compatibility, persistent-state hardening and bounded UID/GID 65534 candidate execution. The live isolation canary verifies the effective launcher identity with zero capabilities, exact configured agent capabilities, transient mounts, same image ID and distinct writable sources.

Project selection neither broadens nor narrows that container boundary. The project resolver accepts only validated direct children of the already-mounted role workspace, rejects symlink project entries, and never converts an editable project name into a shell fragment; the rest of that mounted workspace remains accessible inside the service.

## Versioning and updates

All stack services use the same image reference. The image-bundled Codex release remains the reviewed, tested fallback. Codex may also use a newer official release only after an explicit project-owned admission into its private `state/codex/runtime` mount; that optional runtime never replaces the bundled executable and normal startup performs no update network access. Other built-in components continue to be updated through reviewed image rebuilds, while vendor-installed agents keep independent persisted state only inside their own private service.

A broken optional agent must not make the launcher or Codex unhealthy. Healthchecks validate role readiness without requiring user login.

`ghcr.io/experience83/remote-dev` is the sole published runtime package. The legacy `CODEX_IMAGE` variable remains a configuration fallback through `v0.1.x`, but it should point to the canonical package; the old `codex-remote-dev` GHCR package is retired. Local compatibility tags may still use the old name without creating a registry package.

## Validation contract

Automated tests cover:

- fixed role/start-mode validation;
- bounded project-name/path validation, zero/one/multiple resolution, symlink exclusion and create/delete guards;
- selected-project Codex start/resume and direct-agent launch behavior;
- launcher optional authentication, origin policy, CSP and fixed navigation;
- launcher absence of agent mounts and container-engine sockets;
- one image reference across enabled services;
- exact role-scoped mount targets and canonical source suffixes;
- deterministic host bootstrap from an existing empty root for Codex-only and Codex+Antigravity layouts;
- bootstrap idempotency, existing-content/mode preservation and refusal of missing roots or symlink roots/intermediates;
- exact alignment between the shared host-layout contract and TrueNAS bind sources, including `state/codex/runtime`;
- host-side preflight rejection of missing or symlinked canonical paths;
- independent configuration-backed browser authentication, agent fail-closed missing-password behavior unless an endpoint explicitly opts into `ALLOW_INSECURE_WEB=1`, and the navigation-only launcher's reviewed private-network exception;
- absence of the retired password-file browser-auth contract and browser-password secret tree;
- absence of legacy data-root names and paths;
- role-aware health checks;
- existing Codex start, resume, policy, diagnostics, ttyd and tmux behavior.

Manual TrueNAS validation is performed after the related implementation slices are ready and includes same-revision bootstrap/preflight from an administrator-created root dataset, a second idempotent bootstrap run, persistence, sessions, credentials, project selection/create/delete safety, isolation and recreation. Windows/SMB testing remains separate under #71.

## Non-goals

This architecture does not include:

- a virtual-machine distribution;
- several agents in one agent container;
- one manually maintained TrueNAS App per agent;
- shared OAuth/token, web-password, GitHub, Git, SSH or workspace state between agents;
- dynamic privileged child containers;
- weakening TrueNAS/Docker security to force an inner sandbox;
- shipping Claude before dedicated legal, installation and isolation validation.
