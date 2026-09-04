# Remote Dev Containers — starter v0.1.1-dev

Community-maintained, browser-accessible coding-agent environment for Docker, NAS and homelab systems.

> [!WARNING]
> **Active development / experimental.** There is no stable release yet. Public `edge` images are integrated development builds and may still change before the first stable release. Do not expose any Remote Dev web port directly to the Internet. This project is not affiliated with or endorsed by OpenAI, Google or Anthropic.

## Goal

Keep development tools, repositories and coding agents on a remote Docker host so the personal computer only needs a browser.

## Current implementation

```text
Remote Dev stack
├── launcher      7680 — password-free navigation only
├── codex         7681 — authenticated terminal
└── antigravity   7682 — optional/experimental authenticated terminal
```

Current foundations:

- one `ghcr.io/experience83/remote-dev` image reference reused by launcher, Codex and enabled Antigravity services;
- a stateless/navigation-only launcher with no agent workspace, state, password or Docker/Podman socket;
- an isolated Codex reference service with private role-scoped mounts;
- an optional isolated Antigravity service with private state and a vendor runtime installed only by explicit user action;
- Ubuntu 26.04 LTS, AMD64 first;
- Codex CLI from an official pinned release asset, plus an explicit optional official runtime path with the bundled CLI retained as fallback;
- GitHub CLI, Python 3.14, Node 24, npm, uv, mise, ttyd and tmux;
- one canonical role-neutral persistent-data contract;
- one configuration-backed `WEB_PASSWORD` browser-authentication runtime contract for protected agent endpoints, with separate Codex/Antigravity configuration entries; values may currently be reused across agents;
- project selection below each private `/workspace` collection root;
- `dev -> edge -> stable = latest` release semantics, with dated edge build identity separate from channel and immutable provenance.

## Install on TrueNAS SCALE

Use [`compose/truenas.yml`](compose/truenas.yml) as the **canonical TrueNAS Custom App YAML**. Do not maintain a copied stack definition in the README.

TrueNAS UI details may change between releases. The current upstream reference is the [TrueNAS Custom App documentation](https://www.truenas.com/docs/scale/apps/installcustomappscreens/).

### 1. Create the root dataset explicitly

Create one administrator-owned root dataset, for example:

```text
Pool1/remote-dev
```

normally exposed on the host as:

```text
/mnt/Pool1/remote-dev
```

For the reference Remote Dev Host Path security model, create/use this root as **Generic/POSIX**. Real TrueNAS validation showed that Apps-preset NFSv4 inheritance can leave additional effective host access even when simple mode output appears to be `0700`. See [`docs/truenas-acl-contract.md`](docs/truenas-acl-contract.md) before reusing an existing NFSv4 Apps-preset tree.

Only the root normally needs to be a ZFS dataset. `workspaces/` and `state/` descendants can be ordinary directories. Deliberate child datasets remain valid when an administrator wants a separate snapshot/quota/replication boundary.

The root must already exist. `scripts/init-data-layout.py` deliberately refuses to create a missing root, parent or ZFS dataset implicitly. Do not create symlinks anywhere in the required persistent-path ancestry.

### 2. Use bootstrap, preflight and ACL audit from the same revision

The selected image, `compose/truenas.yml` and the host-side helper scripts must describe the same repository revision.

For the reference YAML, which declares Codex plus optional/experimental Antigravity, run after the root dataset exists:

```bash
sudo python3 scripts/init-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity

sudo python3 scripts/preflight-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity

sudo python3 scripts/truenas-acl-audit.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity
```

The initializer creates only missing canonical descendants and is idempotent. It does not delete, migrate, rename or recursively rewrite existing project/state contents. Preflight validates the same path contract. The ACL audit is read-only and checks the reference Generic/POSIX private-state policy.

Browser passwords are deployment configuration and are validated by their agent endpoints at startup. The retired browser-password file/secret-tree design is not part of bootstrap or preflight.

If you intentionally maintain a local Codex-only YAML without Antigravity, omit `--include-antigravity` consistently. For exact candidate/digest validation, see the [TrueNAS validation runbook](docs/truenas-antigravity-validation.md) and [TrueNAS ACL contract](docs/truenas-acl-contract.md).

### 3. Review host-specific YAML values

Before saving the Custom App, review at least:

- every example bind IP and replace it with the LAN/Tailscale/private-mesh IP of the TrueNAS host;
- every `/mnt/Pool1/remote-dev` bind source if your pool/path differs;
- the configured Codex and optional Antigravity `WEB_PASSWORD` values; they are separate configuration entries but may currently contain the same value;
- timezone, Git identity and Codex approval mode where needed;
- `REMOTE_DEV_PROJECT`: leave the YAML value empty for normal menu mode or set a validated fixed project for direct-agent use.

Remote Dev currently requires only a non-empty single-line value for a protected agent endpoint. It does not enforce minimum length, composition or cross-service uniqueness yet; those choices are intentionally deferred to a future browser-access/security decision.

A privileged TrueNAS administrator can inspect saved App/container configuration and is inside Remote Dev's trust boundary. Sanitize screenshots/YAML exports before sharing them.

TrueNAS Custom App serialization may rewrite formatting, discard comments and not preserve Compose interpolation exactly. Verify the effective image reference/channel after saving.

After the App is running, open:

```text
http://<TrueNAS-LAN-or-private-mesh-IP>:7680
```

Port `7680` is the launcher and is intentionally password-free in the current private-network model. Codex authenticates on `7681`; Antigravity authenticates separately on `7682`. Separate agent endpoints/configuration do not require different password values. Do not expose these ports directly to the public Internet.

Continue with the [practical user guide](docs/user-guide.md).

## Roles and entrypoints

Canonical runtime entrypoints include `start-remote-dev-web`, `remote-dev-launcher`, `remote-dev-menu`, `remote-dev-doctor` and `remote-dev-healthcheck`. Codex-specific entrypoints remain compatibility wrappers.

Implemented roles are:

```dotenv
REMOTE_DEV_ROLE=launcher
# or: codex
# or: antigravity
# or: shell
```

`claude` remains reserved and unimplemented.

Agent-role services accept `REMOTE_DEV_START_MODE=menu|agent|shell`; the launcher accepts only `menu`.

## Project-scoped workspaces

`/workspace` is the private **project collection root** for an agent role. Normal sessions run from one validated direct child such as `/workspace/pollenlevels`; `/workspace` itself is not treated as an implicit repository.

The **Projects...** menu can select, create or exact-name-confirm-delete validated direct child project directories. Symlink projects, traversal and arbitrary absolute selectors are rejected.

For direct agent mode, set a project when more than one exists:

```dotenv
REMOTE_DEV_PROJECT=pollenlevels
```

Project selection chooses a working directory; it is **not** a filesystem-isolation boundary from sibling projects already mounted in the same role container. Codex and Antigravity receive separate writable workspace mounts, so use separate clones/worktrees across roles.

## Launcher and browser authentication

The launcher is a small navigation-only interface. It does not proxy ttyd traffic, manage containers or receive agent state/credentials.

**The current supported launcher does not require a password.** Bind it only to localhost, a trusted LAN or a private mesh such as Tailscale. It is not yet the central secure authentication gateway for the stack.

Codex and enabled Antigravity are the protected endpoints. Each uses one configuration-backed `WEB_PASSWORD` value. Generic Compose keeps separate operator-facing entries for those agent services so they can be changed independently. Remote Dev currently permits those entries to use the same password value and applies no minimum-length or composition rule.

The former file-backed browser-password mechanism is retired. Stronger single-entry authentication, a central gateway, identity/passkeys/MFA or a design where the launcher becomes the trusted entry boundary is future #181 work.

An existing `compose/launcher-auth.yml` advanced override remains in the repository, but it is not part of the normal current deployment path and is not required to use Remote Dev.

## Codex approval modes

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# or: guarded
```

- `autonomous` maps to `--ask-for-approval never`.
- `guarded` marks only the active project untrusted for that launch so Codex prompts unless an explicit exec-policy rule allows the command.

Start/Resume use the selected project as Codex's working directory. A one-launch mode override does not rewrite permanent configuration.

## Explicit Codex runtime updates

The image-tested `/usr/local/bin/codex` remains immutable. An administrator can explicitly install/update/remove a newer compatible official Codex release through `remote-dev-codex-runtime` while keeping the bundled CLI as fallback.

A newer admitted runtime can be shown as **official source; Remote Dev review pending**. Optional runtime state lives in Codex-private persistence and never replaces the immutable fallback. See [`docs/codex-runtime-updates.md`](docs/codex-runtime-updates.md).

## Antigravity — optional and experimental

Antigravity is implemented, not reserved, but remains deliberately **experimental**.

Its project-scoped Start/Resume, useful conversation continuity, explicit install/update, image rollback, persistence and broader TrueNAS lifecycle/isolation validation are complete. The #96 hardened runtime-admission model and the human #53 current-terms/policy reconciliation are also complete.

Remote Dev's accepted support interpretation is narrow:

- use Google's official `agy` CLI/runtime obtained through the reviewed official-source path;
- keep installation/update explicit and user initiated;
- keep vendor automatic update disabled in supported sessions;
- do not redistribute Google installer/CLI proprietary bytes in the image/repository;
- do not implement an alternative Antigravity service client;
- do not reuse/export Google/Antigravity OAuth credentials for another coding agent/service;
- keep role-private credentials/state plus admission/integrity safeguards;
- keep non-affiliation/vendor terms/privacy wording;
- do not describe Remote Dev review evidence as Google signing, certification or endorsement.

The project records this as a human risk/support interpretation, not vendor legal approval.

Scheduled #83 review automation is shipped. Daily discovery validates/downloads bounded installer/manifest/archive bytes as **data**, computes installer/payload identities and executes no vendor code. Changed candidates cross that boundary as metadata; executable inspection requires the explicit trusted review workflow.

See [`docs/antigravity-runtime-admission.md`](docs/antigravity-runtime-admission.md) and [`third_party/optional-agents.md`](third_party/optional-agents.md).

## Context7 for Codex

Context7 hosted MCP support and optional device-code onboarding are shipped for Codex. Remote Dev does not retain a Context7 runtime/package in the image; explicit device login uses reviewed transient tooling and cleans it afterward.

Context7 is an external service operated by Upstash. See [`docs/context7-codex.md`](docs/context7-codex.md) and [`docs/context7-codex.es.md`](docs/context7-codex.es.md).

## Isolation on TrueNAS

The default image does not install system Bubblewrap. Supported Codex launches explicitly disable the unsupported nested sandbox; the outer Docker container and narrow mounts are the supported isolation boundary.

Production launcher, Codex and Antigravity containers use read-only root filesystems, `no-new-privileges`, `cap_drop: [ALL]`, private role mounts and bounded PID/tmpfs/shm controls. The launcher runs as UID/GID `65532` with no restored capabilities. Agent containers restore only the exact reviewed minimum where required.

Do not add privileged mode, `SYS_ADMIN`, host namespaces or a Docker/Podman socket to force an inner sandbox. See [`docs/security.md`](docs/security.md).

## Canonical persistent-data layout

Generic Compose uses one administrative root:

```dotenv
REMOTE_DEV_DATA_ROOT=../data
```

The Codex portion is:

```text
REMOTE_DEV_DATA_ROOT/
├── workspaces/
│   └── codex/
│       └── <project>/
└── state/
    └── codex/
        ├── agent/
        ├── runtime/
        ├── gh/
        ├── git/
        └── ssh/
```

Antigravity uses disjoint corresponding private children. Browser passwords are deployment configuration, not persistent data files.

## Licenses and optional vendor software

Remote Dev project code is Apache-2.0. Bundled upstream software retains its own licenses/notices.

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Google Antigravity, Claude Code and other proprietary vendor products are not covered by this repository's Apache-2.0 license. Antigravity runtime bytes are obtained only after explicit user action from the reviewed vendor source and are not redistributed by Remote Dev.

## Build locally

```bash
cp .env.example .env
chmod 600 .env
mkdir -p \
  data/workspaces/codex/example-project \
  data/state/codex/{agent,gh,git,ssh}
sudo install -d -o root -g root -m 0700 data/state/codex/runtime
# Edit .env and set a non-empty WEB_PASSWORD for Codex.
make preflight
./scripts/build-local.sh
```

The local development baseline is `0.1.1-dev`; edge publications use their dated `edge-YYYY.MM.DD-<short-sha>` identity instead of that local default. Then set `REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous` or `guarded`, use `REMOTE_DEV_IMAGE=remote-dev:local`, and start with Docker Compose.

## Public edge testing

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

For exact reproduction/rollback, record and use the published digest:

```text
ghcr.io/experience83/remote-dev@sha256:<digest>
```

A normal edge runtime identity separates build identity and channel:

```text
Image version: edge-YYYY.MM.DD-<7-char-sha>
Channel: edge
Source revision: <full-commit-sha>
Codex CLI: codex-cli <bundled-version>
```

`latest` is **not** edge. The permanent contract is `dev -> edge -> stable = latest`; `stable`/`latest` move only after explicit stable SemVer publication.

See [`docs/releases.md`](docs/releases.md).

## Important warnings

- Do not publish ports 7680, 7681 or 7682 directly to the Internet.
- Bind the password-free launcher only to localhost, a trusted LAN or a private mesh such as Tailscale.
- Codex and enabled Antigravity require configured non-empty single-line passwords unless an explicit reviewed insecure override applies; the current product does not require long or mutually different password values.
- The launcher is not yet the secure authentication gateway; that future design belongs to #181.
- Do not mount agent state or a container-engine socket into the launcher.
- Project selection changes working directory; it does not isolate sibling projects already mounted under the same `/workspace`.
- Do not share one writable checkout across agent services by default.
- Agent root is constrained by the outer role container and its mounts.
- TrueNAS/Docker administrators can inspect deployment configuration and are inside the host trust boundary.
- Antigravity remains experimental even though its technical lifecycle/admission gates are implemented.
- `edge` remains experimental; no stable release exists yet.

## Documentation

- [`PROJECT_STATUS.md`](PROJECT_STATUS.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/security.md`](docs/security.md)
- [`docs/tool-matrix.md`](docs/tool-matrix.md)
- [`docs/decisions.md`](docs/decisions.md)
- [`docs/releases.md`](docs/releases.md) / [`docs/releases.es.md`](docs/releases.es.md)
- [`docs/user-guide.md`](docs/user-guide.md) / [`docs/user-guide.es.md`](docs/user-guide.es.md)
- [`docs/codex-runtime-updates.md`](docs/codex-runtime-updates.md) / [`docs/codex-runtime-updates.es.md`](docs/codex-runtime-updates.es.md)
- [`docs/context7-codex.md`](docs/context7-codex.md) / [`docs/context7-codex.es.md`](docs/context7-codex.es.md)
- [`docs/antigravity-runtime-admission.md`](docs/antigravity-runtime-admission.md) / [`docs/antigravity-runtime-admission.es.md`](docs/antigravity-runtime-admission.es.md)
- [`docs/truenas-acl-contract.md`](docs/truenas-acl-contract.md) / [`docs/truenas-acl-contract.es.md`](docs/truenas-acl-contract.es.md)
- [`docs/dependency-automation.md`](docs/dependency-automation.md)
- [`docs/roadmap.md`](docs/roadmap.md)
- [`third_party/optional-agents.md`](third_party/optional-agents.md)
