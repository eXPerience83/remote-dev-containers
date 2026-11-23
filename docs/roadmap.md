# Roadmap

**Current published stable:** [v0.3.0](https://github.com/eXPerience83/remote-dev-containers/releases/tag/v0.3.0) (2026-11-22; exact release/support outcome in [#346](https://github.com/eXPerience83/remote-dev-containers/issues/346)). Next two *planned, not yet implemented* releases: **v0.4.0 [#366](https://github.com/eXPerience83/remote-dev-containers/issues/366)**, then **v0.5.0 [#367](https://github.com/eXPerience83/remote-dev-containers/issues/367)**.

This document is the high-level plan. Per-feature issues own design and acceptance; trackers #366 and #367 own release scope and exit gates. The older #31 contains historical release/support discussion; older checklists must not supersede the completed #346 outcome.

## Published baseline — v0.3.0

- **Published and accepted:** Git tag `v0.3.0` at source SHA `ad852d43ea978515ffd0cdf2c876130146e5c8bb`; the independent stable candidate passed its release gates. Scope: AMD64, single user and trusted LAN/private mesh.
- **Shipped:** Codex and optional experimental Antigravity with private role state, Context7 for both roles, Codex OpenAI Docs MCP, pinned Playwright MCP/Chromium Headless Shell, audited menu confirmation parity and an updated bilingual README with TrueNAS screenshots.
- **Acceptance boundary:** owner accepted Stable by functional equivalence to the already tested Edge because only documentation changed between that Edge and source tag. **No claim of deploying Stable's digest to production TrueNAS, executing a host rollback/restore, or proving the two OCI digests identical.** Refer to #346 for exact evidence.
- **Release policy:** source edits or a green Edge CI run do **not** authorize publishing/moving `stable`/`latest`. Stable requires the independent exact-candidate publication, explicit review and operator authorization described in `docs/releases.md`.

## Completed foundations

### Repository and supply-chain baseline

- Public repository, experimental GHCR package and pull-request workflow established.
- Apache-2.0 project licensing, third-party inventory/notices, SBOM generation and vulnerability scanning established.
- Immutable pins/provenance checks and bounded update ownership established.
- `dev -> edge -> stable = latest` release-channel contract implemented; `latest` is stable-only.
- Stable `v0.2.0` was followed by published and operator-accepted `v0.3.0` on 2026-11-22; every stable update has an independent exact-tag candidate build, smoke, notices, SPDX, vulnerability gate and digest verification. See #346.

### Codex AMD64 and outer-container isolation

- AMD64 image builds and public `edge` publication are established.
- Codex device-code authentication, GitHub CLI workflow, ttyd/tmux persistence and real TrueNAS lifecycle validation are complete for the current experimental stack.
- System Bubblewrap is not installed by default; the supported security boundary is the hardened outer role container plus narrow mounts.
- Autonomous/guarded Codex launch semantics are implemented under the current post-0.149 trust model.
- Explicit optional Codex runtime updates are implemented with the immutable bundled Codex CLI retained as fallback.

### Single-stack architecture

- One canonical `ghcr.io/experience83/remote-dev` image is reused by fixed-role services.
- Launcher, Codex and optional Antigravity run in separate containers from the same intended image reference.
- The launcher is navigation-only, password-free in the current supported private-network model and receives no agent workspace/state/password or container-engine socket.
- Role-private workspace, agent state, GitHub/Git/SSH state and runtime-installed vendor state remain isolated.
- `/workspace` is a role-private project collection root and normal agent Start/Resume resolves a concrete validated child project.
- Cross-service canaries and exact TrueNAS isolation/lifecycle validation are complete.

### Current TrueNAS YAML deployment

- `compose/truenas.yml` is the supported canonical TrueNAS Custom App path.
- One administrator-created root dataset plus ordinary role-private descendants is the normal layout.
- Deterministic bootstrap and preflight consume the same shared data-layout contract.
- Browser authentication applies to protected agent endpoints through separate configuration-backed `WEB_PASSWORD` entries for Codex and Antigravity; current validation requires only a non-empty single-line value and does not enforce minimum length, composition or cross-service uniqueness, so the operator may reuse the same value.
- The current launcher is not part of that password contract. Stronger single-entry/gateway authentication is intentionally deferred to #181.
- The former browser-password file/secret-tree design is gone.
- The reference Host Path ACL contract is Generic/POSIX, with host-side audit/migration guidance in `docs/truenas-acl-contract.md` and `.es.md`.
- Real migration/recreation/persistence/session validation for the current layout has completed.

### Optional Antigravity service

- Antigravity is implemented as an **optional experimental** role using Google's official `agy` runtime installed only by explicit user action into private persisted state.
- Vendor auto-update remains disabled in the supported session path.
- Hardened review-pending admission, explicit full verification and mandatory pre-launch integrity checking are implemented.
- Real project-scoped Start/Continue, useful conversation continuity, install/update, image rollback, persistence and isolation evidence are complete.
- Remote Dev exposes launch-scoped `autonomous|guarded` approval modes for Antigravity, defaulting to autonomous like Codex; Start and Continue share the same resolver and a one-launch menu override is consumed once.
- Guarded compatibility is diagnosed offline from Antigravity's own `settings.json`; `request-review` and `strict` are the supported Guarded provider presets, fine-grained permission rules remain user-managed, and an explicit preset selection changes only `toolPermission`. Other incompatible relevant settings are reported and left untouched; Start, Continue, status and Doctor remain read-only.
- The #53 human policy/terms disposition is recorded: Remote Dev may keep this official-CLI wrapper/container integration experimental, without claiming vendor approval or reusing Google/Antigravity OAuth in other agents/services.
- Scheduled #83 review automation is shipped: read-only static discovery executes no vendor code, while executable inspection remains an explicit trusted action.

### MCP integrations, browser and documentation

- Hosted Context7 MCP is optional and role-private for Codex and experimental Antigravity (#95 closed); real tool calls and persistence across Edge container recreation were verified.
- Optional device-code onboarding uses a reviewed transient `ctx7` CLI path and removes its vendor package/login/cache state afterwards. Hosted-service boundaries and terms are tracked in #53; Context7 is not redistributed in the image.
- Codex includes official OpenAI Docs MCP; pinned Playwright MCP + matching Chromium Headless Shell was accepted with security repair #320 and real MCP checks #355. This does not imply arbitrary project-owned Playwright E2E runtimes (#179).

## Pre-v0.4.0 gate — integral audit of v0.3.0 (mandatory)

**Audit: [#369](https://github.com/eXPerience83/remote-dev-containers/issues/369)**, verified baseline `main@be53c1bc1c747171134699a42d644246676ef44f` after the #370 maintenance metadata merge. The post-merge [Build AMD64](https://github.com/eXPerience83/remote-dev-containers/actions/runs/45267312044) and [Publish Edge](https://github.com/eXPerience83/remote-dev-containers/actions/runs/45267311885) passed; neither green workflow proves the findings below are fixed. The audit covers the existing v0.3.0 code **before** implementing the planned v0.4.0 features.

1. **[#371](https://github.com/eXPerience83/remote-dev-containers/issues/371) — P1 project deletion/data-loss protection (blocking):** prevent recursive project Delete from traversing nested mounts, including bind mounts on the same filesystem. The behavior was reproduced with synthetic data in an isolated mount namespace; production TrueNAS was not modified. Deliver a focused fix with pre-deletion guards, disposable-fixture regression tests, review and exact-HEAD CI **before new feature code**. `rm --one-file-system` alone is insufficient for same-device binds.
2. **[#372](https://github.com/eXPerience83/remote-dev-containers/issues/372) — P2 TrueNAS structural-parent ACL audit:** reproduce the diagnostic blind spot with fixtures, decide the correct owner/mode/effective-ACL checks for root/structural parents without treating intentional workspace `0755` as private-state leakage, then implement a read-only, testable repair **before exchange (#71) ACL/SMB implementation**. Never rewrite a populated dataset's permissions automatically.
3. **[#114](https://github.com/eXPerience83/remote-dev-containers/issues/114) — Codex runtime trust boundary:** decide whether manifest executable bits must match in both directions, add focused tests and explicitly document or repair same-owner TOCTOU limits. Do not claim an unverified cross-role or host compromise.
4. **[#369](https://github.com/eXPerience83/remote-dev-containers/issues/369) — audit closure:** record the evidence for each finding and a final **APTO / APTO CON RIESGOS CONOCIDOS / BLOQUEADO** verdict before starting #360 or #71. Reconcile [#357](https://github.com/eXPerience83/remote-dev-containers/issues/357) (menu parity #358 merged) as part of bounded housekeeping [#327](https://github.com/eXPerience83/remote-dev-containers/issues/327) unless evidence identifies a blocking regression.

This is an **audit/repair gate**, not a change in published stable version, a blanket rewrite or an expansion of the feature promises of v0.4.0. Compatibility UX [#157](https://github.com/eXPerience83/remote-dev-containers/issues/157) remains a distinct future improvement. Once cleared, keep the existing v0.4.0 order (#360, #71, #327, TrueNAS Edge acceptance, independent stable publication) and the planned v0.5.0 scope unchanged.

## Planned next — v0.4.0: shared file exchange + Chromium security

**Tracker: [#366](https://github.com/eXPerience83/remote-dev-containers/issues/366).** Start only after the #369 audit gate above clears. Priority is a safe new feature without changing existing project layout or weakening container isolation.

### Sequenced, separately reviewable PRs

1. **[#360](https://github.com/eXPerience83/remote-dev-containers/issues/360) — browser CVE awareness:** detect and report Chromium Headless Shell risks even if the `@playwright/mcp` version is unchanged. Correlate official evidence with the actual pinned MCP/Core/browser revision; fail visibly on unknown network/source status; never mix unofficial browser ZIPs or silently auto-promote.
2. **[#71](https://github.com/eXPerience83/remote-dev-containers/issues/71) — persistent `/exchange` folder:** introduce one shared path `${REMOTE_DEV_DATA_ROOT}/exchange`, mounted narrowly into enabled Codex and Antigravity services, optionally exported as SMB by TrueNAS itself. No agent SMB client/server, no project-folder shares, no parent root mount, no credentials in the share, and **no mount into the launcher**. Prefer an explicit backward-compatible opt-in; confirm exact Compose/bootstrap/preflight/ACL contract before coding so existing deployments do not fail for a missing bind source.
3. **[#327](https://github.com/eXPerience83/remote-dev-containers/issues/327) — bounded CI/code housekeeping and docs:** eliminate only demonstrably redundant paths without removing protections; reconcile already-merged menu parity PR #358 with open tracker #357. Bilingual operator instructions, changed-path manifests and rollback notes must accurately match the delivered feature.
4. **Edge + real TrueNAS acceptance:** record source/OCI digest; validate agent-to-agent handoff and read/write from authorized SMB client, filenames/ACLs, SMB disabled state, persistence after recreation, unaffected private workspaces/credentials and unchanged launcher/container security. Avoid unnecessary production resets and retain a known-working rollback reference.
5. **v0.4.0 source cut and independent stable promotion:** changelog, #53 distribution review when triggered, exact-head CI, smoke, notices, SPDX, Trivy/browser evidence, operator approval and verified promoted digests. No auto-tag or `latest` move merely from merging a feature PR.

**Explicitly deferred to v0.5.0:** web terminal/frontend/mobile controls #247/#97/#90/#91/#152/#87. A security fix may be expedited independently when risk warrants, without quietly expanding release scope.

## Planned following — v0.5.0: browser terminal and mobile UX

**Tracker: [#367](https://github.com/eXPerience83/remote-dev-containers/issues/367).** Do not assume a new ttyd client is necessary until the alternative is measured.

### Design gate and delivery sequence

1. **[#247](https://github.com/eXPerience83/remote-dev-containers/issues/247) — WeTTY research/prototype first.** Compare an exact stable WeTTY candidate with existing ttyd/tmux on auth, origin, maximum clients, role isolation, reconnection, `/copy` OSC 52, selection/paste, mobile UI, base path, licensing, image cost and TrueNAS lifecycle. Record an explicit go/no-go decision.
2. **[#97](https://github.com/eXPerience83/remote-dev-containers/issues/97) — frontend foundation, conditional.** If WeTTY does not pass, build one reproducible, pinned, project-owned `ttyd --index` client with compatibility tests. If WeTTY *does* pass, use a focused migration implementation instead and explicitly disposition/supersede the ttyd-specific foundation; **never maintain two clients for the same job**.
3. **[#90](https://github.com/eXPerience83/remote-dev-containers/issues/90) — mobile terminal keys:** Esc, Ctrl, Alt, Tab, arrows, Home/End, PgUp/PgDn, tested with Samsung Keyboard and Gboard, without breaking keyboard focus, modifier state, AltGr or terminal navigation.
4. **[#91](https://github.com/eXPerience83/remote-dev-containers/issues/91) — reliable terminal copy:** explicit selection Copy, browser-permission fallback and honest confirmation; preserve `Ctrl+C` interrupt, Unicode input and native Codex `/copy`/OSC 52 on existing supported clients.
5. **[#152](https://github.com/eXPerience83/remote-dev-containers/issues/152) — Android scrollback:** reproduce and identify owning layer (tmux/alternate screen/xterm/frontend/touch), repair retained-history reachability in Firefox Android and document Chrome Android limits where necessary.
6. **[#87](https://github.com/eXPerience83/remote-dev-containers/issues/87) + release acceptance:** replace provisional workarounds with tested bilingual browser/keyboard/clipboard matrix; source/lock/license review #53, exact-head CI, desktop Firefox/Chromium + Android Firefox/Chrome smoke, Codex/Antigravity/shell, TrueNAS Edge evidence, independent stable publication and owner sign-off.

**Constraint:** preserve terminal security, project/session persistence, private mounts and v0.4.0 exchange semantics; no public Internet exposure or unreviewed frontend dependencies.

## Ongoing maintenance

- Grouped upstream component refreshes remain owned by `check-upstream.yml`, with bounded provenance and human-reviewed PRs.
- Ubuntu/base-image and CI pin updates remain Renovate-owned; CI-only action changes are not claimed as bundled runtime upgrades.
- #53 remains the standing third-party licensing, vendor terms and privacy review log; revisit for a material new frontend or service boundary.
- Vulnerability scans and browser monitoring are complementary, not interchangeable. Green Trivy results do not prove a bundled Chromium ZIP is patched; #360 owns that gap.
- #93 scheduled Edge rebuild hardening and broader failure-injection/rollback checks remain separately tracked; do not claim they were completed solely because v0.3.0 was published.

## Deferred / separate roadmap

These issues do not block the planned v0.4.0 or v0.5.0 scope unless a newly identified critical security/regression issue demands a separately documented decision:

- #181 — private-mesh/HTTPS/auth-gateway improvements and stronger access identity; the supported baseline remains trusted private network.
- #170 — native TrueNAS Community App / ixVolumes research; current Custom App YAML remains canonical.
- #124 — role-scoped inbound SSH / remote clients.
- #112 — ARM64 support, distinct from presently supported AMD64.
- #179 — optional project-owned browser E2E toolchains (distinct from bundled Playwright MCP).
- #180 and #242 — project-scoped language toolchains and developer-environment contract.
- #148 — concurrent Codex sessions/worktrees.
- #151 — isolated agent container build/test without exposing the host Docker socket.
- #246 — code-server as a longer-term research option.
- Claude Code — only after a new provider/licensing/auth/isolation review.

Do not imply that a planned feature ships until its PR, real-world acceptance and stable publication gates are complete.
