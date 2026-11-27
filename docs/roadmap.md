# Roadmap

**Current published stable:** [v0.3.1](https://github.com/eXPerience83/remote-dev-containers/releases/tag/v0.3.1) (2026-11-24; maintenance tracker [#377](https://github.com/eXPerience83/remote-dev-containers/issues/377)). Next planned feature releases: **v0.4.0 [#366](https://github.com/eXPerience83/remote-dev-containers/issues/366)**, then **v0.5.0 [#367](https://github.com/eXPerience83/remote-dev-containers/issues/367)**.

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

## Pre-v0.4.0 gate — integral audit and maintenance patch

The [#369 audit](https://github.com/eXPerience83/remote-dev-containers/issues/369) is closed with **APTO CON RIESGOS CONOCIDOS** at `main@163889c223014c0fd3137d9f92acdda9d37af8ba`. The reviewed fixes are #371 (shared project deletion protection), #372 (read-only TrueNAS structural ACL audit) and #114 (Codex runtime permission identity and trust boundary). Exact source Build and Edge publication passed. The operator supplied real TrueNAS startup/resume evidence and full integrity diagnostics for both optional runtimes; the exact release-cut host Generic/POSIX ACL audit passed and the local Edge image RepoDigest matched. This does not independently establish the exact running-container image IDs or deployment of the separately built Stable digest.

**v0.3.1 published:** independent stable publication and GitHub Release completed 2026-11-24. #377 remains open for explicit final Stable acceptance (exact deployed digest or operator-accepted functional equivalence); no re-release or new feature-development blocker inferred from tracker state.

Residual risks are recorded in #369 and #377. Menu-parity #358 is merged; #357 remains open for operational acceptance of the final menus. #327 closure audit at `3bb037c` found no justified further active refactor; independent Build/Edge and security gates remain intact. #157 remains separate compatibility UX. Next development is #380, then integral Edge acceptance and independent Stable publication. #360 is optional/manual; v0.5.0 scope remains unchanged.

## Planned next — v0.4.0: shared file exchange and maintenance

**Tracker: [#366](https://github.com/eXPerience83/remote-dev-containers/issues/366).** The #369 source audit and v0.3.1 publication prerequisites have completed. Priority is a safe new feature without changing existing project layout or weakening container isolation.

### Sequenced, separately reviewable PRs

1. **[#71](https://github.com/eXPerience83/remote-dev-containers/issues/71) — persistent `/exchange` folder (implementation merged via #385):** opt-in dedicated mounted filesystem at `${REMOTE_DEV_DATA_ROOT}/exchange`, mounted narrowly into enabled Codex and Antigravity roles, optionally exported as SMB by TrueNAS itself. OFF by default, no ordinary-directory fallback or automatic dataset/ACL creation, no agent SMB client/server, project-folder shares, parent root mount or credentials in the share, and **no mount into the launcher**. CI uses a dedicated ext4 fixture; real TrueNAS 27 (operator host 27.0.0-RC.1 at design time) and Windows SMB acceptance remain mandatory; keep #71 open.
2. **[#327](https://github.com/eXPerience83/remote-dev-containers/issues/327) — bounded CI/code housekeeping:** prior deduplication integrated, closure audit recommends no additional code optimization. Preserve independent builds, smoke, isolation and all security gates; occasional candidate-worker Trivy reuse deferred without measured benefit. #357 and #377 retain their distinct operational acceptance gates.
3. **[#380](https://github.com/eXPerience83/remote-dev-containers/issues/380) — owner-dispatched stable workflow:** retain exact-SHA, independent candidate and explicit promotion authorization gates.
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
- #386: Gitleaks PR scan and CodeQL are integrated and required alongside Build; historical sanitized baseline, missing native settings evidence and targeted Semgrep CE evaluation remain separate follow-up. No redundant scanners by default.
- #53 remains the standing third-party licensing, vendor terms and privacy review log; revisit for a material new frontend or service boundary.
- Green Trivy results do not prove a bundled Chromium ZIP is patched. #360 is deferred as an optional enhancement: manually review official Chromium/Playwright advisories before stable releases, on Playwright updates or serious advisories; keep the official MCP/Core/browser pairing. Do not add a separate monitor or daily transitive updater (#384).
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
