# Architecture v0.1

## Locked decisions

- OpenCode remains independent and continues deriving from its official image.
- This repository builds a shared Ubuntu 26.04 LTS development base.
- The first child image is Codex Remote Dev.
- A future Antigravity child may reuse the same base, but is out of scope for v0.1.
- The runtime user is root to avoid fighting toolchain permissions.
- The first supported architecture is AMD64.
- The primary interface is the official Codex TUI exposed through ttyd and tmux.
- GitHub CLI is a core dependency, not an optional add-on.
- Stable images are updated by rebuilding and replacing the image, never by mutating packages in a running container.

## Image graph

```text
ubuntu:26.04
└── remote-dev-base
    ├── Git, Git LFS, GitHub CLI, SSH
    ├── Python 3.14, Node 24, uv, mise
    ├── build tools and common shell utilities
    ├── ttyd, tmux and tini
    └── codex-remote-dev
        ├── official Codex CLI binary
        ├── web entrypoint
        ├── menu and diagnostics
        └── Codex-specific persistent paths
```

## Persistence

Persistent:

- `/workspace`
- `/root/.codex`
- `/root/.config/gh`
- `/root/.config/git`
- `/root/.ssh`

Not mounted as a whole:

- `/root`
- `/opt`
- `/usr/local`

This prevents volumes from hiding image-provided tools.
