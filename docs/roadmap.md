# Roadmap

## Milestone 0 — repository bootstrap

- Review image names and project name.
- Create the GitHub repository.
- Make the repository and GHCR packages available as a clearly marked development preview.
- Add CodeRabbit configuration for pull-request reviews.
- Copy this starter kit.
- Enable branch protection and GHCR.
- Confirm Apache-2.0 licensing and third-party notices.

## Milestone 1 — AMD64 edge proof

- Publish experimental `edge` and immutable `sha-...` AMD64 images from `main`.
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
- Review CodeRabbit findings without treating AI review as a replacement for CI or manual testing.

## Milestone 3 — first stable release

- Publish AMD64 images only.
- Document TrueNAS and generic Docker Compose installation.
- Publish update and rollback instructions.
- Complete the changelog, repository metadata, topics, contribution guidance and third-party notices.
- Open issues for requested tools instead of expanding the image preemptively.

## Later

- Native ARM64 CI and testing.
- Optional persistent on-demand toolchains.
- Home Assistant helper pack.
- Antigravity child image, only after its legal and technical distribution model is confirmed.
