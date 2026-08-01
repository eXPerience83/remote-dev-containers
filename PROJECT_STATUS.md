# Project status

> Current maturity: **active development / experimental**. Public access is intended for collaborative testing and review, not as a claim of production or stable-release readiness.

## Locked foundations

- One user-installed Remote Dev App or Compose stack
- One final image digest reused by isolated launcher and agent services
- One primary launcher URL
- Ubuntu 26.04 LTS
- Root runtime inside each agent service
- GitHub CLI essential
- Python 3.14, Node 24 LTS, npm 12, uv and mise
- ttyd + tmux browser-terminal experience per agent service
- AMD64 stable first
- Image rebuild/update workflow rather than in-container upgrades for built-in components

## Current implementation

- The public canonical edge package is `ghcr.io/experience83/remote-dev`; generic and TrueNAS Compose select it through `REMOTE_DEV_IMAGE`.
- The `codex-remote-dev` package and `CODEX_IMAGE` remain lower-priority compatibility aliases throughout `v0.1.x` and identify the same promoted edge/stable digest.
- Generic and TrueNAS Compose now start a `launcher` service on primary port 7680 and the existing isolated `codex` terminal service on port 7681 from the same image reference.
- The launcher uses fixed validated navigation, independent Basic authentication, origin checking and CSP; it does not proxy terminal traffic or mount Codex/GitHub/Git/SSH/workspace state.
- Codex keeps its existing service name, container name, `CODEX_DATA_ROOT` and mount layout until the dedicated migration slice.
- Implemented runtime roles are `launcher`, `codex` and `shell`; `antigravity` and `claude` remain reserved and unavailable.
- The default image omits the system Bubblewrap package. Codex is launched with its inner sandbox disabled explicitly, autonomous `never` approvals by default and guarded `untrusted` approvals as a deployment or one-launch option.

## Must validate before the first stable release

- Exact image size
- Ubuntu 26.04 package compatibility and build stability
- Codex binary release and digest resolution
- GitHub CLI checksum installation
- Launcher authentication, origin checking and browser navigation on real TrueNAS
- ttyd authentication, origin checking and tmux reconnection through the navigated Codex endpoint
- Both services using the exact published image digest on TrueNAS
- Autonomous and guarded Codex behavior under the documented outer-container isolation model
- Device-code login persistence
- GH login, credential helper, clone/push/PR
- TrueNAS x-portals behavior for the primary launcher
- Complete third-party licenses, SBOM and notices
- Migration from the Codex-only deployment without data loss or credential sharing
- Later launcher/agent and cross-agent synthetic canary tests

## Out of scope for v0.1

- Enabling Antigravity or Claude by default before their dedicated legal, installation and isolation validation
- Separate per-agent images or one manually maintained TrueNAS App per agent
- A reverse proxy that relays terminal traffic without a dedicated threat-model review
- ARM64 stable support
- Docker socket
- Browser automation
- Home Assistant-specific helper suite
- Office/VBA tools
- Multi-user service

## Upstream pin policy

The exact reviewed versions and architecture-specific SHA-256 values are maintained in `versions.env`, with synchronized Dockerfile defaults enforced by `scripts/validate-version-pins.sh`. Keeping the source of truth there avoids copying version numbers into status documentation that automated update pull requests could leave stale.

The update policy tracks final upstream releases for Codex, GitHub CLI, ttyd, mise and uv, plus maintenance releases within the selected Python 3.14, Node 24 LTS and npm 12 lines. Moving to a new Python, Node or npm major line requires explicit review. Ubuntu LTS tag and digest changes are managed by Renovate; npm remains part of the grouped upstream workflow so only one updater owns it.

The Ubuntu base image, Dockerfile frontend, GitHub Actions and downloaded release assets use immutable digests or hashes. APT package resolution follows the current security revisions in the selected Ubuntu repositories and is not claimed to be bit-for-bit reproducible without an APT snapshot service.

Every pin update must pass the automated AMD64 build, launcher/Codex runtime smoke tests and Trivy gate. Critical findings without a known fix remain visible in retained reports, while fixable `CRITICAL` findings fail the workflow. Real TrueNAS deployment, authentication, navigation, persistence and approval-mode validation remain required before the first stable release.
