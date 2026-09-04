# Remote Dev Containers — starter v0.1

Community-maintained, browser-accessible coding-agent environment for Docker, NAS and homelab systems.

> [!WARNING]
> **Active development / experimental.** There is no stable release yet. Public `edge` images are integrated development builds and may still change before the first stable release. Do not expose any Remote Dev web port directly to the Internet. This project is not affiliated with or endorsed by OpenAI, Google or Anthropic.

## Goal

Keep development tools, repositories and coding agents on a remote Docker host so the personal computer only needs a browser.

## Current implementation

The current stack uses one canonical Remote Dev image for isolated fixed-role services:

```text
Remote Dev stack
├── launcher      7680 — navigation only
├── codex         7681 — independently authenticated terminal
└── antigravity   7682 — optional/experimental independently authenticated terminal
```

Current foundations:

- one `ghcr.io/experience83/remote-dev` image reference reused by launcher, Codex and enabled Antigravity services;
- one stateless/navigation-only launcher with no agent workspace, state, password or Docker/Podman socket;
- one isolated Codex reference service with private role-scoped mounts;
- one optional isolated Antigravity service with private state and a vendor runtime installed only by explicit user action;
- Ubuntu 26.04 LTS, AMD64 first;
- Codex CLI from an official pinned release asset, plus an explicit optional official runtime path with the bundled CLI retained as fallback;
- GitHub CLI, Python 3.14, Node 24, npm, uv, mise, ttyd and tmux;
- one canonical role-neutral persistent-data contract;
- one configuration-backed `WEB_PASSWORD` browser-authentication runtime contract with independent values per protected endpoint;
- project selection below each private `/workspace` collection root so agents launch from a concrete project rather than treating `/workspace` itself as a repository;
- `dev -> edge -> stable = latest` release semantics, with dated edge build identity kept separate from channel and immutable provenance.

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

The selected image, `compose/truenas.yml` and the host-side helper scripts must describe the same repository revision. Do not combine an image pinned to one revision with helper scripts copied later from a moving `main` branch.

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

The initializer creates only missing canonical descendants, applies initial modes only to paths it creates and is idempotent. It does not delete, migrate, rename or recursively chmod/chown existing project/state contents. Existing required paths, including deliberate child-dataset mountpoints, are preserved.

Preflight validates the same canonical path contract. The ACL audit is read-only and checks the reference Generic/POSIX private-state policy. Browser passwords are deployment configuration and are validated by their endpoints at startup; none of these host-layout helpers creates or requires a browser-password `secrets/` tree.

If you intentionally maintain a local Codex-only YAML without Antigravity, omit `--include-antigravity` consistently. Do not omit it while deploying the reference YAML unchanged because its Antigravity bind sources must already exist.

For exact candidate/digest validation and migration evidence, see the [TrueNAS validation runbook](docs/truenas-antigravity-validation.md) and [TrueNAS ACL contract](docs/truenas-acl-contract.md).

### 3. Review the host-specific YAML values

Before saving the Custom App, review at least:

- every example bind IP and replace it with the LAN or Tailscale/private-mesh IP of the TrueNAS host;
- every `/mnt/Pool1/remote-dev` bind source if your pool/path differs;
- Codex `WEB_PASSWORD` and the independent Antigravity `WEB_PASSWORD` when retaining the Antigravity service;
- timezone, Git identity and Codex approval mode where needed;
- `REMOTE_DEV_PROJECT`: leave the literal YAML value empty for normal menu mode, or set a validated fixed project for direct-agent use.

A privileged TrueNAS administrator can inspect saved App/container configuration. That administrator is inside Remote Dev's trust boundary; sanitize screenshots and YAML exports before sharing them.

TrueNAS Custom App serialization may rewrite formatting, discard comments and not preserve Compose interpolation exactly as a source file would. Operational guidance therefore depends on the actual saved/rendered values, not on comments or `${...}` expressions surviving a UI edit round-trip. Verify the effective image reference/channel after saving.

After the App is running, open:

```text
http://<TrueNAS-LAN-or-private-mesh-IP>:7680
```

Port `7680` is the launcher. Codex authenticates independently on `7681`; Antigravity uses its own independent authentication on `7682`. Do not expose any of these ports directly to the public Internet.

Continue with the [practical user guide](docs/user-guide.md) for projects, sessions/Resume, tmux/browser controls, persistence and project-local tooling.

## Roles and entrypoints

Canonical runtime entrypoints include:

- `start-remote-dev-web`;
- `remote-dev-launcher`;
- `remote-dev-menu`;
- `remote-dev-doctor`;
- `remote-dev-healthcheck`.

`start-codex-web`, `codex-menu` and `codex-doctor` remain compatibility wrappers that select Codex and call the canonical runtime.

Implemented roles are:

```dotenv
REMOTE_DEV_ROLE=launcher
# or: codex
# or: antigravity
# or: shell
```

`claude` remains reserved and unimplemented.

Agent-role services accept `REMOTE_DEV_START_MODE=menu|agent|shell`; the launcher accepts only `menu`. Unknown roles/modes are rejected rather than evaluated as editable shell fragments.

## Project-scoped workspaces

`/workspace` is the private **project collection root** for the current agent role. Normal agent sessions run from one validated direct child such as `/workspace/pollenlevels`; `/workspace` itself is not treated as an implicit repository.

The **Projects...** menu can select, create or exact-name-confirm-delete validated direct child project directories. Discovery is deliberately non-recursive. Symlink projects, traversal and arbitrary absolute selectors are rejected.

For direct agent mode, set a project when more than one exists:

```dotenv
REMOTE_DEV_PROJECT=pollenlevels
```

Without an explicit selector, direct agent mode auto-resolves exactly one valid project and otherwise fails clearly.

Project selection chooses a working directory; it is **not** a filesystem-isolation boundary from sibling projects already mounted into the same role container. Codex and Antigravity receive separate writable workspace mounts, so the same logical repository should use separate clones/worktrees across roles rather than one concurrently writable checkout.

## Launcher and browser authentication

The launcher is navigation only. It does not proxy ttyd traffic, manage containers or receive agent state. It checks same-origin requests when an `Origin` header is present and applies a restrictive Content Security Policy.

Each protected agent endpoint uses one configuration-backed `WEB_PASSWORD` value. Generic Compose maps the external Codex `WEB_PASSWORD` and distinct `ANTIGRAVITY_WEB_PASSWORD` to their respective services. Credentials are not embedded in links, passed through the launcher or copied between roles.

`WEB_PASSWORD_FILE`, `/run/secrets/web_password`, browser-password Compose secrets and the old password-file persistence tree are retired.

Optional launcher Basic authentication remains available for advanced generic Compose deployments through `compose/launcher-auth.yml`. It uses a distinct `LAUNCHER_PASSWORD` mapped to the launcher's own `WEB_PASSWORD` and adds no bind/persistent secret mount.

## Codex approval modes

Supported project-owned launch modes are:

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# or: guarded
```

- `autonomous` maps to `--ask-for-approval never`.
- `guarded` marks only the active project untrusted for that launch so Codex prompts unless an explicit exec-policy rule allows the command.

Start and Resume pass the selected project as Codex's working directory. The menu can keep the deployment mode or choose an autonomous/guarded override for the next launch only; that one-launch choice does not rewrite permanent configuration.

Equivalent commands include:

```bash
run-codex --cd /workspace/pollenlevels --approval-mode autonomous
run-codex --cd /workspace/pollenlevels --approval-mode guarded resume
run-codex --print-policy
```

The upstream `/permissions` command changes the active Codex process's permission profile; it does not replace Remote Dev's deployment/next-launch resolver.

## Explicit Codex runtime updates

The image-tested `/usr/local/bin/codex` remains immutable. From the menu or `remote-dev-codex-runtime`, an administrator may explicitly install/update/remove a newer compatible official Codex release.

A newer admitted runtime can be shown as **official source; Remote Dev review pending**: the bounded origin/integrity/package/compatibility admission passed, but that exact upstream release has not yet completed the image's review/deployment evidence. Damaged or locally modified optional state is rejected and an equal/older optional runtime never shadows the bundled CLI.

Optional runtime state lives in the Codex-only `state/codex/runtime` mount, separate from `CODEX_HOME`, and never replaces the bundled fallback. See [`docs/codex-runtime-updates.md`](docs/codex-runtime-updates.md).

## Antigravity — optional and experimental

Antigravity is implemented, not reserved, but remains deliberately **experimental**.

Its project-scoped Start/Resume, useful conversation continuity, explicit install/update, image rollback, persistence and broader TrueNAS lifecycle/isolation validation are complete. The #96 hardened runtime-admission model and the human #53 current-terms/policy reconciliation are also complete.

Remote Dev's accepted support interpretation is narrow:

- use Google's official `agy` CLI/runtime obtained through the reviewed official-source path;
- keep installation/update explicit and user initiated;
- keep vendor automatic update disabled in supported sessions;
- do not redistribute Google installer/CLI proprietary bytes in the image/repository;
- do not implement an alternative Antigravity service client;
- do not reuse/export Google/Antigravity OAuth credentials for Codex, Claude Code, OpenCode, OpenClaw or another third-party service;
- keep role-private credentials/state plus admission/integrity safeguards;
- keep non-affiliation/vendor terms/privacy wording;
- do not describe Remote Dev review evidence as Google signing, certification or endorsement.

The project records this as a human risk/support interpretation, not vendor legal approval.

Scheduled #83 review automation is shipped. Its daily discovery path validates/downloads bounded installer/manifest/archive bytes as **data**, computes the installer and `agy` payload hashes and executes no vendor code. If the pair changes, only metadata is proposed. Executable inspection requires the explicit trusted review workflow, which resolves and verifies the exact pending pair before execution.

See [`docs/antigravity-runtime-admission.md`](docs/antigravity-runtime-admission.md) and [`third_party/optional-agents.md`](third_party/optional-agents.md).

## Context7 for Codex

Context7 hosted MCP support and optional device-code onboarding are shipped for Codex.

Remote Dev does not retain a Context7 runtime/package in the image. Explicit device login may download/run the reviewed transient `ctx7` CLI in isolated disposable state, adopt only the validated resulting API key into Codex-private managed configuration and clean the transient vendor package/login/cache state afterward.

Context7 is an external service operated by Upstash. See [`docs/context7-codex.md`](docs/context7-codex.md) and [`docs/context7-codex.es.md`](docs/context7-codex.es.md) for privacy, terms, data-flow and credential boundaries.

## Isolation on TrueNAS

The default image does not install system Bubblewrap. Supported Codex launches explicitly disable the unsupported nested sandbox; the outer Docker container and narrow mounts are the supported isolation boundary.

Autonomous mode may act on everything mounted into the Codex service without confirmations. Guarded mode adds confirmation friction but is not a filesystem sandbox.

Production launcher, Codex and Antigravity containers use read-only root filesystems, `no-new-privileges`, `cap_drop: [ALL]`, no supplementary groups, private role mounts and bounded PID/tmpfs/shm controls. The launcher runs as UID/GID `65532` with no restored capabilities. Agent containers restore only the exact reviewed minimum needed for private-state ownership/hardening and bounded unprivileged admission work.

Do not add privileged mode, `SYS_ADMIN`, unconfined profiles, host networking/PID or a Docker/Podman socket to force an inner sandbox.

See [`docs/security.md`](docs/security.md) for the exact capability/tmpfs/mount model.

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

Antigravity uses disjoint corresponding private children. The parent data root, `/root`, `/home`, `/mnt`, host root and container-engine sockets are never mounted wholesale.

Browser passwords are deployment configuration, not part of `REMOTE_DEV_DATA_ROOT`.

`scripts/lib/data_layout.py` is the canonical host-side path contract consumed by both initializer and preflight. There is no automatic migration/copy/delete of experimental state. Use the documented migration path for any contract that changes on disk.

## Licenses and optional vendor software

Remote Dev project code is Apache-2.0. Bundled upstream software retains its own licenses/notices.

Inspect the inventory/notices with:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Google Antigravity, Claude Code and other proprietary vendor products are not covered by this repository's Apache-2.0 license. Antigravity's current integration downloads its runtime only after explicit user action directly through the reviewed vendor-source path and does not redistribute those bytes. Future optional proprietary integrations must follow the same explicit-source, terms/privacy, credential-isolation and non-affiliation policy in [`third_party/optional-agents.md`](third_party/optional-agents.md).

## Build locally

```bash
cp .env.example .env
chmod 600 .env
mkdir -p \
  data/workspaces/codex/example-project \
  data/state/codex/{agent,gh,git,ssh}
sudo install -d -o root -g root -m 0700 data/state/codex/runtime
# Edit .env and set a non-empty Codex-specific WEB_PASSWORD.
make preflight
./scripts/build-local.sh
```

Set `REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous` or `guarded`, set `REMOTE_DEV_IMAGE=remote-dev:local`, then start:

```bash
docker compose -f compose/docker-compose.yml up -d
```

Open port `7680`, select Codex and authenticate to its separate `7681` endpoint.

To protect the launcher too, set distinct launcher credentials and add the reviewed override:

```dotenv
LAUNCHER_USERNAME=remote-dev
LAUNCHER_PASSWORD=replace-with-a-distinct-launcher-password
```

```bash
docker compose \
  -f compose/docker-compose.yml \
  -f compose/launcher-auth.yml \
  up -d
```

To enable the generic Antigravity profile, set a separate `ANTIGRAVITY_WEB_PASSWORD` and follow the experimental Antigravity instructions. Never reuse the Codex password silently between endpoints.

## Public edge testing

The public integrated AMD64 channel is:

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

GHCR tags are mutable. For exact reproduction/rollback, record the published digest and use:

```text
ghcr.io/experience83/remote-dev@sha256:<digest>
```

Published `main` revisions also receive:

```text
ghcr.io/experience83/remote-dev:sha-<full-commit-sha>
```

A normal edge runtime identity now separates build identity from maturity channel:

```text
Image version: edge-YYYY.MM.DD-<7-char-sha>
Channel: edge
Source revision: <full-commit-sha>
Codex CLI: codex-cli <bundled-version>
```

`latest` is **not** edge. The permanent contract is `dev -> edge -> stable = latest`; `stable`/`latest` move only after an explicit stable SemVer publication.

See [`docs/releases.md`](docs/releases.md) for candidate publication, updater/Renovate changelog provenance, promotion criteria and rollback.

## Important warnings

- Do not publish ports 7680, 7681 or 7682 directly to the Internet.
- Bind the password-free launcher only to localhost, a trusted LAN or a private mesh such as Tailscale.
- Codex and Antigravity terminals remain independently authenticated with distinct configured passwords.
- The launcher never embeds or forwards an agent password and does not make agent terminals a same-origin application.
- Do not mount agent state or optional runtime state into the launcher.
- Project selection changes working directory; it does not isolate sibling directories already mounted under the same `/workspace`.
- Do not share one writable checkout across agent services by default; use separate clones/worktrees.
- Do not mount a Docker/Podman socket or use privileged mode.
- Agent root is constrained by the outer role container and its mounts; anyone with terminal access can use credentials visible to that service.
- TrueNAS/Docker administrators can inspect deployment configuration and are inside the host trust boundary.
- `auth.json`, GitHub tokens, Context7 keys and SSH keys are secrets.
- Optional vendor agents are not bundled or covered by the project Apache-2.0 license.
- Antigravity remains experimental even though its technical lifecycle/admission gates are implemented.
- `edge` remains experimental and can move after integrated changes; no stable release exists yet.

## Development and reviews

Development happens through pull requests. CodeRabbit is configured for security-sensitive repository areas, but automated review is advisory; repository CI, exact workflow gates and required human/real-system validation remain authoritative.

Read `AGENTS.md` and `CONTRIBUTING.md` before proposing changes.

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
- [`third_party/README.md`](third_party/README.md)
- [`third_party/optional-agents.md`](third_party/optional-agents.md)
- `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `AGENTS.md`

## Upstream references

- OpenAI Codex: https://github.com/openai/codex
- Codex documentation: https://developers.openai.com/codex/cli
- GitHub CLI: https://github.com/cli/cli
- ttyd: https://github.com/tsl0922/ttyd
- mise: https://github.com/jdx/mise
