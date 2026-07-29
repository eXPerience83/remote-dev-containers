# Roadmap

The detailed dependency tracker is issue #31. This document summarizes the delivery milestones without replacing the issue-level acceptance criteria.

## Milestone 0 — repository bootstrap

- Create the public repository and experimental GHCR packages.
- Add pull-request review, branch protection and contribution guidance.
- Confirm Apache-2.0 licensing and complete third-party notices.
- Establish reproducible version pins, SBOMs, provenance and vulnerability scanning.

## Milestone 1 — Codex AMD64 edge proof

- Publish experimental `edge` and commit-addressed `sha-...` AMD64 images from `main`.
- Deploy the edge image on TrueNAS pinned by its published digest.
- Verify Python, Node, uv, GitHub CLI, ttyd and tmux.
- Verify Codex device-code login and persistence across container recreation.
- Verify GitHub login, `gh auth setup-git`, clone, push and PR creation.
- Record the tested image digest, source commit and rollback image.

Codex remains the stable reference implementation while later milestones are developed.

## Milestone 2 — architecture and outer-isolation contract

- Record the one-App, one-image, isolated-service architecture from issue #24.
- Define the TrueNAS outer-container trust boundary.
- Test an exact edge candidate without Bubblewrap before deciding whether to remove it.
- Do not enable deprecated Landlock or weaken TrueNAS/Docker security.
- Complete the bundled-component inventory and optional-agent distribution policy.

## Milestone 3 — neutral image and single-stack launcher

- Define one canonical final image and one Remote Dev App/Compose stack.
- Add a launcher or gateway as the primary browser entry point.
- Run Codex in its own isolated service from the same image digest.
- Keep the launcher free of agent credentials, workspaces and Docker socket access.
- Preserve migration and rollback from the current Codex-only deployment.
- Add cross-service and launcher-isolation canary tests.

## Milestone 4 — optional Antigravity service

- Add an explicit installer and updater using the official vendor source.
- Discover and persist the real executable, account and state paths.
- Run Antigravity in its own service using the same final image digest.
- Validate installation, individual/free login, tools, updates and rollback on TrueNAS.
- Keep Codex and Antigravity credentials, GitHub state, SSH keys and workspaces separate.

## Milestone 5 — first stable release

- Publish AMD64 images only.
- Complete TrueNAS and generic Docker Compose installation documentation.
- Publish update, migration and rollback instructions.
- Complete the changelog, repository metadata, topics, contribution guidance and third-party notices.
- Close all issues that block the support level claimed by the release.

## Later

- Native ARM64 CI and real-device testing.
- Optional persistent on-demand toolchains.
- Home Assistant helper pack.
- Context7 adaptation to isolated agent services.
- Claude Code implementation only after current licensing, installation, authentication and sandbox behavior are revalidated.
- Optional sandbox-enabled variants only if a reproducible non-privileged design or demonstrated community demand justifies them.
- A lightweight VM distribution only if the container architecture proves insufficient for a real supported requirement.
