# Remote Dev Containers — starter v0.1

Community-maintained, browser-accessible Codex CLI development environment for Docker, NAS and homelab systems.

> [!WARNING]
> **Active development / experimental.** There is no stable release yet. The public `edge` images may change or break without notice and have not completed the full TrueNAS, security or persistence validation checklist. Do not expose the web terminal directly to the Internet. This project is not affiliated with or endorsed by OpenAI.

## Goal

Keep development tools, repositories and Codex on a remote Docker host so the personal computer only needs a browser.

## Design

- Shared lightweight Ubuntu 26.04 LTS base
- Root runtime for predictable tool permissions
- Codex CLI from an official pinned release asset
- GitHub CLI as a core tool
- Python 3.14, Node 24, uv and mise
- Browser terminal through ttyd
- Persistent sessions through tmux
- Separate persistent volumes for workspace and credentials
- AMD64 first

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

The web menu shows the image channel, abbreviated source revision and Codex CLI version. To display the complete embedded metadata from the menu diagnostics or a shell, run:

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
- Anyone with terminal access can read mounted repositories and credentials.
- `auth.json`, GitHub tokens and SSH keys are secrets.
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
- `docs/architecture.md`
- `docs/tool-matrix.md`
- `docs/security.md`
- `docs/decisions.md`
- `docs/releases.md`
- `docs/roadmap.md`

## Upstream references

- OpenAI Codex: https://github.com/openai/codex
- Codex documentation: https://developers.openai.com/codex/cli
- GitHub CLI: https://github.com/cli/cli
- ttyd: https://github.com/tsl0922/ttyd
- mise: https://github.com/jdx/mise
