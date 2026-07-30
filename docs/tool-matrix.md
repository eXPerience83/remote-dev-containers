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
| Python | Python 3.14 from the exact `astral-sh/python-build-standalone` artifact pinned in `mise.lock`, plus uv |
| JavaScript | Node 24 from the exact official Node.js artifact pinned in `mise.lock`, plus npm 12 |
| Tool manager | mise |
| Checks | shellcheck |
| Notices | `remote-dev-notices`, the reviewed third-party inventory and runtime-provided license files |
| User entry point | launcher or gateway runtime after issue #25 is implemented |
| Built-in agent | Codex CLI reference integration |
| Optional integrations | reviewed installer/manager code only; proprietary binaries are not implied |

The system Bubblewrap package and executable are deliberately not installed in the default image. The pinned Codex release may carry its own packaged fallback, but the supported launcher disables the unsupported inner sandbox explicitly, uses `untrusted` approvals and relies on the outer container plus narrow mounts as the TrueNAS isolation boundary.

A shared executable does not imply shared configuration or credentials.

## Licensing and distribution boundary

Remote Dev project code is Apache-2.0. Bundled upstream components retain their own licenses and notices; the complete human-maintained inventory is in `third_party/README.md`, and the built image exposes it with:

```bash
remote-dev-notices
remote-dev-notices --list
remote-dev-notices --check
```

Ubuntu package notices remain under `/usr/share/doc/<package>/copyright`. Python, Node.js and npm license files are copied from the exact installed runtime artifacts during image construction. The generated SBOM supplements this inventory but does not replace required copyright, license or NOTICE files.

Antigravity, Claude Code and similar optional proprietary agents are not covered by the project license and are not redistributed by default. Their binding install, terms, privacy, credential and non-affiliation policy is recorded in `third_party/optional-agents.md`.

## Service-private state

Every agent service receives its own narrow persistent mounts:

| State | Launcher | Codex service | Optional agent service |
|---|---:|---:|---:|
| Workspace or worktree | No | Private | Private |
| Agent authentication/configuration | No | Private | Private |
| Agent cache/history/sessions | No | Private | Private |
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
| Codex CLI | Built from an official pinned release asset with Apache-2.0 and upstream NOTICE preserved | Current reference implementation |
| Antigravity | Not redistributed by default; explicit vendor-sourced installation is planned | Not yet supported |
| Claude Code | Not installed or advertised | Future research path only |
| OpenCode | Independent project based on its official image | Outside this stack |

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
