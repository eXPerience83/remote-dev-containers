# Decision log

## D001 — no codex-universal base

Rejected as the default because its multi-version toolchains make the image unusually large. It remains a reference and possible future `full` variant.

## D002 — shared lightweight base

Superseded by D008. The original decision proposed separate Codex and possible Antigravity child images sharing base layers. The accepted target now uses one final image digest for all fixed service roles.

## D003 — root runtime

Accepted for v0.1. Simplicity and predictable permissions take priority, with strict host-mount and network boundaries.

## D004 — AMD64 first

Accepted. AMD64 is the only stable target until native ARM64 builds and smoke tests are available.

## D005 — GitHub CLI is essential

Accepted. Authentication, cloning, pull requests and Actions diagnostics are expected parts of the environment.

## D006 — image rebuilds replace r14-style mutation

Accepted. The image contains required common tools. Runtime scripts diagnose and configure credentials but do not perform broad package upgrades.

## D007 — latest Ubuntu LTS base

Accepted. The project targets Ubuntu 26.04 LTS and will track later Ubuntu LTS releases through tested migration pull requests. Floating tags such as `latest` are not used in reproducible builds. The effective pin in `versions.env` and the Dockerfile default must remain synchronized and are checked before every build.

## D008 — one final image and one user-installed stack

Accepted. A user deploys one Remote Dev App or Compose stack. The launcher and each enabled agent service reference the same final image digest with a fixed role. Docker reuses the immutable layers instead of building or storing an independent toolchain image per agent.

This rejects both a single container holding every agent's private state and several manually maintained TrueNAS Apps, one per agent.

## D009 — one isolated service per agent

Accepted. Codex, Antigravity and any future Claude integration run in separate services. Each agent service has its own workspace or worktree, authentication, configuration, history, GitHub CLI state, Git configuration, SSH keys and integration credentials.

The parent data directory and broad home or tool directories are never mounted wholesale. Sharing a writable checkout between agents is not the default.

## D010 — the launcher is not a container control plane

Accepted. The launcher exposes the primary user entry point and routes only to fixed services declared by the stack. It receives neither the Docker socket nor agent credentials and does not create privileged child containers dynamically.

Agent services may remain running but idle so selecting a tool requires no container-management capability.

## D011 — optional proprietary agents use explicit vendor-sourced installation

Accepted. Optional proprietary agents are installed or updated only by an explicit reviewed action from an official vendor-controlled source unless redistribution rights are confirmed and documented.

A missing optional agent is reported as unavailable and is never downloaded silently during normal startup. Claude Code remains a future path until a dedicated implementation and validation decision is made.

## D012 — outer containers are the supported TrueNAS isolation boundary

Accepted as the baseline. The project does not weaken TrueNAS or Docker with privileged mode, `SYS_ADMIN`, unconfined profiles, host-root mounts or Docker socket access to force a nested sandbox.

An inner Bubblewrap, Landlock, nsjail or similar sandbox is reported as active only after a positive runtime test. The package-level Bubblewrap decision and the exact user-facing diagnostics are tracked by issue #36.
