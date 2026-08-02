# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once versioned releases begin.

## [Unreleased]

### Added

- Shared remote-development base built on Ubuntu 26.04 LTS.
- Browser-accessible Codex CLI environment using ttyd and persistent tmux sessions.
- Git, Git LFS, OpenSSH client and GitHub CLI.
- Python 3.14, Node.js 24 LTS, npm 12, uv and mise.
- Separate persistent paths for workspaces and Codex, GitHub, Git and SSH configuration.
- AMD64 build, configuration validation and runtime smoke tests.
- Verification that the effective Ubuntu and Codex release pins match their Dockerfile defaults.
- Secure-by-default web startup guard requiring authentication unless explicitly overridden.
- SBOM and provenance generation in image publication workflows.
- Renovate dependency tracking, including grouped Ubuntu LTS base updates and immutable GitHub Action pins.
- Public experimental `edge` images with commit-addressed `sha-...` tags and published digests for reproducible testing.
- CodeRabbit configuration focused on Dockerfiles, Bash, Python launcher code, GitHub Actions, Compose and security-sensitive changes.
- Shared tmux mouse and scrollback configuration for browser terminals.
- Persistent credential permission hardening for Codex, GitHub CLI, Git and SSH state.
- Embedded image channel and source revision metadata exposed in the launcher, menu, diagnostics and `remote-dev-version`, together with the installed Codex CLI version reported at runtime.
- Trivy JSON reports for all critical findings in locally built images and exact publication candidates; only findings with a known fixed version fail the gate.
- Committed mise runtime configuration and lock data for Linux AMD64 and ARM64, plus validation and a documented regeneration helper.
- Accepted architecture contract for one user-installed App, one final image digest, one launcher and isolated per-agent services with private state.
- A single `run-codex` command launcher shared by menu, resume and direct-start paths so the supported TrueNAS policy cannot silently diverge.
- Canonical `start-remote-dev-web`, `remote-dev-menu`, `remote-dev-doctor` and role-aware healthcheck commands.
- Implemented fixed `REMOTE_DEV_ROLE=launcher|codex|shell` resolution with `antigravity` and `claude` reserved.
- Validated `REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous|guarded`, one-launch menu/CLI overrides and diagnostics that report the effective upstream policy and its source.
- Canonical local image tags `remote-dev-base:local` and `remote-dev:local`, plus compatibility tags that are verified to share the same image IDs.
- Canonical GHCR package `ghcr.io/experience83/remote-dev`; edge and stable tags are promoted from the same scanned digest as their `codex-remote-dev` compatibility tags, while PR candidates are canonical-only.
- Compose regression tests for canonical defaults, legacy fallback, canonical precedence and empty-value handling across generic and TrueNAS files.
- Stateless `remote-dev-launcher` page with fixed Codex navigation, optional Basic authentication, origin checking, nonce-based CSP, method restrictions and a secret-free health endpoint.
- Generic and TrueNAS two-service stacks using the same image reference for the primary launcher on port 7680 and the isolated Codex terminal on port 7681.
- Automated optional/authenticated launcher routing tests, launcher mount-boundary checks and runtime same-image-ID verification.

### Changed

- Migrated the effective base image from Ubuntu 24.04 to Ubuntu 26.04 LTS.
- Updated maintained GitHub Actions to their current major releases.
- Changed the edge channel from private validation to public experimental development testing.
- Updated project documentation to state clearly that no stable release exists yet.
- Changed the generic and TrueNAS Compose defaults to `ghcr.io/experience83/remote-dev:edge-amd64` through the canonical `REMOTE_DEV_IMAGE` variable.
- Retained `CODEX_IMAGE` as a lower-priority compatibility fallback throughout `v0.1.x`; it will not be removed before `v0.2.0`.
- Updated the pinned Codex CLI from `0.144.4` to stable `0.145.0`.
- Updated the reviewed stable toolchain to mise `2026.7.14`, Node.js `24.18.0` LTS, npm `12.0.1` and uv `0.11.32`; Python `3.14.6`, GitHub CLI `2.96.0` and ttyd `1.7.7` were already current.
- Changed stable upstream checks from weekly to daily and made the update branch reusable.
- Changed relevant merges to `main` to publish a new edge image automatically after required checks pass.
- Removed the system Bubblewrap package and executable from the default image because they cannot provide a nested namespace sandbox on the supported TrueNAS profile and must not be mistaken for an active security boundary. Codex's own packaged fallback is not used by the supported launcher.
- Changed Codex startup to disable the unsupported inner sandbox explicitly with `--sandbox danger-full-access` and use autonomous `never` approvals by default, while retaining guarded `untrusted` approvals as a validated option.
- Changed diagnostics to report the fixed sandbox, project approval mode, exact upstream approval policy and selection source explicitly.
- Bound displayed image identity to metadata embedded during the image build rather than runtime environment overrides.
- Changed upstream automation to update release versions and their architecture-specific SHA-256 pins together.
- Extended upstream automation to follow final Codex, GitHub CLI, ttyd, mise and uv releases, plus maintenance updates within the selected Python 3.14, Node 24 LTS and npm 12 lines; major runtime-line changes remain manual decisions.
- Assigned npm updates exclusively to the grouped upstream workflow to avoid competing Renovate pull requests.
- Added an official `SHA256SUMS` fallback for upstream releases such as ttyd that do not expose GitHub asset digest metadata.
- Centralized the fixable-critical Trivy gate so build, edge and stable workflows share the same enforcement logic.
- Extended upstream automation to regenerate and review the mise lock whenever runtime versions or resolved artifacts change.
- Updated the pinned stable releases to Codex CLI `0.146.0`, mise `2026.7.16` and uv `0.12.0`, and refreshed the locked Python 3.14.6 artifacts.
- Superseded the earlier separate child-image plan with a single-stack architecture that reuses one final image digest across fixed launcher and agent roles.
- Changed `start-codex-web`, `codex-menu` and `codex-doctor` into compatibility wrappers around the canonical role-neutral implementation while retaining legacy `START_MODE=menu|codex|shell` behavior.
- Limited persistent-state hardening for `REMOTE_DEV_ROLE=shell` to common GitHub, Git and SSH state so that the neutral shell role does not inspect or modify Codex state.
- Changed local build and CI references from `codex-remote-dev*` to the canonical `remote-dev*` names while retaining legacy aliases through `v0.1.x`.
- Changed PR candidate publication to use the canonical `remote-dev` package; edge and stable publication retain legacy package tags without rebuilding.
- Changed the normal TrueNAS x-portal entry from the Codex terminal to the launcher while retaining the existing independently authenticated Codex port and data layout.
- Changed the image healthcheck from Codex-specific process checks to a fixed role-aware command.
- Changed the stateless launcher to require no password by default on localhost/LAN/Tailscale deployments; optional Basic authentication remains available without affecting the independently authenticated Codex terminal.

### Security

- Web authentication remains required by default for Codex and other agent terminals; the stateless non-proxy launcher may be unauthenticated on a trusted local/private network.
- The launcher receives no agent workspace, Codex state, GitHub CLI state, Git configuration or SSH mounts and does not receive the Docker socket.
- The launcher never embeds or forwards terminal credentials and does not relay terminal HTTP/WebSocket traffic.
- The launcher validates routing inputs, checks matching origins when supplied, sends a restrictive CSP and rejects state-changing HTTP methods.
- The supported Compose configuration avoids privileged mode, host networking and the Docker socket.
- Image startup and publication fail when repository version pins are inconsistent.
- Codex stable release tags are validated to reject prerelease identifiers.
- Stable image publication also requires the tagged commit to belong to `main` history.
- Codex and GitHub credential files are tightened after startup, login and interactive sessions.
- Direct `START_MODE=codex` and `START_MODE=shell` sessions reapply credential hardening when their foreground process exits.
- Runtime tests keep `no-new-privileges`; they do not add `SYS_ADMIN`, privileged mode or unconfined security profiles to force a nested sandbox.
- The supported TrueNAS security boundary is each outer container; the inner Codex sandbox is disabled explicitly in both autonomous and guarded modes.
- Autonomous mode can act on all state mounted into Codex without confirmations; guarded prompts add friction but are not a sandbox or a substitute for narrow mounts.
- The Codex command launcher rejects arbitrary sandbox/approval flags, dangerous aliases, relevant config overrides and invalid project-owned mode values before Codex starts.
- Public availability does not change the warning against exposing ports 7680 or 7681 directly to the Internet.
- Third-party GitHub Actions are pinned to immutable commit SHAs.
- The Ubuntu base image is pinned to an immutable OCI digest.
- Downloaded Codex, GitHub CLI, ttyd and mise assets are verified against repository-controlled architecture-specific SHA-256 values.
- Python, Node.js and uv install from committed artifact URLs and SHA-256 values in strict mise locked mode, with GitHub artifact attestations required where supported.
- Publication workflows scan exact pushed digests before promoting public tags and verify that every canonical and compatibility edge/stable tag resolves to that digest.
