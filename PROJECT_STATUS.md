# Project status

> Current maturity: **active development / experimental**. Public access is intended for collaborative testing and review, not as a claim of production or stable-release readiness.

## Locked

- Shared lightweight base plus Codex child
- Ubuntu 26.04 LTS
- Root runtime
- GitHub CLI essential
- Python 3.14, Node 24, uv and mise
- ttyd + tmux web experience
- AMD64 stable first
- Image rebuild/update workflow rather than in-container upgrades

## Must validate before the first stable release

- Exact image size
- Ubuntu 26.04 package compatibility and build stability
- Codex binary release and digest resolution
- GitHub CLI checksum installation
- ttyd authentication and origin checking
- mise installation of the pinned Python/Node/uv versions
- Codex sandbox behavior inside Docker
- Device-code login persistence
- GH login, credential helper, clone/push/PR
- TrueNAS x-portals behavior
- Complete third-party licenses, SBOM and notices

## Out of scope for v0.1

- Antigravity image
- ARM64 stable support
- Docker socket
- Browser automation
- Home Assistant-specific helper suite
- Office/VBA tools
- Multi-user service

## Initial upstream pins reviewed on 2026-07-23

- Ubuntu: `26.04` LTS
- Codex CLI: `rust-v0.144.4` stable
- Python: `3.14.6`
- Node.js: `24.17.0` LTS
- uv: `0.11.30`
- GitHub CLI: `2.96.0`
- ttyd: `1.7.7`
- mise: `2026.5.3`

These pins have passed the automated AMD64 build and smoke tests but remain subject to real TrueNAS deployment, authentication, persistence and sandbox validation.
