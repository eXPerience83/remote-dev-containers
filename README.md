# Remote Dev Containers — starter v0.1

Community-maintained, browser-accessible coding-agent environment for Docker, NAS and homelab systems.

> [!WARNING]
> **Active development / experimental.** There is no stable release yet. The public `edge` images may change or break without notice and have not completed the full TrueNAS, security or persistence validation checklist. Do not expose either web port directly to the Internet. This project is not affiliated with or endorsed by OpenAI, Google or Anthropic.

## Goal

Keep development tools, repositories and coding agents on a remote Docker host so the personal computer only needs a browser.

## Current implementation

The current edge stack is the Codex reference implementation:

- one Remote Dev image reused by the launcher and Codex services;
- one stateless launcher as the normal browser entry point, without authentication by default;
- one isolated, independently authenticated Codex terminal service with private role-scoped mounts;
- shared lightweight Ubuntu 26.04 LTS base;
- root runtime for predictable tool permissions;
- Codex CLI from an official pinned release asset;
- GitHub CLI as a core tool;
- Python 3.14, Node 24, uv and mise;
- browser terminal through ttyd;
- persistent sessions through tmux;
- one canonical role-neutral persistent-data contract;
- AMD64 first.

### Role-neutral entrypoints

The accepted single-stack architecture uses one canonical runtime implementation:

- `start-remote-dev-web`;
- `remote-dev-launcher`;
- `remote-dev-menu`;
- `remote-dev-doctor`;
- `remote-dev-healthcheck`.

`start-codex-web`, `codex-menu` and `codex-doctor` remain compatibility wrappers that select the Codex role and call the canonical commands.

Implemented roles are:

```dotenv
REMOTE_DEV_ROLE=launcher
# or: codex
# or: shell
```

`antigravity` and `claude` remain reserved and fail clearly because they are not implemented. They never trigger an implicit download.

The neutral direct-start selector accepts `menu`, `agent` or `shell` for agent-role services:

```dotenv
REMOTE_DEV_START_MODE=menu
```

The launcher accepts only `menu`. The existing `START_MODE=menu|codex|shell` setting remains compatible for Codex and shell deployments; legacy `codex` maps to neutral `agent`. Unknown roles and modes are rejected without evaluating editable shell fragments.

### Single-stack launcher

The generic and TrueNAS Compose files start two services from the same `REMOTE_DEV_IMAGE` reference:

```text
Remote Dev stack
├── launcher  → primary browser port 7680
└── codex     → authenticated terminal port 7681
```

The launcher is navigation only and has no authentication by default. It checks same-origin requests when an `Origin` header is present and applies a restrictive Content Security Policy. It shows the embedded image/source identity and one fixed link for the built-in Codex service.

Selecting Codex navigates the browser to the Codex service. The launcher does **not** proxy or relay ttyd HTTP/WebSocket traffic, does not use the Docker socket and receives no Codex workspace, agent state, GitHub configuration, Git configuration, SSH mounts or Codex terminal password.

The Codex endpoint authenticates independently with its own password source. Credentials are not embedded in the link, passed through the launcher or shared between services.

Launcher Basic authentication remains optional for advanced generic Compose deployments through the separate file-backed `compose/launcher-auth.yml` override. The normal TrueNAS home/LAN example does not require a second password, secret, mount or launcher dataset.

Configured launcher and Codex paths are restricted to safe URL-path characters before they are placed into the page. Antigravity/Claude services and a one-origin reverse proxy remain outside the current implementation.

### Codex approval modes

Codex always runs through the project-owned command launcher with the unsupported inner sandbox disabled explicitly. The deployment can select one of two validated modes:

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# or: guarded
```

- `autonomous` is the default and maps to `--ask-for-approval never`.
- `guarded` maps to `--ask-for-approval untrusted`.

The menu has separate **Start Codex** and **Resume a Codex session** actions plus an **Approval mode for next launch** selector. That selector can keep the configured mode or choose autonomous/guarded for the next start or resume only. A one-launch override is consumed when Codex starts and the menu then returns automatically to the deployment setting. It never rewrites the permanent configuration.

The equivalent command-line interface is:

```bash
run-codex --approval-mode autonomous
run-codex --approval-mode guarded resume
run-codex --print-policy
```

A per-launch selection overrides the deployment value only for that process. Unknown values and raw Codex sandbox/approval overrides are rejected before Codex starts. Arguments after `--` remain literal Codex/prompt arguments.

The upstream Codex TUI also exposes `/permissions`. That command changes the active upstream permission profile inside the running Codex process; it does not set `REMOTE_DEV_CODEX_APPROVAL_MODE` and does not replace Remote Dev's validated autonomous/guarded resolver. Use the Remote Dev menu or deployment variable for the supported default and next-launch behavior.

### Isolation on TrueNAS

The default image does not install the system Bubblewrap package. The supported Codex command launcher explicitly disables Codex's unsupported nested sandbox with `--sandbox danger-full-access`. Autonomous mode uses `--ask-for-approval never`; guarded mode uses `--ask-for-approval untrusted`. Every supported menu, resume and direct Codex path uses that same resolver.

Here, `danger-full-access` describes only the Codex inner sandbox. It does not grant Docker privileges or host access. The outer Docker container and its narrow mounts are the supported security boundary. Approval prompts are not a sandbox and do not protect files or credentials already mounted into the service.

Autonomous mode means Codex may read, modify or delete anything mounted into its service and may use credentials available there without asking first. It does not add access beyond the existing container mounts, network and credentials. Guarded mode adds confirmation friction but does not provide filesystem isolation.

Do not weaken the host or container with privileged mode, `SYS_ADMIN`, unconfined security profiles or a Docker socket to make a nested sandbox start. Mount only the paths that the selected service must access.

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

The Codex service mounts only the corresponding child paths. The base launcher has no mounts; the optional launcher-auth overlay adds only its own dedicated read-only password secret. The parent data root, `/root`, `/home`, `/mnt`, host root and container-engine sockets are never mounted wholesale.

All persistent bind mounts use `create_host_path: false`. Create every required directory deliberately before starting the stack; a typo fails instead of silently producing a new host directory.

There is no automatic migration or compatibility alias for the earlier experimental data layout. Move or recreate experimental state manually. Optional SMB/ACL workspace sharing is deferred to issue #71 and must never expose `state` or `secrets`.

## Licenses and optional vendor software

Remote Dev project code is Apache-2.0. Ubuntu, Codex CLI, GitHub CLI, ttyd, mise, Python, Node.js, npm, uv and their dependencies retain their respective upstream licenses and notices. The image preserves package-provided copyright files and copies the license files supplied by the exact installed runtime artifacts.

Inspect the reviewed inventory in `third_party/README.md`, or from a built image:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Antigravity, Claude Code and similar vendor products are not covered by this repository's Apache-2.0 license. They are not downloaded or redistributed by the current image. Any future optional installer must be initiated explicitly by the user, download directly from the vendor and follow the terms, privacy, credential-isolation and non-affiliation policy in `third_party/optional-agents.md`.

## Accepted target architecture

The target architecture is:

- one user-installed Remote Dev App or Compose stack;
- one final Remote Dev image digest reused by every service;
- one primary launcher URL;
- one isolated service per enabled coding agent;
- Codex as the built-in reference service;
- Antigravity as the first planned optional vendor-installed service;
- Claude Code preserved as a future path only;
- private workspaces, credentials, histories, GitHub state and SSH keys per agent service.

The current implementation delivers the launcher, Codex and canonical persistence portions of that topology. Docker reuses the same immutable image layers, and the launcher has no agent-state mounts or agent web credential. Optional agent services and the later cross-service hardening/canary phase remain tracked by issues #25 and #31.

The default launcher navigates to each agent's own authenticated endpoint and does not relay terminal traffic. Any future reverse proxy that terminates or relays that traffic is treated as a trusted transport component and requires a separate threat-model review.

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

Set `REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous` or `guarded` in `.env`, set `REMOTE_DEV_IMAGE=remote-dev:local`, and run:

```bash
docker compose -f compose/docker-compose.yml up -d
```

Open the launcher at published port `7680` and select Codex. The browser then opens the independently authenticated terminal on published port `7681`. Inside the Codex menu you can:

1. start Codex or resume a saved session with the configured deployment mode;
2. select autonomous or guarded for the next start/resume only;
3. use Codex device-code login;
4. use GitHub CLI login;
5. run diagnostics.

To protect the launcher itself in an advanced generic Compose deployment, create a separate launcher password file and add the reviewed override:

```bash
mkdir -p secrets
printf '%s\n' 'replace-with-a-launcher-password' > secrets/launcher_password.txt
chmod 600 secrets/launcher_password.txt
docker compose \
  -f compose/docker-compose.yml \
  -f compose/launcher-auth.yml \
  up -d
```

The override mounts that value as a Compose secret at `/run/secrets/launcher_password`; it does not place the password in the rendered service environment and it does not replace or reuse the Codex terminal password.

## Public edge testing

The `edge` image is an unstable development build published automatically after relevant changes merge into `main`. It is available publicly for testing, but it must not be treated as a stable release.

Pull the current AMD64 edge image without registry credentials:

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

For the generic or TrueNAS Compose file, set:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

Existing `v0.1.x` deployments may keep `CODEX_IMAGE` and `ghcr.io/experience83/codex-remote-dev`. `REMOTE_DEV_IMAGE` takes precedence when both variables are set, and both package names identify the same promoted edge/stable digest. The compatibility names will not be removed before `v0.2.0`; they do not preserve the removed experimental data layout.

For a source-commit-addressed deployment, use the `sha-...` tag shown by the edge workflow and package page:

```text
ghcr.io/experience83/remote-dev:sha-<full-commit-sha>
```

GHCR tags are mutable. For immutable reproduction or rollback, record the published digest and pin the image as:

```text
ghcr.io/experience83/remote-dev@sha256:<digest>
```

The launcher and terminal diagnostics show the embedded image channel and source revision. To display the complete embedded image metadata together with the runtime Codex CLI version from a Codex shell, run:

```bash
remote-dev-version
```

Expected edge output:

```text
Image version: edge
Source revision: <full-commit-sha>
Codex CLI: codex-cli <version>
```

See `docs/releases.md` for release channels, promotion criteria and rollback guidance.

## Important warnings

- Do not publish ports 7680 or 7681 directly to the Internet.
- The unauthenticated launcher should be bound only to localhost, a trusted LAN address or a Tailscale address.
- The Codex terminal remains independently authenticated.
- The launcher never embeds or forwards the terminal password.
- The launcher is navigation only and does not make the Codex terminal a same-origin application.
- Do not mount agent workspaces or credentials into the launcher.
- Do not mount the Docker socket.
- Do not use privileged mode.
- The default Codex command launcher disables the inner sandbox explicitly; the outer Codex container is the supported isolation boundary.
- Autonomous mode permits Codex to act on all state mounted into the Codex service without confirmations.
- Guarded prompts are not a sandbox and do not hide mounted files or credentials from Codex.
- Anyone with terminal access can read repositories and credentials mounted into that agent service.
- `auth.json`, GitHub tokens and SSH keys are secrets.
- Optional vendor agents are not bundled or covered by the project Apache-2.0 license.
- `edge` is experimental and may be replaced without notice.
- Breaking configuration and persistence changes are still possible before `v0.1.0`.

## Development and reviews

Development happens through pull requests. CodeRabbit is configured in `.coderabbit.yaml` to review Dockerfiles, Bash scripts, Python launcher code, GitHub Actions, Compose and security-sensitive changes. Its comments are advisory during the current development phase; passing CI and manual validation remain required.

Read `AGENTS.md` and `CONTRIBUTING.md` before proposing changes. Pull requests use the repository template, and GitHub requests review from the code owner when a non-draft pull request is ready for review.

## Documentation

- `AGENTS.md`
- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `PROJECT_STATUS.md`
- `third_party/README.md`
- `third_party/optional-agents.md`
- `docs/architecture.md`
- `docs/tool-matrix.md`
- `docs/security.md`
- `docs/decisions.md`
- `docs/releases.md`
- `docs/runtime-locks.md`
- `docs/roadmap.md`

## Upstream references

- OpenAI Codex: https://github.com/openai/codex
- Codex documentation: https://developers.openai.com/codex/cli
- GitHub CLI: https://github.com/cli/cli
- ttyd: https://github.com/tsl0922/ttyd
- mise: https://github.com/jdx/mise
