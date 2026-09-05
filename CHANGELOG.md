# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once versioned releases begin.

## [Unreleased]

### Automated upstream refreshes

<!-- remote-dev-upstream-refreshes -->

- 2026-09-05 — Codex CLI 0.153.2 → 0.153.4; uv 0.12.9 → 0.12.10; Context7 CLI (transient) 0.5.9 → 0.5.10.

- 2026-09-04 — Codex CLI 0.152.1 → 0.153.2; GitHub CLI 2.99.0 → 2.100.0; mise 2026.9.0 → 2026.9.1; Context7 CLI (transient) 0.5.8 → 0.5.9.

### Renovate image refreshes

<!-- remote-dev-renovate-runtime-refreshes:start -->
<!-- remote-dev-renovate-ubuntu: datasource=docker depName=ubuntu versioning=ubuntu UBUNTU_VERSION=26.04 UBUNTU_DIGEST=sha256:2260313b31c8c011cd2eebe728008efac1b3982be73eb71348ea2648d2c0e09b -->
<!-- remote-dev-renovate-runtime-refreshes:end -->

### Added

- Weekly exact-digest vulnerability rescanning for published AMD64 edge images with fresh Trivy evidence, bounded 30-day reports, a deduplicated automation-owned alert for fixable `CRITICAL` findings, fail-closed report validation and split scan/issue-write permissions; image rebuilding and promotion remain separate under #93.
- Human-readable edge build identities in `edge-YYYY.MM.DD-<7-char-sha>` form, backed by the existing full source revision/digest and an explicit embedded `local|dev|edge|stable` image-channel field.
- Bounded automated upstream changelog provenance that records only actual tracked component version deltas inside the automation-owned Unreleased section while preserving human-authored changelog text.
- Deterministic Renovate-owned Ubuntu base-image changelog provenance in a separate bounded Unreleased block; Ubuntu tag/digest changes advance one machine-owned state anchor in the same human-reviewed PR, while CI-only GitHub Action/frontend pin maintenance is not mislabeled as a bundled runtime update.
- Scheduled Antigravity review automation that discovers the current official installer/payload pair from bounded fixed-origin bytes as data without executing vendor code, records changed pairs as metadata-only review state and keeps executable inspection behind the explicit trusted review workflow.
- Bounded, write-only OSC 52 handling for native Codex `/copy`, served through ttyd 1.7.7's supported `--index` path with deterministic upstream-baseline, provenance, notice and SPDX checks.
- Shared remote-development base built on Ubuntu 26.04 LTS.
- Browser-accessible Codex CLI environment using ttyd and persistent tmux sessions.
- Git, Git LFS, OpenSSH client and GitHub CLI.
- Python 3.14, Node.js 24 LTS, npm 12, uv and mise.
- Separate persistent paths for workspaces and Codex, GitHub, Git and SSH configuration.
- AMD64 build, configuration validation and runtime smoke tests.
- Verification that the effective Ubuntu and Codex release pins match their Dockerfile defaults.
- Secure-by-default agent-terminal web startup guard requiring authentication unless explicitly overridden.
- SBOM and provenance generation in image publication workflows.
- Renovate dependency tracking, including grouped Ubuntu LTS base updates and immutable GitHub Action pins.
- Public experimental `edge` images with commit-addressed `sha-...` tags and published digests for reproducible testing.
- Explicit owner-authorized `dev` / `dev-amd64` image channel for reviewed pre-merge PR candidates, while preserving candidate-specific tags and immutable digests.
- Bounded release-channel validation that keeps `dev`, `edge`, `stable` and `latest` publication sources and tag promotion boundaries distinct.
- CodeRabbit configuration focused on Dockerfiles, Bash, Python launcher code, GitHub Actions, Compose and security-sensitive changes.
- Shared tmux mouse and scrollback configuration for browser terminals.
- Persistent credential permission hardening for Codex, GitHub CLI, Git and SSH state.
- Embedded image channel and source revision metadata exposed in the launcher, menu, diagnostics and `remote-dev-version`, together with the installed Codex CLI version reported at runtime.
- Trivy JSON reports for all critical findings in locally built images and exact publication candidates; only findings with a known fixed version fail the gate.
- Committed mise runtime configuration and lock data for Linux AMD64 and ARM64, plus validation and a documented regeneration helper.
- Accepted architecture contract for one user-installed App, one final image digest, one launcher and isolated per-agent services with private state.
- A single `run-codex` command launcher shared by menu, resume and direct-start paths so the supported TrueNAS policy cannot silently diverge.
- Canonical `start-remote-dev-web`, `remote-dev-menu`, `remote-dev-doctor` and role-aware healthcheck commands.
- Implemented fixed `REMOTE_DEV_ROLE=launcher|codex|antigravity|shell` resolution; Antigravity is optional/experimental and `claude` remains reserved/unimplemented.
- Validated `REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous|guarded`, one-launch menu/CLI overrides and diagnostics that report the effective upstream policy and its source.
- Canonical local image tags `remote-dev-base:local` and `remote-dev:local`, plus compatibility tags that are verified to share the same image IDs.
- Canonical GHCR package `ghcr.io/experience83/remote-dev`; edge, stable and PR-candidate publication use only this runtime package after exact-digest scanning.
- Compose regression tests for canonical defaults, legacy fallback, canonical precedence and empty-value handling across generic and TrueNAS files.
- Stateless `remote-dev-launcher` page with fixed navigation, a password-free current default, origin checking, nonce-based CSP, method restrictions and a secret-free health endpoint.
- Generic and TrueNAS stacks using the same image reference for the launcher on port 7680, Codex on port 7681 and optional experimental Antigravity on port 7682 while retaining disjoint mutable state.
- Existing `compose/launcher-auth.yml` advanced override for optional environment-backed launcher Basic authentication without adding a persistent credential mount; it is not part of the normal current deployment path.
- Automated launcher routing/isolation tests, launcher mount-boundary checks and runtime same-image-ID verification.
- Canonical `REMOTE_DEV_DATA_ROOT` layout with separate `workspaces` and per-role `state` boundaries.
- Host-side canonical data-layout preflight with regression tests for missing, symlinked or malformed persistent paths.
- Deterministic host-side data-layout bootstrap sharing one canonical path contract with preflight; it requires an existing administrative root, creates only missing role-private descendants, is idempotent, preserves existing paths/content/modes including deliberate TrueNAS child-dataset mountpoints, and creates no browser-password secrets tree.
- Read-only TrueNAS ACL audit plus English/Spanish Generic/POSIX private-state contract and NFSv4 migration/rollback guidance, validated on real TrueNAS data before the documentation synchronization.
- Static Compose regressions for exact role-scoped mount targets, the launcher's bind/persistent-mount boundary and removal of the earlier experimental data-root names.
- Antigravity conversation entry points using normal Start with in-TUI `/resume` for browsing older conversations and the vendor-supported `--continue` path for the latest conversation.
- Optional Codex-only Context7 integration using the external Upstash-hosted Streamable HTTP MCP endpoint, with explicit status/install-repair/test/update/remove actions, no bundled Context7 runtime, an owned marked config block, private optional API-key storage and English/Spanish user documentation.
- Optional Context7 device-code onboarding for Codex that transiently runs an exact published `ctx7` login flow, adopts only the resulting long-lived API key into the existing private Remote Dev state, and retains manual-key and anonymous fallbacks.
- Role-neutral project discovery and management below each private agent `/workspace`, including select/create/delete menu actions, exact-name destructive confirmation and bounded direct-mode selection through `REMOTE_DEV_PROJECT`.
- Bilingual TrueNAS SCALE YAML quick-start documentation plus a practical user guide for projects, Codex Resume exact-path behavior, browser/tmux controls, `AGENTS.md` verification, persistence and project-owned tooling.

### Changed

- Bumped the local development baseline from `0.1.0-dev` to `0.1.1-dev`. This does not create a stable release: edge publication keeps its dated `edge-YYYY.MM.DD-<short-sha>` identity and stable/latest remain reserved for an explicit SemVer release.
- Clarified the current browser-password policy: Codex and enabled Antigravity require only a non-empty single-line configured value unless an explicit reviewed insecure override is used; Remote Dev does not enforce minimum length, composition or cross-agent uniqueness, and the two agent configuration entries may intentionally reuse the same password pending a future browser-access/security decision.
- Clarified that the current launcher is a password-free navigation surface rather than the stack's central authentication boundary. Stronger single-entry launcher/gateway authentication remains future #181 work; the existing launcher-auth override is advanced/non-default and is not required for the normal deployment.
- Synchronized the public/project documentation with the implemented single-stack topology: Antigravity is an optional experimental official-CLI integration with completed #29/#96/#106/#131 technical evidence and recorded #53 policy disposition; agent browser authentication uses configuration-backed `WEB_PASSWORD`; the TrueNAS reference host layout is Generic/POSIX with the read-only ACL audit; #83 review automation and #189 Renovate provenance are shipped rather than future work.
- Edge publication now embeds the dated build identity as OCI/runtime version metadata while the mutable `edge` tags remain unchanged; `dev`, stable SemVer tags, `latest = stable`, full source SHA and immutable digest semantics are preserved.
- Grouped upstream-update PRs now add `CHANGELOG.md` to their deterministic tracked set and record exact old-to-new component version deltas; digest/notice-only refreshes do not create fake version entries.
- Standardized protected-agent browser authentication on one per-agent `WEB_PASSWORD` contract, retired the alternative password-file path and removed browser-password files from the persistent data layout/preflight; the launcher remains outside that current password contract.
- TrueNAS YAML first-install setup now starts from one administrator-created Generic/POSIX root dataset and uses same-revision bootstrap, preflight and host ACL audit instead of a hand-maintained `mkdir` list or mode-bit-only assumptions; ordinary descendants are the default while deliberate child datasets remain supported and untouched.
- Moved normal Codex and Antigravity temporary files and uv/npm/pip caches from the bounded `/tmp` tmpfs to a safely prepared hidden tree in each role-private disk-backed workspace, while preserving trusted staging and credential-environment boundaries.
- Updated the immutable bundled Codex baseline to `0.149.1` and migrated guarded mode from the retired `approval_policy=untrusted` value to launch-scoped untrusted trust for the active project, preserving the outer-container boundary and one-launch mode precedence.
- Made optional Codex runtime status and menu inspection lightweight and offline, added an offline full-SHA `verify` command, and made Codex diagnostics fail on full runtime-integrity errors. A newer optional runtime is still fully verified before launch; equal or older optional runtimes keep the bundled CLI without package hashing.
- Made informational Antigravity status and menu inspection lightweight and offline, added explicit full-SHA `verify`, and retained exactly one mandatory full verification before execution. Antigravity diagnostics now perform full verification and fail on integrity errors; damaged state still blocks launch without a bundled fallback.
- Migrated the effective base image from Ubuntu 24.04 to Ubuntu 26.04 LTS.
- Updated maintained GitHub Actions to their current major releases.
- Changed the edge channel from private validation to public experimental development testing.
- Defined the permanent image-channel hierarchy as `dev -> edge -> stable = latest`; `latest` now has an explicit contract as a stable-only alias and must never follow `edge` or `dev`.
- Updated project documentation to state clearly that no stable release exists yet.
- Changed the generic and TrueNAS Compose defaults to `ghcr.io/experience83/remote-dev:edge-amd64` through the canonical `REMOTE_DEV_IMAGE` variable.
- Retained `CODEX_IMAGE` as a lower-priority compatibility fallback throughout `v0.1.x`; it will not be removed before `v0.2.0`, but registry values should use the canonical `ghcr.io/experience83/remote-dev` package.
- Retired the legacy `ghcr.io/experience83/codex-remote-dev` GHCR package before the first stable release so publication maintains only `remote-dev-base` and the canonical `remote-dev` runtime package.
- Updated the pinned Codex CLI from `0.144.4` to stable `0.145.0`.
- Updated the reviewed stable toolchain to mise `2026.7.14`, Node.js `24.18.0` LTS, npm `12.0.1` and uv `0.11.32`; Python `3.14.6`, GitHub CLI `2.96.0` and ttyd `1.7.7` were already current.
- Changed stable upstream checks from weekly to daily and made the update branch reusable.
- Changed relevant merges to `main` to publish a new edge image automatically after required checks pass.
- Removed the system Bubblewrap package and executable from the default image because they cannot provide a nested namespace sandbox on the supported TrueNAS profile and must not be mistaken for an active security boundary. Codex's own packaged fallback is not used by the supported launcher.
- Changed Codex startup to disable the unsupported inner sandbox explicitly with `--sandbox danger-full-access` and use autonomous `never` approvals by default. Guarded mode now uses launch-scoped untrusted project trust under the post-0.149 Codex model.
- Changed diagnostics to report the fixed sandbox, project approval mode, exact upstream approval policy and selection source explicitly.
- Simplified the Codex menu to fixed start/resume actions plus a next-launch approval selector whose autonomous/guarded override is consumed once and then resets to the configured deployment mode.
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
- Changed local build and CI references from `codex-remote-dev*` to the canonical `remote-dev*` names while retaining local and variable compatibility aliases through `v0.1.x`.
- Changed all public runtime publication paths to use the canonical `remote-dev` package only; legacy package tags are no longer created.
- Changed the normal TrueNAS x-portal entry from the Codex terminal to the launcher while retaining the existing independently authenticated Codex port and data layout.
- Changed the image healthcheck from Codex-specific process checks to a fixed role-aware command.
- Changed the stateless launcher to remain password-free in the current localhost/LAN/Tailscale/private-mesh deployment model; the advanced launcher-auth override is retained but is not the normal security boundary.
- Replaced the Codex-specific persistent directory contract with one clean role-neutral administrative root. No data-path alias, migration script, automatic copy, deletion or compatibility symlink is provided.
- Changed all persistent bind mounts to long syntax with `create_host_path: false` as defense-in-depth and made the explicit host preflight authoritative because some Compose implementations may ignore that option.
- Moved the TrueNAS reference paths under `/mnt/Pool1/remote-dev`, separating Codex and Antigravity workspace and role-private state trees from browser authentication configuration.
- Kept optional SMB workspace integration and Windows/Git validation under #71 while moving the TrueNAS host private-state ACL contract to the completed Generic/POSIX audit/migration work under #186.
- Changed `/workspace` from an implicit repository working directory into a private project collection root; Codex and experimental Antigravity start/resume now resolve a concrete `/workspace/<project>` through the shared bounded resolver. Shell mode remains at the collection root.
- Changed successful project Select/Create actions to return directly to the calling Codex/Antigravity menu with the active project ready for Start/Resume/Continue, while Delete and recoverable invalid/failed/cancelled project actions remain in `Projects...`.
- Replaced Antigravity's menu-triggered prompt-text-dependent automatic `/resume` injection with a Codex-aligned two-action menu: Start opens the normal TUI and advertises in-TUI `/resume` for older conversations, while Continue latest uses the vendor-supported `--continue` path.

### Security

- Hardened launcher, Codex and experimental Antigravity outer containers with read-only root filesystems, `cap_drop: [ALL]`, exact role capability whitelists, private bounded `/tmp` and `/run` tmpfs mounts, explicit PID ceilings and live same-image isolation/toolchain assertions; `/tmp` remains `noexec`, while executable Codex update and Context7 staging remains bounded under transient `/run`.
- Reduced the launcher further after retiring file-backed browser secrets: production launcher containers now start directly as UID/GID `65532` with no added capabilities, while remaining free of bind, persistent, and agent-state mounts and under `no-new-privileges`.
- Added a narrow Antigravity-private `state/antigravity/config` bind at `/root/.gemini/config` so the official CLI can persist project configuration below `projects/` without making the read-only container root or all of `/root/.gemini` writable; host preflight, startup hardening and cross-service canaries enforce the separate boundary.
- Codex runtime update probes now use a fixed transient executable staging root under `/run`, verify its real execution capability before download, and normalize extracted package directories independently of restrictive umasks while ignoring caller-controlled `TMPDIR` and preserving the intentional `noexec` `/tmp` mount, UID/GID `65534` probes, synthetic credential-free state and immutable bundled fallback.
- Web authentication remains required by default for Codex and other protected agent terminals; the current stateless non-proxy launcher remains password-free on a trusted local/private network.
- The existing advanced launcher-auth override uses only launcher-specific environment configuration and adds no bind or persistent mounts; agent passwords never enter the launcher. It is not required by the normal deployment flow.
- The base launcher receives no agent workspace, Codex state, GitHub CLI state, Git configuration, SSH state, agent password or Docker socket.
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
- Public availability does not change the warning against exposing ports 7680, 7681 or 7682 directly to the Internet.
- Third-party GitHub Actions are pinned to immutable commit SHAs.
- The Ubuntu base image is pinned to an immutable OCI digest.
- Downloaded Codex, GitHub CLI, ttyd and mise assets are verified against repository-controlled architecture-specific SHA-256 values.
- Python, Node.js and uv install from committed artifact URLs and SHA-256 values in strict mise locked mode, with GitHub artifact attestations required where supported.
- Publication workflows scan exact pushed digests before promoting public tags; `remote-dev` runtime tags are verified against `REMOTE_DEV_DIGEST`, while `remote-dev-base` promotion metadata is checked separately against `BASE_DIGEST`.
- The parent Remote Dev data root is never mounted wholesale; each service receives only the specific child paths required by its role.
- The host bootstrap/preflight contract rejects missing roots, unsafe symlink ancestry and malformed persistent paths before deployment while preserving existing administrator-created paths rather than silently rewriting them.
- The TrueNAS host ACL audit rejects NFSv4/non-trivial or broadened private-state ACL conditions against the reviewed Generic/POSIX reference contract without mutating the filesystem; Doctor deliberately does not claim to infer host ACL type from inside the container.
- Agent credentials, GitHub state, Git configuration, SSH state and workspaces remain private per service.
- Project selection is a working-directory contract, not an intra-service filesystem sandbox: the full role-private `/workspace` mount remains accessible to processes in that agent container, including sibling projects.
- Project names/selectors are constrained to direct non-symlink children of the validated role workspace; create/delete cannot target arbitrary paths, and recursive deletion requires exact project-name confirmation.
- Remote Dev-managed Context7 API keys are kept out of Codex TOML, arguments and diagnostics, stored only in restrictive Codex-private state, and injected only into the Codex process for a healthy Remote Dev-managed integration; unmanaged Context7 configuration is never overwritten and passive lifecycle/status paths do not contact the external service.
- Context7 device login executes the pinned transient vendor CLI only after explicit user action in credential-minimized private state, disables npm lifecycle scripts and vendor telemetry, drops root execution to an unprivileged identity, validates the returned long-lived key before adoption, and removes the complete transient CLI/login/cache state afterward.
- Antigravity remains unbundled and experimental under the recorded #53 human support interpretation: Remote Dev uses only the official `agy` runtime path, does not implement an alternative Antigravity client or reuse Google/Antigravity OAuth for other agents/services, and does not present review evidence as vendor signing/certification/endorsement.
