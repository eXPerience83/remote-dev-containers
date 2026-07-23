# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once versioned releases begin.

## [Unreleased]

### Added

- Shared remote-development base built on Ubuntu 26.04 LTS.
- Browser-accessible Codex CLI environment using ttyd and persistent tmux sessions.
- Git, Git LFS, OpenSSH client and GitHub CLI.
- Python 3.14, Node.js 24, npm, uv and mise.
- Separate persistent paths for workspaces and Codex, GitHub, Git and SSH configuration.
- AMD64 build, configuration validation and runtime smoke tests.
- Verification that the effective Ubuntu build pin matches the Dockerfile default and the resulting image.
- Secure-by-default web startup guard requiring authentication unless explicitly overridden.
- SBOM and provenance generation in image publication workflows.
- Renovate dependency tracking, including grouped Ubuntu LTS base updates.

### Changed

- Migrated the effective base image from Ubuntu 24.04 to Ubuntu 26.04 LTS.
- Updated maintained GitHub Actions to their current major releases.

### Security

- Web authentication is required by default.
- The supported Compose configuration avoids privileged mode, host networking and the Docker socket.
- Image startup and publication fail when repository version pins are inconsistent.

## Release policy

- `edge` images are manually published from the current `main` branch for private validation.
- Stable images require an exact `vMAJOR.MINOR.PATCH` tag.
- The first stable section will replace relevant entries from `Unreleased` when `v0.1.0` is prepared.

[Unreleased]: https://github.com/eXPerience83/remote-dev-containers/compare/HEAD...HEAD
