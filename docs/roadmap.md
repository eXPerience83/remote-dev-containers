# Roadmap

The detailed release/support tracker is issue #31. This document summarizes delivery milestones without replacing issue-level acceptance criteria.

## Completed foundations

### Repository and supply-chain baseline

- Public repository, experimental GHCR package and pull-request workflow established.
- Apache-2.0 project licensing, third-party inventory/notices, SBOM generation and vulnerability scanning established.
- Immutable pins/provenance checks and bounded update ownership established.
- `dev -> edge -> stable = latest` release-channel contract implemented; `latest` is stable-only.

### Codex AMD64 and outer-container isolation

- AMD64 image builds and public `edge` publication are established.
- Codex device-code authentication, GitHub CLI workflow, ttyd/tmux persistence and real TrueNAS lifecycle validation are complete for the current experimental stack.
- System Bubblewrap is not installed by default; the supported security boundary is the hardened outer role container plus narrow mounts.
- Autonomous/guarded Codex launch semantics are implemented under the current post-0.149 trust model.
- Explicit optional Codex runtime updates are implemented with the immutable bundled Codex CLI retained as fallback.

### Single-stack architecture

- One canonical `ghcr.io/experience83/remote-dev` image is reused by fixed-role services.
- Launcher, Codex and optional Antigravity run in separate containers from the same intended image reference.
- The launcher is navigation-only and receives no agent workspace/state/password or container-engine socket.
- Role-private workspace, agent state, GitHub/Git/SSH state and runtime-installed vendor state remain isolated.
- `/workspace` is a role-private project collection root and normal agent Start/Resume resolves a concrete validated child project.
- Cross-service canaries and exact TrueNAS isolation/lifecycle validation are complete.

### Current TrueNAS YAML deployment

- `compose/truenas.yml` is the supported canonical TrueNAS Custom App path.
- One administrator-created root dataset plus ordinary role-private descendants is the normal layout.
- Deterministic bootstrap and preflight consume the same shared data-layout contract.
- Browser authentication uses independent configuration-backed `WEB_PASSWORD` values; the retired password-file/secrets-tree design is gone.
- The reference Host Path ACL contract is Generic/POSIX, with host-side audit/migration guidance in `docs/truenas-acl-contract.md` and `.es.md`.
- Real migration/recreation/persistence/session validation for the current layout has completed.

### Optional Antigravity service

- Antigravity is implemented as an **optional experimental** role using Google's official `agy` runtime installed only by explicit user action into private persisted state.
- Vendor auto-update remains disabled in the supported session path.
- Hardened review-pending admission, explicit full verification and mandatory pre-launch integrity checking are implemented.
- Real project-scoped Start/Resume, useful conversation continuity, install/update, image rollback, persistence and isolation evidence are complete.
- The #53 human policy/terms disposition is recorded: Remote Dev may keep this official-CLI wrapper/container integration experimental, without claiming vendor approval or reusing Google/Antigravity OAuth in other agents/services.
- Scheduled #83 review automation is shipped: read-only static discovery executes no vendor code, while executable inspection remains an explicit trusted action.

### Context7 for Codex

- Hosted Context7 MCP configuration is implemented for Codex.
- Optional device-code onboarding uses a reviewed transient `ctx7` CLI path and removes the vendor package/login/cache state afterwards.
- Hosted-service privacy/terms and credential boundaries are documented; Context7 remains outside the image SBOM/runtime bundle.

## Current milestone — first stable release preparation

Remote Dev still has no stable release. The current work is to make the public/support surface match the implementation and then run the exact stable-release gates.

1. **#92 — documentation synchronization.** Align README EN/ES, project status, roadmap, architecture/security/tool/release guidance and changelog with the implemented stack and final experimental Antigravity wording.
2. **#31 — tracker reconciliation.** Remove already completed gates from the pending lists and identify only blockers that genuinely remain for the support level claimed by the first stable release.
3. **Stable candidate validation.** Run the checklist in `docs/releases.md` on one exact `main` revision and immutable published digest, including image identity, TrueNAS deployment, authentication, persistence, isolation, notices/SBOM and vulnerability gates.
4. **Stable publication.** Only after the gates pass, create the dated changelog release section and exact `vMAJOR.MINOR.PATCH`; publish `stable` and `latest` as the same reviewed digest.

A normal integrated deployment remains on `edge-amd64` until that explicit stable publication exists.

## Ongoing maintenance

- Grouped upstream component refreshes remain owned by `check-upstream.yml`, with bounded changelog provenance and human-reviewed PRs.
- Ubuntu/base-image and CI pin updates remain Renovate-owned; Ubuntu runtime-image changes receive deterministic provenance while CI-only action changes are not presented as bundled runtime upgrades.
- #53 remains the standing legal/license/vendor-policy review log with routine and out-of-cycle triggers.
- Security/vulnerability refresh work remains governed by the dedicated maintenance issues and release gates; passing one earlier scan is never treated as permanent approval.

## Optional / future capabilities

These are not shipped by the current core contract unless their own issue says otherwise:

- #181 — stronger browser/remote-access security: private mesh/Tailscale, HTTPS, reviewed auth gateway, identity headers and passkeys/MFA.
- #170 — deferred native TrueNAS Community App/ixVolumes research; current YAML remains supported.
- #124 — optional role-scoped key-only inbound SSH/remote-client path.
- #95 — Context7 for Antigravity.
- #159 — optional Antigravity autonomous approval mode.
- #71 — optional SMB access to selected project paths only.
- #112 — ARM64.
- #121 — broader/universal developer tooling.
- #148 — concurrent sessions/worktrees.
- #151 — isolated container build/test tooling without a host Docker socket.
- #97/#90/#91/#152/#87 — frontend/mobile/browser-experience work.
- Claude Code — future dedicated implementation only after fresh licensing, installation, authentication and isolation review.

Optional sandbox-enabled variants or a VM distribution should be considered only if a reproducible non-privileged design or a demonstrated supported requirement justifies the added complexity.
