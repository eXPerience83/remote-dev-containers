# Remote Dev Containers — starter v0.1

Community-maintained, browser-accessible coding-agent environment for Docker, NAS and homelab systems.

> [!WARNING]
> **Active development / experimental.** There is no stable release yet. The public `edge` images may change or break without notice and have not completed the full TrueNAS, security or persistence validation checklist. Do not expose any web port directly to the Internet. This project is not affiliated with or endorsed by OpenAI, Google or Anthropic.

## Goal

Keep development tools, repositories and coding agents on a remote Docker host so the personal computer only needs a browser.

## Current implementation

The current edge stack is the Codex reference implementation, with Antigravity available only as an explicitly enabled experimental role:

- one Remote Dev image reused by the launcher, Codex and optional Antigravity services;
- one stateless launcher as the normal browser entry point, without authentication by default;
- one isolated, independently authenticated Codex terminal service with private role-scoped mounts;
- an optional isolated Antigravity terminal service using its own private role state and an explicitly installed vendor runtime;
- shared lightweight Ubuntu 26.04 LTS base;
- root runtime for predictable tool permissions;
- Codex CLI from an official pinned release asset, plus an explicit optional official runtime-update path with the bundled CLI retained as fallback;
- GitHub CLI as a core tool;
- Python 3.14, Node 24, uv and mise;
- browser terminal through ttyd;
- persistent sessions through tmux;
- one canonical role-neutral persistent-data contract;
- role-neutral project selection below each private `/workspace` mount so agents launch from a concrete project rather than the collection root;
- AMD64 first.

## Install on TrueNAS SCALE

Use [`compose/truenas.yml`](compose/truenas.yml) as the **canonical TrueNAS Custom App YAML**. Do not maintain a separate copied stack definition from the README.

Current TrueNAS UI documentation exposes Compose YAML installation from **Apps → Discover Apps → ⋮ → Install via YAML**. Give the Custom App a name, paste the contents of `compose/truenas.yml` into **Custom Config**, review the host-specific values below, and save the app.

Before saving, review at least:

- every example bind IP `192.168.1.10` and replace it with the LAN or Tailscale IP of the TrueNAS host;
- every `/mnt/Pool1/remote-dev` bind source and replace the dataset root if your pool/path differs;
- Codex `WEB_PASSWORD` and the independent Antigravity `WEB_PASSWORD` when retaining the experimental Antigravity terminal from the reference YAML;
- optional timezone, Git identity and Codex approval-mode values if the defaults are not appropriate;
- `REMOTE_DEV_PROJECT`: leave the literal YAML value empty for normal menu mode. For a fixed direct-agent project, edit the relevant TrueNAS YAML field itself. An ambient `.env` `REMOTE_DEV_PROJECT` does **not** override this literal field in `compose/truenas.yml`.

The reference YAML declares the role-private Codex and experimental Antigravity workspace/state trees. Create the required host directories before deployment and run the repository preflight on the TrueNAS host. For the reference YAML as shipped:

```bash
python3 scripts/preflight-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity \
  --password-source environment
```

`--password-source environment` matches the TrueNAS home-mode YAML, where terminal passwords are entered as `WEB_PASSWORD` values rather than file-backed secrets. If you intentionally maintain a local Codex-only YAML without the Antigravity service, omit `--include-antigravity` and create only the Codex paths.

After TrueNAS reports the Custom App as running, open:

```text
http://<TrueNAS-LAN-or-Tailscale-IP>:7680
```

Port `7680` is the launcher. Codex remains independently authenticated on port `7681`; the experimental Antigravity terminal uses its own authentication on port `7682`. Do not expose any of these ports directly to the Internet.

After installation, continue with the [practical user guide](docs/user-guide.md) for projects, Codex sessions/Resume, tmux/browser controls, `AGENTS.md`, persistence and project-local tooling.

TrueNAS Custom App/YAML UI details can change between TrueNAS releases; the current upstream reference is the [TrueNAS Custom App documentation](https://www.truenas.com/docs/scale/apps/installcustomappscreens/).

### Role-neutral entrypoints

The accepted single-stack architecture uses one canonical runtime implementation:

- `start-remote-dev-web`;
- `remote-dev-launcher`;
- `remote-dev-menu`;
- `remote-dev-doctor`;
- `remote-dev-healthcheck`.

`start-codex-web`, `codex-menu` and `codex-doctor` remain compatibility wrappers that select the Codex role and call the canonical commands.

Implemented roles are:

```dotenv
REMOTE_DEV_ROLE=launcher
# or: codex
# or: antigravity
# or: shell
```

`antigravity` is implemented as an **experimental optional role** and remains behind explicit enablement; its real project/session Start/Resume validation is deferred to issue #131. Its vendor runtime is installed only by explicit user action and normal startup never downloads it implicitly. `claude` remains reserved and unimplemented.

The neutral direct-start selector accepts `menu`, `agent` or `shell` for agent-role services:

```dotenv
REMOTE_DEV_START_MODE=menu
```

The launcher accepts only `menu`. The existing `START_MODE=menu|codex|shell` setting remains compatible for Codex and shell deployments; legacy `codex` maps to neutral `agent`. Unknown roles and modes are rejected without evaluating editable shell fragments.

### Project-scoped workspaces

`/workspace` is the private **project collection root** for the current agent service. Normal agent sessions run from one validated direct child such as `/workspace/pollenlevels`; `/workspace` itself is not treated as an implicit repository.

The agent menu exposes **Projects...** with actions to select, create or delete direct child project directories. Project discovery is intentionally non-recursive. If exactly one valid project exists it is selected automatically; if several exist, choose one before Start/Resume. The current selection lasts only for that menu/tmux session.

Project creation makes an empty direct child directory only. It does not run `git init`, clone a repository or contact a remote service. Deletion is destructive and requires typing the exact project name before the entire directory is removed. Project names are restricted to one conservative path component: ASCII letters/digits plus `.`, `_` and `-`, starting with a letter or digit. Symlink project entries and path traversal are rejected.

For direct `REMOTE_DEV_START_MODE=agent`, set a validated project name when more than one project exists:

```dotenv
REMOTE_DEV_PROJECT=pollenlevels
```

With no explicit selector, direct agent mode auto-resolves exactly one project and otherwise fails clearly instead of starting at `/workspace`. General shell mode continues to open at the collection root.

Selecting a project sets the agent's default working directory; it is **not** a filesystem isolation boundary. The complete role-private `/workspace` mount remains available inside that agent container, so sibling projects can still be accessed by processes running there. Use separate role services or mounts if filesystem isolation between those projects is required.

Each agent service still owns a separate writable workspace mount. Shared project-management code does **not** share a checkout between Codex, Antigravity or future roles. Use independent clones/worktrees when the same logical repository is needed by more than one agent; do not mount one writable checkout into several agent services by default.

### Single-stack launcher

The generic and TrueNAS Compose files use the same `REMOTE_DEV_IMAGE` reference for the launcher and Codex services and for the optional Antigravity service when it is enabled:

```text
Remote Dev stack
├── launcher      → primary browser port 7680
├── codex         → authenticated terminal port 7681
└── antigravity   → optional experimental authenticated terminal port 7682
```

The launcher is navigation only and has no authentication by default. It checks same-origin requests when an `Origin` header is present and applies a restrictive Content Security Policy. It shows the embedded image/source identity and only fixed links for services enabled by the reviewed stack configuration.

Selecting Codex navigates the browser to the Codex service. The launcher does **not** proxy or relay ttyd HTTP/WebSocket traffic, does not use the Docker socket and receives no Codex workspace, agent state, GitHub configuration, Git configuration, SSH mounts, optional Codex runtime state or Codex terminal password. When experimental Antigravity is enabled, its terminal remains a separate independently authenticated endpoint with its own role-private workspace and state.

The Codex endpoint authenticates independently with its own password source. Credentials are not embedded in the link, passed through the launcher or shared between services.

Launcher Basic authentication remains optional for advanced generic Compose deployments through the separate file-backed `compose/launcher-auth.yml` override. The normal TrueNAS home/LAN example does not require a second password, secret, mount or launcher dataset.

Configured launcher and agent paths are restricted to safe URL-path characters before they are placed into the page. Antigravity remains experimental and its real project/session behavior is tracked in #131; Claude and a one-origin reverse proxy remain outside the current implementation.

### Codex approval modes

Codex always runs through the project-owned command launcher with the unsupported inner sandbox disabled explicitly. The deployment can select one of two validated modes:

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# or: guarded
```

- `autonomous` is the default and maps to `--ask-for-approval never`.
- `guarded` marks only the active project untrusted for that launch. Codex then prompts for commands unless an explicit exec-policy rule allows them; plain `on-request` in a trusted project is not Remote Dev guarded mode.

The menu has separate **Start Codex** and **Resume a Codex session** actions plus an **Approval mode for next launch** selector. Start and Resume pass the selected project to Codex with its working-directory option, so Codex starts in `/workspace/<project>` and uses it as the default working directory for repository discovery and `AGENTS.md` lookup. This working-directory selection does not restrict filesystem access to that child; sibling projects under the same mounted `/workspace` remain reachable. The approval selector can keep the configured mode or choose autonomous/guarded for the next start or resume only. A one-launch override is consumed when Codex starts and the menu then returns automatically to the deployment setting. It never rewrites the permanent configuration.

The equivalent command-line interface is:

```bash
run-codex --cd /workspace/pollenlevels --approval-mode autonomous
run-codex --cd /workspace/pollenlevels --approval-mode guarded resume
run-codex --print-policy
```

A per-launch selection overrides the deployment value only for that process. Unknown values and raw Codex sandbox/approval overrides are rejected before Codex starts. Arguments after `--` remain literal Codex/prompt arguments.

The upstream Codex TUI also exposes `/permissions`. That command changes the active upstream permission profile inside the running Codex process; it does not set `REMOTE_DEV_CODEX_APPROVAL_MODE` and does not replace Remote Dev's validated autonomous/guarded resolver. Use the Remote Dev menu or deployment variable for the supported default and next-launch behavior.

### Explicit Codex runtime updates

The image-tested `/usr/local/bin/codex` remains immutable. From the Codex menu or with `remote-dev-codex-runtime install` / `remote-dev-codex-runtime update`, an administrator may explicitly install a newer compatible package from OpenAI's official Codex release. Both commands use the same bounded admission path and ask for confirmation before the first updater network request. `--yes` is the explicit non-interactive form for `install`, `update` and `remove`.

A newer admitted package is shown as **official source; Remote Dev review pending**. That means origin, release digest, package identity and bounded compatibility checks passed, while Remote Dev has not yet reviewed and deployment-tested that exact release as part of an image build. Damaged or locally modified optional state is rejected, and an equal/older optional runtime never shadows the bundled CLI.

The optional package is stored outside `CODEX_HOME` under the Codex-only runtime state mount, so credentials/config/sessions remain separate and the upstream standalone self-update path cannot bypass the project-owned explicit updater. See `docs/codex-runtime-updates.md` for the trust states, package checks, fallback behavior and removal command.

### Isolation on TrueNAS

The default image does not install the system Bubblewrap package. The supported Codex command launcher explicitly disables Codex's unsupported nested sandbox with `--sandbox danger-full-access`. Autonomous mode uses `--ask-for-approval never`; guarded mode applies launch-scoped untrusted project trust so commands prompt unless an explicit exec-policy rule allows them. Every supported menu, resume and direct Codex path uses that same resolver. Approval prompts are not a sandbox; the outer container remains the isolation boundary.

Here, `danger-full-access` describes only the Codex inner sandbox. It does not grant Docker privileges or host access. The outer Docker container and its narrow mounts are the supported security boundary. Approval prompts are not a sandbox and do not protect files or credentials already mounted into the service.

Autonomous mode means Codex may read, modify or delete anything mounted into its service and may use credentials available there without asking first. It does not add access beyond the existing container mounts, network and credentials. Guarded mode adds confirmation friction but does not provide filesystem isolation.

The production launcher, Codex and Antigravity containers use a read-only root filesystem, `no-new-privileges`, `cap_drop: [ALL]`, no supplementary groups, role-private mounts and explicit PID limits (`64` for the launcher, `1024` for each agent). The launcher starts as root only to read an optional protected file-backed password, receives only `DAC_READ_SEARCH`, `SETGID` and `SETUID`, then permanently becomes UID/GID `65532` with zero effective capabilities. `DAC_READ_SEARCH` is needed because Compose preserves the host ownership of a mode-`0600` file-backed secret. Root agent terminals receive only `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `KILL`, `SETGID` and `SETUID`; those capabilities preserve private bind-mount ownership/hardening and bounded UID/GID `65534` candidate execution, not host access.

Each role has private transient `/tmp` and `/run` tmpfs mounts. `/tmp` remains a bounded `noexec,nosuid,nodev` filesystem; Codex `/run` deliberately permits execution for bounded Codex update and Context7 device-login staging. Normal Codex and Antigravity sessions instead use the hidden workspace-backed `/workspace/.remote-dev-tmp` tree for generic temporary files and uv, npm and pip caches. That untrusted development scratch persists with its role-private workspace, is excluded from project discovery and may be removed while the service is stopped for clean recreation. The launcher does not receive it. Generic Compose keeps file-backed secrets below `/run/secrets`, while the TrueNAS reference keeps its environment-backed password mode.

Do not weaken the host or container with privileged mode, `SYS_ADMIN`, unconfined security profiles or a Docker socket to make a nested sandbox start. Mount only the paths that the selected service must access.

## Canonical persistent-data layout

Generic Compose uses one administrative root:

```dotenv
REMOTE_DEV_DATA_ROOT=../data
```

Paths are resolved relative to `compose/docker-compose.yml`. The canonical layout is:

```text
REMOTE_DEV_DATA_ROOT/
├── workspaces/
│   └── codex/
│       └── <project>/
├── state/
│   └── codex/
│       ├── agent/
│       ├── runtime/
│       ├── gh/
│       ├── git/
│       └── ssh/
└── secrets/
    └── codex/
        └── web_password.txt
```

The Codex service mounts only `workspaces/codex` at `/workspace`; the project manager operates only on validated direct children below that mount. `state/codex/runtime` contains the complete Remote Dev-managed optional runtime state, including the `current` active pointer, retained release directories, package files and private integrity manifests such as `remote-dev-runtime.json`; `state/codex/agent` remains `CODEX_HOME` for credentials, configuration and sessions. The base launcher has no mounts; the optional launcher-auth overlay adds only its own dedicated read-only password secret. The parent data root, `/root`, `/home`, `/mnt`, host root and container-engine sockets are never mounted wholesale.

`state/codex/runtime` is a root-owned trust boundary: it must be a real `root:root` directory with mode `0700`. The runtime manager rejects an unexpected owner rather than admitting optional runtime state from an arbitrary host identity. Before deployment, run the host-side preflight. It validates every required directory, rejects symlinks, and checks that the password is a non-empty regular file with restrictive permissions; current preflight does not validate the runtime directory owner. Persistent bind mounts also request `create_host_path: false` as defense-in-depth, but the project does not rely on every Compose implementation enforcing that option.

There is no automatic migration or compatibility alias for the earlier experimental data layout. Move or recreate experimental state manually. Optional SMB/ACL workspace sharing is deferred to issue #71 and must never expose `state` or `secrets`; if implemented later, it must target explicitly selected concrete project directories rather than the whole collection root by default.

## Licenses and optional vendor software

Remote Dev project code is Apache-2.0. Ubuntu, Codex CLI, GitHub CLI, ttyd, mise, Python, Node.js, npm, uv and their dependencies retain their respective upstream licenses and notices. The image preserves package-provided copyright files and copies the license files supplied by the exact installed runtime artifacts. The embedded project-owned ttyd client has its own exact component inventory, preserved notices and dedicated SPDX document under `third_party/components/remote-dev-ttyd-client/`.

Inspect the reviewed inventory in `third_party/README.md`, or from a built image:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Antigravity, Claude Code and similar vendor products are not covered by this repository's Apache-2.0 license. They are not downloaded or redistributed by the current image. Any future optional installer must be initiated explicitly by the user, download directly from the vendor and follow the terms, privacy, credential-isolation and non-affiliation policy in `third_party/optional-agents.md`.

## Accepted target architecture

The target architecture is:

- one user-installed Remote Dev App or Compose stack;
- one final Remote Dev image digest reused by every service;
- one primary launcher URL;
- one isolated service per enabled coding agent;
- Codex as the built-in reference service;
- Antigravity as the first planned optional vendor-installed service;
- Claude Code preserved as a future path only;
- private workspaces, credentials, histories, GitHub state and SSH keys per agent service.

The current implementation delivers the launcher, Codex and canonical persistence portions of that topology. Docker reuses the same immutable image layers, and the launcher has no agent-state mounts or agent web credential. Optional agent services and the later cross-service hardening/canary phase remain tracked by issues #25 and #31.

The default launcher navigates to each agent's own authenticated endpoint and does not relay terminal traffic. Any future reverse proxy that terminates or relays that traffic is treated as a trusted transport component and requires a separate threat-model review.

## Build locally

```bash
cp .env.example .env
mkdir -p \
  data/workspaces/codex/example-project \
  data/state/codex/{agent,gh,git,ssh} \
  data/secrets/codex
sudo install -d -o root -g root -m 0700 data/state/codex/runtime
printf '%s\n' 'replace-with-a-codex-password' > data/secrets/codex/web_password.txt
chmod 600 data/secrets/codex/web_password.txt
make preflight
./scripts/build-local.sh
```

To correct an existing empty runtime directory with the wrong owner, run only:

```bash
sudo chown root:root data/state/codex/runtime
sudo chmod 0700 data/state/codex/runtime
```

For a custom root, set `REMOTE_DEV_DATA_ROOT=/absolute/host/path` in `.env` and run `make preflight DATA_ROOT=/absolute/host/path` before deployment. You may also create the first project later from the **Projects...** menu instead of creating `example-project` on the host.

Set `REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous` or `guarded` in `.env`, set `REMOTE_DEV_IMAGE=remote-dev:local`, and run:

```bash
docker compose -f compose/docker-compose.yml up -d
```

Open the launcher at published port `7680` and select Codex. The browser then opens the independently authenticated terminal on published port `7681`. Inside the Codex menu you can:

1. select, create or explicitly-confirm-delete projects below `/workspace`;
2. start Codex or resume a saved session in the selected project with the configured deployment mode;
3. select autonomous or guarded for the next start/resume only;
4. explicitly update or remove the optional official Codex runtime while retaining the bundled fallback;
5. use Codex device-code login;
6. use GitHub CLI login;
7. run diagnostics.

To protect the launcher itself in an advanced generic Compose deployment, create a separate launcher password file and add the reviewed override:

```bash
mkdir -p secrets
printf '%s\n' 'replace-with-a-launcher-password' > secrets/launcher_password.txt
chmod 600 secrets/launcher_password.txt
docker compose \
  -f compose/docker-compose.yml \
  -f compose/launcher-auth.yml \
  up -d
```

The override mounts that value as a Compose secret at `/run/secrets/launcher_password`; it does not place the password in the rendered service environment and it does not replace or reuse the Codex terminal password.

## Public edge testing

The `edge` image is an unstable development build published automatically after relevant changes merge into `main`. It is available publicly for testing, but it must not be treated as a stable release.

Pull the current AMD64 edge image without registry credentials:

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

For the generic or TrueNAS Compose file, set:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

The only published GHCR runtime package is `ghcr.io/experience83/remote-dev`. The legacy `CODEX_IMAGE` variable remains accepted throughout `v0.1.x` as a configuration fallback, but it should point to the canonical `remote-dev` package. The old remote package `ghcr.io/experience83/codex-remote-dev` is retired and may be deleted from GHCR after this change is merged.

For a source-commit-addressed deployment, use the `sha-...` tag shown by the edge workflow and package page:

```text
ghcr.io/experience83/remote-dev:sha-<full-commit-sha>
```

GHCR tags are mutable. For immutable reproduction or rollback, record the published digest and pin the image as:

```text
ghcr.io/experience83/remote-dev@sha256:<digest>
```

The launcher and terminal diagnostics show the embedded image channel and source revision. To display the complete embedded image metadata together with the bundled and optional Codex runtime state from a Codex shell, run:

```bash
remote-dev-version
```

Expected edge output begins with:

```text
Image version: edge
Source revision: <full-commit-sha>
Codex CLI: codex-cli <bundled-version>
```

When an optional runtime exists, the command also reports its version, trust state and active source.

See `docs/releases.md` for release channels, promotion criteria and rollback guidance.

## Important warnings

- Do not publish ports 7680, 7681 or 7682 directly to the Internet.
- The unauthenticated launcher should be bound only to localhost, a trusted LAN address or a Tailscale address.
- The Codex terminal remains independently authenticated.
- The launcher never embeds or forwards the terminal password.
- The launcher is navigation only and does not make the Codex terminal a same-origin application.
- Do not mount agent workspaces, credentials or optional runtime state into the launcher.
- Selecting a project changes the agent working directory; it does not isolate that project from sibling directories mounted under the same `/workspace`.
- Do not share one writable project checkout between agent services by default; use separate clones/worktrees.
- Project deletion removes the complete selected `/workspace/<project>` directory after exact-name confirmation; commit or back up anything that must be retained first.
- Do not mount the Docker socket.
- Do not use privileged mode.
- The default Codex command launcher disables the inner sandbox explicitly; the outer Codex container is the supported isolation boundary.
- Autonomous mode permits Codex to act on all state mounted into the Codex service without confirmations.
- Guarded prompts are not a sandbox and do not hide mounted files or credentials from Codex.
- Anyone with terminal access can read repositories and credentials mounted into that agent service.
- `auth.json`, GitHub tokens and SSH keys are secrets.
- A newer optional Codex runtime marked review-pending has passed provenance/integrity/compatibility admission but has not yet completed Remote Dev review and real deployment validation for that exact upstream release.
- Optional vendor agents are not bundled or covered by the project Apache-2.0 license.
- `edge` is experimental and may be replaced without notice.
- Breaking configuration and persistence changes are still possible before `v0.1.0`.

## Development and reviews

Development happens through pull requests. CodeRabbit is configured in `.coderabbit.yaml` to review Dockerfiles, Bash scripts, Python launcher code, GitHub Actions, Compose and security-sensitive changes. Its comments are advisory during the current development phase; passing CI and manual validation remain required.

Read `AGENTS.md` and `CONTRIBUTING.md` before proposing changes. Pull requests use the repository template, and GitHub requests review from the code owner when a non-draft pull request is ready for review.

## Documentation

- `AGENTS.md`
- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `PROJECT_STATUS.md`
- `third_party/README.md`
- `third_party/optional-agents.md`
- `docs/architecture.md`
- `docs/tool-matrix.md`
- `docs/security.md`
- `docs/decisions.md`
- `docs/releases.md`
- `docs/runtime-locks.md`
- `docs/dependency-automation.md`
- `docs/user-guide.md`
- `docs/user-guide.es.md`
- `docs/codex-runtime-updates.md`
- `docs/codex-runtime-updates.es.md`
- `docs/roadmap.md`

## Upstream references

- OpenAI Codex: https://github.com/openai/codex
- Codex documentation: https://developers.openai.com/codex/cli
- GitHub CLI: https://github.com/cli/cli
- ttyd: https://github.com/tsl0922/ttyd
- mise: https://github.com/jdx/mise
