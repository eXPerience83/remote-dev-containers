# Project status

> Current maturity: **active development / experimental**. Public access is intended for collaborative testing and review, not as a claim of production or stable-release readiness.

## Locked

- Shared lightweight base plus Codex child
- Ubuntu 26.04 LTS
- Root runtime
- GitHub CLI essential
- Python 3.14, Node 24 LTS, npm 12, uv and mise
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

## Upstream pin policy

The exact reviewed versions and architecture-specific SHA-256 values are maintained in `versions.env`, with synchronized Dockerfile defaults enforced by `scripts/validate-version-pins.sh`. Keeping the source of truth there avoids copying version numbers into status documentation that automated update pull requests could leave stale.

The update policy tracks final upstream releases for Codex, GitHub CLI, ttyd, mise and uv, plus maintenance releases within the selected Python 3.14, Node 24 LTS and npm 12 lines. Moving to a new Python, Node or npm major line requires explicit review. Ubuntu LTS tag and digest changes are managed by Renovate; npm remains part of the grouped upstream workflow so only one updater owns it.

The Ubuntu base image, Dockerfile frontend, GitHub Actions and downloaded release assets use immutable digests or hashes. APT package resolution, including bubblewrap, deliberately follows the current security revisions in the selected Ubuntu repositories and is not claimed to be bit-for-bit reproducible without an APT snapshot service.

Every pin update must pass the automated AMD64 build, runtime smoke tests and Trivy gate. Critical findings without a known fix remain visible in retained reports, while fixable `CRITICAL` findings fail the workflow. Real TrueNAS deployment, authentication, persistence and sandbox validation remain required before the first stable release.
