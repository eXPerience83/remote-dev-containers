# Remote Dev Containers — starter v0.1

Community-maintained, browser-accessible Codex CLI development environment for Docker, NAS and homelab systems.

> [!WARNING]
> **Active development / experimental.** There is no stable release yet. The public `edge` images may change or break without notice and have not completed the full TrueNAS, security or persistence validation checklist. Do not expose the web terminal directly to the Internet. This project is not affiliated with or endorsed by OpenAI.

## Goal

Keep development tools, repositories and coding agents on a remote Docker host so the personal computer only needs a browser.

## Current implementation

The current edge image is the Codex reference implementation:

- shared lightweight Ubuntu 26.04 LTS base;
- root runtime for predictable tool permissions;
- Codex CLI from an official pinned release asset;
- GitHub CLI as a core tool;
- Python 3.14, Node 24, uv and mise;
- browser terminal through ttyd;
- persistent sessions through tmux;
- separate persistent paths for workspace and credentials;
- AMD64 first.

### Isolation on TrueNAS

The default image does not install the system Bubblewrap package. The supported launcher explicitly disables Codex's unsupported nested sandbox with `--sandbox danger-full-access` and uses `--ask-for-approval untrusted`. The menu, resume action and direct Codex start mode all use that same launcher.

Here, `danger-full-access` describes only the Codex inner sandbox. It does not grant Docker privileges or host access. The outer Docker container and its narrow mounts are the supported security boundary. Untrusted shell commands require approval, but approvals are not a sandbox and do not protect files or credentials already mounted into the service.

Do not weaken the host or container with privileged mode, `SYS_ADMIN`, unconfined security profiles or a Docker socket to make a nested sandbox start. Mount only the paths that the selected service must access.

## Licenses and optional vendor software

Remote Dev project code is Apache-2.0. Ubuntu, Codex CLI, GitHub CLI, ttyd, mise, Python, Node.js, npm, uv and their dependencies retain their respective upstream licenses and notices. The image preserves package-provided copyright files and copies the license files supplied by the exact installed runtime artifacts.

Inspect the reviewed inventory in `third_party/README.md`, or from a built image:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Antigravity, Claude Code and similar vendor products are not covered by this repository's Apache-2.0 license. They are not silently downloaded or redistributed by the current image. Any future optional installer must be initiated explicitly by the user, download directly from the vendor and follow the terms, privacy, credential-isolation and non-affiliation policy in `third_party/optional-agents.md`.

## Accepted target architecture

The next runtime architecture is documented before implementation:

- one user-installed Remote Dev App or Compose stack;
- one final Remote Dev image digest reused by every service;
- one primary launcher or gateway URL;
- one isolated service per enabled coding agent;
- Codex as the built-in reference service;
- Antigravity as the first planned optional vendor-installed service;
- Claude Code preserved as a future path only;
- private workspaces, credentials, histories, GitHub state and SSH keys per agent service.

Docker reuses the same immutable image layers. Users will not install one image or TrueNAS App per tool, and several agents will not share one container's private state.

The default launcher navigates or redirects to each agent's own authenticated endpoint and does not relay terminal traffic. Any future reverse proxy that terminates or relays that traffic is treated as a trusted transport component and requires a separate threat-model review.

This target is not yet implemented in the current edge image. See `docs/architecture.md`, issue #24 and implementation issue #25.

## Build locally

```bash
cp .env.example .env
mkdir -p secrets data/{workspace,codex,gh,git,ssh}
printf '%s\n' 'replace-with-a-long-password' > secrets/web_password.txt
chmod 600 secrets/web_password.txt
./scripts/build-local.sh
```

Then set `CODEX_IMAGE=codex-remote-dev:local` in `.env` and run:

```bash
docker compose -f compose/docker-compose.yml up -d
```

Open the published web address and choose:

1. Codex device-code login
2. GitHub CLI login
3. Diagnostics
4. Start Codex

## Public edge testing

The `edge` image is an unstable development build published automatically after relevant changes merge into `main`. It is available publicly for testing, but it must not be treated as a stable release.

Pull the current AMD64 edge image without registry credentials:

```bash
docker pull ghcr.io/experience83/codex-remote-dev:edge-amd64
```

For the generic or TrueNAS Compose file, set:

```dotenv
CODEX_IMAGE=ghcr.io/experience83/codex-remote-dev:edge-amd64
```

For a source-commit-addressed deployment, use the `sha-...` tag shown by the edge workflow and package page:

```text
ghcr.io/experience83/codex-remote-dev:sha-<full-commit-sha>
```

GHCR tags are mutable. For immutable reproduction or rollback, record the published digest and pin the image as:

```text
ghcr.io/experience83/codex-remote-dev@sha256:<digest>
```

The web menu shows the embedded image channel, abbreviated embedded source revision and installed Codex CLI version detected at runtime. To display the complete embedded image metadata together with the runtime Codex CLI version from the menu diagnostics or a shell, run:

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

- Do not publish the terminal port directly to the Internet.
- Do not mount the Docker socket.
- Do not use privileged mode.
- The default Codex launcher disables the inner sandbox explicitly; the outer container is the supported isolation boundary.
- Approval prompts are not a sandbox and do not hide mounted files or credentials from Codex.
- Anyone with terminal access can read repositories and credentials mounted into that service.
- `auth.json`, GitHub tokens and SSH keys are secrets.
- The current edge deployment is Codex-specific; the single-stack launcher is not implemented yet.
- Optional vendor agents are not bundled or covered by the project Apache-2.0 license.
- `edge` is experimental and may be replaced without notice.
- Breaking configuration and persistence changes are still possible before `v0.1.0`.

## Development and reviews

Development happens through pull requests. CodeRabbit is configured in `.coderabbit.yaml` to review Dockerfiles, Bash scripts, GitHub Actions, Compose files and security-sensitive changes. Its comments are advisory during the current development phase; passing CI and manual validation remain required.

Read `CONTRIBUTING.md` before proposing changes. Pull requests use the repository template, and GitHub requests review from the code owner when a non-draft pull request is ready for review.

## Documentation

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
