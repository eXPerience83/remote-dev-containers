# Tool matrix

## Architecture status

The current development image is Codex-specific. The accepted target architecture uses one final Remote Dev image digest for a launcher and isolated agent services inside one App or Compose stack. Issue #25 implements that migration.

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
| User entry point | launcher or gateway runtime after issue #25 is implemented |
| Built-in agent | Codex CLI reference integration |
| Optional integrations | reviewed installer/manager code only; proprietary binaries are not implied |

The system Bubblewrap package and executable are deliberately not installed in the default image. The pinned Codex release may carry its own packaged fallback, but the supported launcher disables the unsupported inner sandbox explicitly, uses `untrusted` approvals and relies on the outer container plus narrow mounts as the TrueNAS isolation boundary.

A shared executable does not imply shared configuration or credentials.

## Service-private state

Every agent service receives its own narrow persistent mounts:

| State | Launcher | Codex service | Optional agent service |
|---|---:|---:|---:|
| Workspace or worktree | No | Private | Private |
| Agent authentication/configuration | No | Private | Private |
| Agent cache/history/sessions | No | Private | Private |
| Managed runtime packages | No | Private | Private |
| GitHub CLI configuration | No | Private | Private |
| Git global configuration | No | Private | Private |
| SSH keys/configuration | No | Private | Private |
| MCP/integration credentials | No | Private | Private |
| Launcher UI/routing state | Private | No | No |

The launcher may receive its own browser-authentication secret and fixed routing configuration. It must not mount agent workspaces, OAuth tokens, GitHub CLI state or SSH keys.

The supported deployment does not mount `/root`, `/home`, `/opt`, `/usr/local` or the parent Remote Dev data directory wholesale.

## Agent availability

| Agent | Distribution in final image | Supported state |
|---|---|---|
| Codex CLI | Immutable fallback built from an official pinned release asset | Current reference implementation; explicit newer official runtime may be admitted into Codex-private state |
| Antigravity | Not redistributed by default; explicit vendor-sourced installation is planned | Not yet supported |
| Claude Code | Not installed or advertised | Future research path only |
| OpenCode | Independent project based on its official image | Outside this stack |

A newer Codex runtime is downloaded only through the explicit project-owned update action, is not part of the image build-time SBOM, and never replaces the image-bundled fallback. Normal startup does not download or update it.

Optional agents must not be downloaded silently during launcher or container startup. Their persisted binaries, credentials and histories remain scoped to their own service.

## Explicitly deferred

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
