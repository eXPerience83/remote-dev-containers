# Roadmap

## Milestone 0 — repository bootstrap

- Review image names and project name.
- Create the private GitHub repository.
- Keep it private until the first image is validated, licensed and documented.
- Copy this starter kit.
- Enable branch protection and GHCR.
- Confirm Apache-2.0 licensing and third-party notices.

## Milestone 1 — private AMD64 edge proof

- Publish private `edge` and immutable `sha-...` AMD64 images from `main`.
- Deploy an immutable edge image on TrueNAS.
- Measure compressed and unpacked sizes.
- Verify Python, Node, uv, GitHub CLI and ttyd.
- Verify browser access and reconnection through tmux.
- Verify Codex device-code login and persistence across container recreation.
- Verify GitHub login, `gh auth setup-git`, clone, push and PR creation.
- Record the tested image digest, source commit and rollback image.

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
- Complete the changelog, public repository metadata, topics and CodeRabbit configuration.
- Open issues for requested tools instead of expanding the image preemptively.

## Later

- Native ARM64 CI and testing.
- Optional persistent on-demand toolchains.
- Home Assistant helper pack.
- Antigravity child image, only after its legal and technical distribution model is confirmed.
