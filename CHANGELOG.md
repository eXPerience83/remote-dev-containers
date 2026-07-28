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
- CodeRabbit configuration focused on Dockerfiles, Bash, GitHub Actions, Compose and security-sensitive changes.
- Ubuntu `bubblewrap` package plus diagnostics for host-dependent nested-sandbox compatibility.
- Shared tmux mouse and scrollback configuration for browser terminals.
- Persistent credential permission hardening for Codex, GitHub CLI, Git and SSH state.
- Embedded image channel and source revision metadata exposed in the menu, diagnostics and `remote-dev-version`, together with the installed Codex CLI version reported at runtime.
- Trivy JSON reports for all critical findings in locally built images and exact publication candidates; only findings with a known fixed version fail the gate.
- Committed mise runtime configuration and lock data for Linux AMD64 and ARM64, plus validation and a documented regeneration helper.

### Changed

- Migrated the effective base image from Ubuntu 24.04 to Ubuntu 26.04 LTS.
- Updated maintained GitHub Actions to their current major releases.
- Changed the edge channel from private validation to public experimental development testing.
- Updated project documentation to state clearly that no stable release exists yet.
- Changed the generic and TrueNAS Compose defaults to the published `edge-amd64` image until the first stable release exists.
- Updated the pinned Codex CLI from `0.144.4` to stable `0.145.0`.
- Updated the reviewed stable toolchain to mise `2026.7.14`, Node.js `24.18.0` LTS, npm `12.0.1` and uv `0.11.32`; Python `3.14.6`, GitHub CLI `2.96.0` and ttyd `1.7.7` were already current.
- Changed stable upstream checks from weekly to daily and made the update branch reusable.
- Changed relevant merges to `main` to publish a new edge image automatically after required checks pass.
- Changed the bubblewrap runtime probe to report host namespace restrictions without weakening the container or failing unrelated image validation.
- Changed bubblewrap installation to follow Ubuntu's current repository security revision instead of an exact APT version that may disappear when superseded.
- Bound displayed image identity to metadata embedded during the image build rather than runtime environment overrides.
- Changed upstream automation to update release versions and their architecture-specific SHA-256 pins together.
- Extended upstream automation to follow final Codex, GitHub CLI, ttyd, mise and uv releases, plus maintenance updates within the selected Python 3.14, Node 24 LTS and npm 12 lines; major runtime-line changes remain manual decisions.
- Assigned npm updates exclusively to the grouped upstream workflow to avoid competing Renovate pull requests.
- Added an official `SHA256SUMS` fallback for upstream releases such as ttyd that do not expose GitHub asset digest metadata.
- Centralized the fixable-critical Trivy gate so build, edge and stable workflows share the same enforcement logic.
- Extended upstream automation to regenerate and review the mise lock whenever runtime versions or resolved artifacts change.

### Security

- Web authentication is required by default.
- The supported Compose configuration avoids privileged mode, host networking and the Docker socket.
- Image startup and publication fail when repository version pins are inconsistent.
- Codex stable release tags are validated to reject prerelease identifiers.
- Stable image publication also requires the tagged commit to belong to `main` history.
- Codex and GitHub credential files are tightened after startup, login and interactive sessions.
- Direct `START_MODE=codex` and `START_MODE=shell` sessions reapply credential hardening when their foreground process exits.
- Runtime tests keep `no-new-privileges`; they do not add `SYS_ADMIN`, privileged mode or an unconfined seccomp profile to force nested bubblewrap support.
- Public availability does not change the warning against exposing the ttyd port directly to the Internet.
- Third-party GitHub Actions are pinned to immutable commit SHAs.
- The Ubuntu base image is pinned to an immutable OCI digest.
- Downloaded Codex, GitHub CLI, ttyd and mise assets are verified against repository-controlled architecture-specific SHA-256 values.
- Python, Node.js and uv install from committed artifact URLs and SHA-256 values in strict mise locked mode, with GitHub artifact attestations required where supported.
- Publication workflows scan exact pushed digests before promoting public tags and use only the permissions required to read source and write packages.
