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
- Public experimental `edge` images with commit-addressed `sha-...` tags and published digests for reproducible testing.
- CodeRabbit configuration focused on Dockerfiles, Bash, GitHub Actions, Compose and security-sensitive changes.

### Changed

- Migrated the effective base image from Ubuntu 24.04 to Ubuntu 26.04 LTS.
- Updated maintained GitHub Actions to their current major releases.
- Changed the edge channel from private validation to public experimental development testing.
- Updated project documentation to state clearly that no stable release exists yet.

### Security

- Web authentication is required by default.
- The supported Compose configuration avoids privileged mode, host networking and the Docker socket.
- Image startup and publication fail when repository version pins are inconsistent.
- Public availability does not change the warning against exposing the ttyd port directly to the Internet.

## Release policy

- `edge` images are public experimental builds published manually from the current `main` branch.
- Stable images require an exact `vMAJOR.MINOR.PATCH` tag.
- The first stable section will replace relevant entries from `Unreleased` when `v0.1.0` is prepared.

[Unreleased]: https://github.com/eXPerience83/remote-dev-containers/commits/main
