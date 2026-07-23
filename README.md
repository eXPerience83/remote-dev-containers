# Remote Dev Containers — starter v0.1

Community-maintained, browser-accessible Codex CLI development environment for Docker, NAS and homelab systems.

> Status: design and implementation starter. Not yet a published or security-audited stable image. Not affiliated with or endorsed by OpenAI.

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

## Private edge testing

The `edge` image is an unstable validation build published manually from `main`. It must be tested before any stable version tag is created.

For the generic Compose file, set:

```dotenv
CODEX_IMAGE=ghcr.io/experience83/codex-remote-dev:edge-amd64
```

The TrueNAS example accepts the same `CODEX_IMAGE` variable. Keep the repository and GHCR packages private during this phase.

For a reproducible deployment, prefer the immutable tag shown by the edge workflow:

```text
ghcr.io/experience83/codex-remote-dev:sha-<full-commit-sha>
```

See `docs/releases.md` for release channels, promotion criteria and rollback guidance.

## Important warnings

- Do not publish the terminal port directly to the Internet.
- Do not mount the Docker socket.
- Do not use privileged mode.
- Anyone with terminal access can read mounted repositories and credentials.
- `auth.json`, GitHub tokens and SSH keys are secrets.
- `edge` is not a stable release and may be replaced without notice.

## Documentation

- `CHANGELOG.md`
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
