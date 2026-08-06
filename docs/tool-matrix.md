# Tool matrix

## Architecture status

The current development image is reused by the launcher, Codex and optional Antigravity services inside one App or Compose stack. Each role runs in a separate container with private state and workspace mounts.

## Shared immutable image contents

These executables and project-owned runtime components are shared through read-only image layers:

| Area | Included |
|---|---|
| Runtime | Remote Dev entrypoints, role validation, diagnostics, version reporting and health checks |
| Terminal | bash, tmux, ttyd, tini, nano, less, fzf |
| Git | git, git-lfs, openssh-client, GitHub CLI executable |
| Search/files | ripgrep, fd, jq, rsync, zip/unzip, tar/gzip, patch |
| Build | build-essential, make, pkg-config and common native libraries |
| Python | Python 3.14, uv |
| JavaScript | Node 24, npm |
| Tool manager | mise |
| Checks | shellcheck |
| User entry point | Stateless navigation launcher |
| Built-in agent | Codex CLI reference integration |
| Optional agent support | Project-owned Antigravity installer/update/status/rollback wrappers and metadata-only review evidence |

The system Bubblewrap package and executable are deliberately not installed in the default image. The supported Codex launcher disables the unsupported inner sandbox explicitly and relies on the outer container plus narrow mounts as the TrueNAS isolation boundary.

A shared executable does not imply shared configuration or credentials.

## Service-private state

Every agent service receives its own narrow persistent mounts:

| State | Launcher | Codex service | Antigravity/optional service |
|---|---:|---:|---:|
| Workspace or worktree | No | Private | Private |
| Agent authentication/configuration | No | Private | Private |
| Agent cache/history/sessions | No | Private | Private |
| Runtime-installed optional executable | No | No | Private |
| Local agent integrity/rollback data | No | No | Private |
| GitHub CLI configuration | No | Private | Private |
| Git global configuration | No | Private | Private |
| SSH keys/configuration | No | Private | Private |
| MCP/integration credentials | No | Private | Private |
| Launcher UI/routing state | Private | No | No |

The launcher may receive its own browser-authentication secret and fixed routing configuration. It must not mount agent workspaces, OAuth tokens, GitHub CLI state or SSH keys.

The supported deployment does not mount `/root`, `/home`, `/opt`, `/usr/local` or the parent Remote Dev data directory wholesale.

## Agent availability

| Agent | Distribution in final image | Installation/update model | Current state |
|---|---|---|---|
| Codex CLI | Included from an official pinned OpenAI release asset | Image updates; future explicit official runtime update must retain bundled fallback | Built-in reference implementation |
| Antigravity | Google installer and `agy` executable are not redistributed | Explicit fixed official-source install/update, private local integrity manifest, one-version rollback; normal sessions never self-update | Experimental integration validated on TrueNAS; not stable |
| Claude Code | Not installed or advertised | No implementation authorized | Future research path only |
| OpenCode | Independent project based on its official image | Outside this stack | Outside this stack |

Antigravity review evidence distinguishes `official, reviewed` from `official, review pending`. A newer official-source installation remains usable while its private local integrity checks pass; publishing a new Docker image is not required for ordinary upstream version/hash churn. A changed or damaged local executable remains blocked.

Optional agents are never downloaded during launcher or container startup. Their persisted binaries, credentials and histories remain scoped to their own service.

## Explicitly deferred

- Explicit Codex runtime updater with bundled fallback
- Additional Python versions
- Additional Node versions
- Rust, Go, Java, Ruby, PHP, Swift, Erlang and Elixir
- Home Assistant helpers
- Browser automation and Playwright
- Office parsing and VBA tools
- actionlint, zizmor, Biome and html-validate
- Docker CLI and Docker socket access
- Bundled MCP servers and skills
- A virtual-machine distribution
- A privileged inner-sandbox profile

Additions should be driven by real repositories or community requests and measured for image size, security, licensing and maintenance cost.
