# Remote Dev Containers — starter v0.1

Community-maintained, browser-accessible coding-agent environment for Docker, NAS and homelab systems.

> [!WARNING]
> **Active development / experimental.** There is no stable release yet. Public `edge` images may change or break without notice. Do not expose either web port directly to the Internet. This project is not affiliated with or endorsed by OpenAI, Google or Anthropic.

## Goal

Keep development tools, repositories and coding agents on a remote Docker host so the personal computer only needs a browser.

## Current implementation

The current edge stack is the Codex reference implementation:

```text
Remote Dev stack
├── launcher  → primary browser port 7680
└── codex     → authenticated terminal port 7681
```

- one Remote Dev image reused by both services;
- stateless launcher with no password by default on trusted private networks;
- isolated, independently authenticated Codex terminal;
- Ubuntu 26.04 LTS;
- Git, Git LFS, OpenSSH and GitHub CLI;
- Python 3.14, Node 24, npm 12, uv and mise;
- ttyd browser terminal and persistent tmux sessions;
- canonical role-scoped persistent-data paths;
- AMD64 first.

Implemented runtime roles are:

```dotenv
REMOTE_DEV_ROLE=launcher
# or: codex
# or: shell
```

`antigravity` and `claude` remain reserved and unavailable. They never trigger an implicit download.

## Launcher and authentication

The launcher is navigation only. It does not proxy terminal traffic, use the Docker socket or receive agent workspaces, credentials or state. Selecting Codex navigates to the independently authenticated Codex endpoint.

Launcher Basic authentication is optional for advanced generic Compose deployments through `compose/launcher-auth.yml`. The normal TrueNAS/LAN example keeps the launcher password-free and requires authentication only on the Codex terminal.

## Codex approval modes

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# or: guarded
```

- `autonomous` maps to `--ask-for-approval never`;
- `guarded` maps to `--ask-for-approval untrusted`.

The menu provides separate start/resume actions and a next-launch selector. A one-launch override is consumed when Codex starts and then resets to the deployment value.

Approval prompts are not a sandbox. The supported isolation boundary is the outer Codex container and its narrow mounts. The project-owned launcher fixes the unsupported inner sandbox to `danger-full-access` on the validated TrueNAS profile.

## Canonical persistent-data layout

Generic Compose uses one administrative root:

```dotenv
REMOTE_DEV_DATA_ROOT=../data
```

Paths are resolved relative to `compose/docker-compose.yml`. The canonical layout is:

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

The Codex service mounts only the corresponding child paths. The launcher has no mounts. The parent data root, `/root`, `/home`, `/mnt`, host root and container-engine sockets are never mounted wholesale.

All bind mounts use `create_host_path: false`. Create every required directory deliberately before starting the stack; a typo fails instead of silently producing a new host directory.

There is no automatic migration or compatibility alias for the earlier experimental data layout. Move or recreate experimental state manually. Optional SMB/ACL workspace sharing is deferred to issue #71 and must never expose `state` or `secrets`.

## Licenses and optional vendor software

Remote Dev project code is Apache-2.0. Bundled upstream components retain their own licenses and notices. Inspect them with:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Antigravity, Claude Code and similar vendor products are not covered by the repository's Apache-2.0 license and are not downloaded or redistributed by the current image. Any future integration must use an explicit vendor-controlled installation path after dedicated legal and package inspection.

## Build locally

```bash
cp .env.example .env
mkdir -p \
  data/workspaces/codex \
  data/state/codex/{agent,gh,git,ssh} \
  data/secrets/codex
printf '%s\n' 'replace-with-a-codex-password' > data/secrets/codex/web_password.txt
chmod 600 data/secrets/codex/web_password.txt
./scripts/build-local.sh
```

Set `REMOTE_DEV_IMAGE=remote-dev:local` in `.env`, then run:

```bash
docker compose -f compose/docker-compose.yml up -d
```

Open port `7680`, select Codex and authenticate on port `7681`.

To protect the launcher in an advanced generic deployment:

```bash
mkdir -p secrets
printf '%s\n' 'replace-with-a-launcher-password' > secrets/launcher_password.txt
chmod 600 secrets/launcher_password.txt
docker compose \
  -f compose/docker-compose.yml \
  -f compose/launcher-auth.yml \
  up -d
```

The launcher password remains separate from every agent password.

## Public edge testing

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

Set:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

The `codex-remote-dev` package and `CODEX_IMAGE` remain image-name compatibility aliases during `v0.1.x`; they do not preserve the removed data layout.

For immutable reproduction, record the published digest and use:

```text
ghcr.io/experience83/remote-dev@sha256:<digest>
```

## Important warnings

- Do not publish ports 7680 or 7681 directly to the Internet.
- Bind the password-free launcher only to localhost, a trusted LAN or Tailscale/WireGuard.
- Keep the Codex terminal independently authenticated.
- Do not mount the Docker socket or use privileged mode.
- Do not mount agent state or credentials into the launcher.
- Autonomous mode can modify everything mounted into the Codex service without confirmation.
- `edge` remains experimental.

See `AGENTS.md`, `PROJECT_STATUS.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/security.md`, `docs/releases.md` and `docs/roadmap.md` for implementation and release details.
