# Tool matrix

## Included in the shared base

| Area | Included |
|---|---|
| Shell | bash, tmux, ttyd, tini, nano, less, fzf |
| Git | git, git-lfs, openssh-client, GitHub CLI |
| Search/files | ripgrep, fd, jq, rsync, zip/unzip, tar/gzip, patch |
| Build | build-essential, make, pkg-config and common native libraries |
| Python | Python 3.14, uv |
| JavaScript | Node 24, npm |
| Tool manager | mise |
| Checks | shellcheck |

## Explicitly deferred

- Additional Python versions
- Additional Node versions
- Rust, Go, Java, Ruby, PHP, Swift, Erlang and Elixir
- Home Assistant helpers
- Browser automation and Playwright
- Office parsing and VBA tools
- actionlint, zizmor, Biome and html-validate
- Docker CLI and Docker socket access
- MCP servers and skills

Additions should be driven by real repositories or community requests and measured for size, security and maintenance cost.
