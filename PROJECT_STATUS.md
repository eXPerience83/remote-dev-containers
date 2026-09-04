# Project status

> Current maturity: **active development / experimental**. Public `edge` images are for integrated testing and homelab use; Remote Dev has not published its first stable release yet.

## Locked foundations

- One user-installed Remote Dev App or Compose stack.
- One final Remote Dev image reference reused by isolated fixed-role services.
- One navigation-only launcher as the normal browser entry point.
- Separate Codex and optional Antigravity agent services with role-private mutable state.
- Ubuntu 26.04 LTS, AMD64 first.
- Root runtime inside agent services, constrained by the outer container and narrow mounts.
- GitHub CLI, Python 3.14, Node 24 LTS, npm 12, uv, mise, ttyd and tmux in the shared image.
- Image rebuild/update workflows for bundled components rather than broad in-container package mutation.
- `dev -> edge -> stable = latest` release-channel contract; immutable digest remains the strongest reproduction/rollback identity.

## Current implementation

```text
Remote Dev stack
├── launcher      7680 — password-free navigation only
├── codex         7681 — authenticated terminal
└── antigravity   7682 — optional/experimental authenticated terminal
```

- `ghcr.io/experience83/remote-dev` is the canonical runtime package and `REMOTE_DEV_IMAGE` is the preferred deployment selector.
- Launcher, Codex and enabled Antigravity services use the same intended image reference while keeping separate container, mount and credential boundaries.
- The launcher has no agent workspace/state/password, no Docker/Podman socket and no host-control credential. It navigates to agent endpoints rather than proxying terminal traffic and is deliberately password-free in the current supported private-network model.
- Codex is the bundled reference agent. The immutable image copy remains the fallback even when an explicitly admitted newer official Codex runtime exists in Codex-private state.
- Antigravity is implemented as an **optional experimental integration**. Google's `agy` runtime is not bundled or redistributed; installation/update is explicit, uses the reviewed official-source path, persists only in Antigravity-private state and keeps vendor automatic update disabled for supported sessions.
- The #29/#106/#131 Antigravity lifecycle, conversation continuity, project-scoped Start/Resume, update/rollback and isolation evidence is complete.
- The #96 technical admission model and #53 human terms/policy reconciliation are complete. The recorded project decision is to keep Antigravity experimental; this is a project risk/support interpretation, not Google approval, certification or endorsement.
- #83 scheduled Antigravity review automation is shipped. Scheduled discovery hashes/validates bounded vendor bytes as data without executing vendor code; a changed candidate requires the explicit trusted review workflow before executable evidence is admitted.
- Context7 for Codex and device-code onboarding are shipped as an optional hosted integration. The transient `ctx7` CLI used for explicit device login is not retained in the image or normal persistent runtime.

## Browser authentication and persistence

The current browser-password contract applies to protected **agent** endpoints through `WEB_PASSWORD`.

- Codex and Antigravity keep separate configuration entries so each endpoint can be changed independently.
- A protected agent endpoint currently requires a non-empty single-line value, but Remote Dev does **not** enforce minimum length, composition or cross-service uniqueness. The operator may intentionally reuse the same value across agents.
- The launcher is outside this password contract in the current supported design: it remains a password-free navigation surface on localhost/trusted LAN/private mesh.
- Stronger launcher/gateway authentication and a future single secure entry point remain explicit #181 work rather than a current requirement.
- The former browser-password file/mount/secret-tree mechanism is retired and must not be presented as supported.
- TrueNAS/Docker root/admin can inspect deployment configuration and is inside the trust boundary; the product does not claim secrecy from the host administrator.

Persistent data is rooted at one administrator-selected `REMOTE_DEV_DATA_ROOT` but only narrow role-private descendants are mounted into agent containers. Each `/workspace` is a private project collection root; normal Start/Resume/direct-agent paths resolve a concrete validated `/workspace/<project>`.

The current TrueNAS YAML path is deterministic:

- the operator creates one root dataset explicitly;
- the reference Host Path security contract uses **Generic/POSIX** for the root/private-state tree;
- `scripts/init-data-layout.py` creates only missing documented descendants from the shared data-layout contract;
- `scripts/preflight-data-layout.py` validates the same storage layout before deployment;
- `scripts/truenas-acl-audit.py` validates the TrueNAS Generic/POSIX private-state ACL contract without modifying data;
- no browser-password secret directory is created or required.

See `docs/truenas-acl-contract.md` for the ACL rationale, audit and migration guidance.

## Security boundary

Remote Dev is a single-user/homelab appliance, not a multi-tenant enterprise boundary.

- Agent root is constrained by the outer role container and its mounts.
- The default image does not install system Bubblewrap; supported Codex launches explicitly disable the unsupported inner sandbox.
- Launcher and agent services use read-only root filesystems, `no-new-privileges`, `cap_drop: [ALL]`, bounded tmpfs/PID controls and exact role-specific capability restoration where required.
- Cross-service isolation canaries and real TrueNAS validation for the current launcher/Codex/Antigravity topology are complete.
- Browser/SSH ports must not be exposed directly to the public Internet. Trusted LAN/Tailscale/private mesh is the normal deployment context; stronger access-security work remains tracked by #181.

## Release and update state

There is **no stable release yet**. The local development baseline is now `0.1.1-dev`; published edge images continue to use dated `edge-YYYY.MM.DD-<short-sha>` identities rather than that local default.

Current channel semantics are:

- `dev` / `dev-amd64` — explicitly published reviewed-but-unmerged candidate;
- `edge` / `edge-amd64` — integrated `main`;
- `stable` / `stable-amd64` — future explicit stable publication only;
- `latest` — exact alias of `stable`, never `dev` or `edge`.

Edge publications embed a human-readable `edge-YYYY.MM.DD-<short-sha>` identity plus a separate `Channel: edge`; full source SHA and image digest remain stronger provenance.

Upstream ownership is split deliberately:

- `.github/workflows/check-upstream.yml` owns the grouped bundled/runtime pins and its bounded `### Automated upstream refreshes` changelog provenance;
- Renovate owns immutable GitHub Action/frontend pins and the Ubuntu LTS tag/digest pair;
- Renovate-owned Ubuntu runtime-image changes update a separate bounded `### Renovate image refreshes` changelog section, while CI-only action pin changes are not mislabeled as bundled runtime upgrades;
- neither updater auto-merges dependency changes.

Exact mutable component versions remain authoritative in `versions.env` and runtime diagnostics rather than this status page.

## Remaining first-stable work

The main implementation foundations are already present. Before the first stable publication the repository still needs to satisfy the support level it actually claims, including:

- merge the #92 documentation synchronization and close the stale status gap;
- reconcile #31 so completed gates are no longer listed as pending and only real release blockers remain;
- pass the stable-release checklist in `docs/releases.md` on an exact `main` revision/digest;
- complete any open maintenance/security item that #31 identifies as blocking the claimed stable support level;
- create the dated stable changelog section and publish an exact SemVer release only after those gates pass.

Optional/future work such as #181 stronger browser access, #170 native Community App research, #124 inbound key-only SSH, #95 Context7 for Antigravity, #159 Antigravity autonomous mode, #71 SMB, #112 ARM64, #121 universal tooling, #148 concurrent sessions/worktrees and #151 isolated container build/test tooling does not become shipped merely because the core YAML deployment works.

## Upstream pin policy

The selected reviewed versions and architecture-specific immutable identities live in `versions.env` plus their validated generated/consumer files. Moving Python, Node or npm to a new major line requires explicit review. Ubuntu LTS tag/digest updates are Renovate-owned and must remain synchronized across the runtime pins and Renovate changelog state.

The Ubuntu base image, Dockerfile frontend, GitHub Actions and downloaded release assets use immutable digests or hashes where applicable. APT package resolution follows current security revisions in the selected Ubuntu repositories and is not claimed to be bit-for-bit reproducible without an APT snapshot service.

Every image-affecting change must continue to pass repository validation, AMD64 build/smoke tests, notices/SBOM checks and the fixable-`CRITICAL` vulnerability gate before publication or merge according to its workflow boundary.
