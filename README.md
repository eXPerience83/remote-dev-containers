# Remote Dev Containers — starter v0.1

Community-maintained, browser-accessible coding-agent environment for Docker, NAS and homelab systems.

> [!WARNING]
> **Active development / experimental.** There is no stable release yet. Public `edge` images may change or break without notice. Do not expose the launcher or agent terminals directly to the Internet. This project is not affiliated with or endorsed by OpenAI, Google or Anthropic.

## Goal

Keep development tools, repositories and coding agents on a remote Docker host so the personal computer only needs a browser.

## Current stack

One Remote Dev image is reused by three isolated services:

```text
Remote Dev App / Compose stack
├── launcher       → navigation, normally port 7680
├── codex          → authenticated terminal, normally port 7681
└── antigravity    → authenticated experimental terminal, normally port 7682
```

- The launcher is stateless navigation. It has no agent workspace, OAuth state, GitHub credentials, SSH keys or Docker socket.
- Codex and Antigravity run in separate containers with separate workspaces, GitHub CLI state, Git configuration, SSH state, tmux sessions and agent credentials.
- All services reuse the same final image reference/digest; Docker stores shared immutable layers once.
- Codex is included in the image from a pinned official OpenAI release.
- Antigravity is not redistributed. The Antigravity service contains only Remote Dev's installer/update/launch wrappers and metadata-only review evidence.
- The shared toolchain includes Ubuntu 26.04 LTS, GitHub CLI, Git/Git LFS, OpenSSH, Python 3.14, Node 24, npm, uv, mise, ttyd and tmux.
- AMD64 is the currently validated architecture for Antigravity.

## Roles and entrypoints

Canonical commands are:

- `start-remote-dev-web`;
- `remote-dev-launcher`;
- `remote-dev-menu`;
- `remote-dev-doctor`;
- `remote-dev-healthcheck`.

Implemented roles are:

```dotenv
REMOTE_DEV_ROLE=launcher
# or: codex
# or: antigravity
# or: shell
```

`start-codex-web`, `codex-menu` and `codex-doctor` remain compatibility wrappers. Unknown roles and start modes fail without evaluating editable shell fragments.

## Launcher and terminal authentication

The launcher is navigation only. On trusted localhost/LAN/Tailscale deployments it may run without Basic authentication while retaining origin checks, a restrictive Content Security Policy, path validation and method restrictions.

Codex and Antigravity terminals authenticate independently with different credentials. The launcher does not proxy ttyd HTTP/WebSocket traffic and never embeds or forwards terminal passwords.

An optional file-backed launcher-authentication override remains available for generic Compose deployments. It does not replace either agent terminal's password.

## Codex

Codex remains the built-in reference agent and guaranteed image fallback. The menu provides:

- Start Codex;
- Resume a Codex session;
- one-launch autonomous or guarded approval selection;
- device-code sign-in;
- GitHub CLI sign-in;
- diagnostics and shell access.

The deployment setting is:

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# or: guarded
```

- `autonomous` maps to `--ask-for-approval never`.
- `guarded` maps to `--ask-for-approval untrusted`.

Both modes use the outer container as the actual isolation boundary. Approval prompts are not a sandbox.

Codex currently updates through normal Remote Dev image releases. A separate planned feature will permit an explicit official OpenAI runtime update while retaining automatic fallback to the bundled executable. See `docs/agent-update-model.md`.

## Antigravity

Antigravity is an **experimental** optional integration. Google installer and CLI bytes are never committed to this repository or included in the public image/SBOM.

The Antigravity menu provides:

1. Start Antigravity.
2. Resume an Antigravity session through the full `/resume` picker.
3. Install Antigravity from Google.
4. Update Antigravity from Google.
5. Restore the previous locally retained version.
6. GitHub CLI sign-in, diagnostics and shell access.

### Installation and update model

Installation/update is always explicit. The canonical manager:

- downloads only from `https://antigravity.google/cli/install.sh`;
- requires HTTPS and rejects a final URL outside Google's fixed official HTTPS origin;
- stores the response in a private bounded file instead of piping it to Bash;
- validates the shell syntax and live `--dir <path>` contract in a credential-free home;
- installs into an Antigravity-owned staging directory;
- validates the resulting bounded Linux AMD64 ELF and its `--version`/`--help` behavior;
- records source, version, size and SHA-256 in a private local integrity manifest;
- publishes only after validation;
- preserves the active installation when an update fails;
- retains one previous validated local version for rollback.

Normal startup and agent launch never download or update Antigravity. Every launch verifies the executable against its local manifest and sets:

```text
AGY_CLI_DISABLE_AUTO_UPDATE=true
```

### Review status is not availability

Remote Dev distinguishes:

- `official, reviewed` — matches the latest committed inspection evidence;
- `official, review pending` — installed explicitly from the fixed Google endpoint and unchanged since installation, but newer/different than the current review snapshot;
- `official, review unavailable` — local integrity is valid but image review evidence cannot be read;
- damaged/locally modified — executable or manifest no longer matches and launch is blocked.

An ordinary Google version or hash change does not require a new Docker image before a user can install/update. A new image is required only if Google's installer/package contract changes beyond what the existing manager can safely validate.

See:

- `docs/agent-update-model.md`;
- `third_party/optional-agents.md`;
- `third_party/antigravity-cli-inspection.md`.

## TrueNAS isolation

The supported boundary is each outer container and its narrow mounts. Do not add privileged mode, `SYS_ADMIN`, unconfined profiles, broad home/root mounts or a Docker socket.

Do not run Codex and Antigravity concurrently against the same writable checkout. The supplied topology uses separate workspaces.

## Canonical persistent-data layout

Generic Compose uses one administrative root:

```dotenv
REMOTE_DEV_DATA_ROOT=../data
```

The complete stack layout is:

```text
REMOTE_DEV_DATA_ROOT/
├── workspaces/
│   ├── codex/
│   └── antigravity/
├── state/
│   ├── codex/
│   │   ├── agent/
│   │   ├── gh/
│   │   ├── git/
│   │   └── ssh/
│   └── antigravity/
│       ├── bin/
│       ├── runtime/
│       ├── vendor/
│       ├── gh/
│       ├── git/
│       └── ssh/
└── secrets/
    ├── codex/web_password.txt
    └── antigravity/web_password.txt
```

Home-mode TrueNAS may keep terminal passwords directly in the private App YAML using `WEB_PASSWORD`; generic/hardened deployments may use file-backed secrets. Never publish real values in issues, documentation or chat.

Run the host-side preflight before deployment. It rejects missing, malformed or symlinked paths and unsafe password files. Bind mounts use long syntax with `create_host_path: false` as defense in depth.

## Licenses and notices

Remote Dev project code is Apache-2.0. Bundled tools retain their upstream licenses and notices:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Antigravity, Claude Code and similar vendor products are not covered by the project licence. Antigravity is obtained directly from Google only after explicit user consent. Remote Dev does not claim redistribution rights or vendor affiliation.

## Build locally

```bash
cp .env.example .env
mkdir -p \
  data/workspaces/{codex,antigravity} \
  data/state/codex/{agent,gh,git,ssh} \
  data/state/antigravity/{bin,runtime,vendor,gh,git,ssh} \
  data/secrets/{codex,antigravity}
printf '%s\n' 'replace-with-a-codex-password' > data/secrets/codex/web_password.txt
printf '%s\n' 'replace-with-a-different-antigravity-password' > data/secrets/antigravity/web_password.txt
chmod 600 data/secrets/*/web_password.txt
make preflight
./scripts/build-local.sh
```

Enable the optional Antigravity Compose profile/configuration as documented by the deployment file, then start the stack with the same `REMOTE_DEV_IMAGE` reference for all services.

## Public edge testing

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

Set:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

Use a commit tag or immutable digest for reproduction/rollback:

```text
ghcr.io/experience83/remote-dev:sha-<full-commit-sha>
ghcr.io/experience83/remote-dev@sha256:<digest>
```

The menus and diagnostics display embedded image/source identity. `edge` remains mutable and experimental.

## Important warnings

- Do not expose ports 7680, 7681 or 7682 directly to the Internet.
- Keep launcher access limited to localhost, a trusted LAN or Tailscale unless a separately reviewed reverse proxy is used.
- Agent terminal authentication is mandatory.
- Anyone with terminal access can read the repositories and credentials mounted into that agent service.
- Do not share OAuth/token/GitHub/SSH state between agents.
- Do not mount the Docker socket or use privileged mode.
- Automatic Antigravity CLI updates remain disabled; use the explicit update action.
- A `review pending` version has not yet completed Remote Dev's human payload review.
- `edge` may be replaced without notice.

## Development and documentation

Development happens through focused pull requests. Read `AGENTS.md` and `CONTRIBUTING.md` before changing runtime/security behavior.

Key documents:

- `README.es.md`;
- `AGENTS.md`;
- `CHANGELOG.md`;
- `docs/agent-update-model.md`;
- `docs/architecture.md`;
- `docs/security.md`;
- `docs/tool-matrix.md`;
- `docs/truenas-antigravity-validation.md`;
- `third_party/optional-agents.md`;
- `third_party/antigravity-cli-inspection.md`.
