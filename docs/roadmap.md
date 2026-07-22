# Roadmap

## Milestone 0 — repository bootstrap

- Review image names and project name.
- Create the private GitHub repository.
- Keep it private until the first image is validated, licensed and documented.
- Copy this starter kit.
- Enable branch protection and GHCR.
- Confirm Apache-2.0 licensing and third-party notices.

## Milestone 1 — local AMD64 proof

- Build the shared base on TrueNAS or another AMD64 Docker host.
- Measure compressed and unpacked sizes.
- Verify Python, Node, uv, GitHub CLI and ttyd.
- Verify Codex device-code login and persistence.
- Verify GitHub login, `gh auth setup-git`, clone, push and PR creation.
- Verify browser reconnection through tmux.

## Milestone 2 — hardening

- Review ttyd basic-auth handling.
- Test origin checking and reverse-proxy base paths.
- Test Codex sandbox and approval behavior inside Docker.
- Generate SBOMs and provenance attestations.
- Add secret scanning, Dockerfile linting and vulnerability scanning.

## Milestone 3 — first public release

- Publish AMD64 images only.
- Document TrueNAS and generic Docker Compose installation.
- Publish update and rollback instructions.
- Open issues for requested tools instead of expanding the image preemptively.

## Later

- Native ARM64 CI and testing.
- Optional persistent on-demand toolchains.
- Home Assistant helper pack.
- Antigravity child image, only after its legal and technical distribution model is confirmed.
