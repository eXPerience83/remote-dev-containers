# Security model

This is a single-user development appliance, not a multi-tenant service.

## Root decision

The container intentionally runs as root. Root is constrained to the container and to the paths mounted into it. Any person who reaches the web terminal can operate everything accessible to that container.

## Supported isolation boundary

The supported TrueNAS security boundary is the outer Docker container. The default image does not install the system Bubblewrap package or executable and does not enable deprecated Landlock as a fallback. The pinned Codex release may carry its own packaged Bubblewrap fallback, but the supported launcher starts Codex with `--sandbox danger-full-access` so that fallback is not invoked and no unsupported nested sandbox is attempted.

`danger-full-access` describes the Codex inner sandbox only. It does not add Docker privileges, `SYS_ADMIN`, host mounts, unconfined AppArmor/seccomp profiles or a Docker socket. The container's normal isolation and narrow mounts remain the security boundary.

Approval prompts are never a sandbox or an isolation boundary. Whether the selected approval policy is `never` or `untrusted`, Codex can access every path and credential mounted into its service. The guarded policy adds command-by-command friction in cases classified as untrusted; it does not hide mounted state, and some built-in editing operations may not map to a shell-command prompt.

Separate agent services must receive separate narrow mounts. The outer-container boundary protects one agent service from state that is not mounted into it; it does not protect files or credentials from a person who already controls that service's terminal.

## Required controls

- Do not expose port 7681 directly to the public Internet.
- Use LAN, Tailscale, WireGuard, or an authenticated HTTPS reverse proxy.
- Configure a strong ttyd password through a mounted secret file.
- Never mount `/var/run/docker.sock`.
- Never use `privileged: true`, host PID, or host networking.
- Mount only the documented persistent directories.
- Treat `/root/.codex/auth.json`, GitHub credentials and SSH keys as secrets.
- Keep `no-new-privileges:true` enabled.

## Codex approval modes

The project-owned launcher always fixes the inner sandbox to `danger-full-access` and accepts only these reviewed modes:

- `autonomous` maps to `--ask-for-approval never` and is the supported default;
- `guarded` maps to `--ask-for-approval untrusted` and remains available when the operator wants confirmation friction.

Configure the permanent service value with:

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# or: guarded
```

The menu can select either mode for one new start or resume operation without rewriting the deployment setting. The equivalent validated CLI is:

```bash
run-codex --approval-mode autonomous
run-codex --approval-mode guarded resume
```

Precedence is:

1. an explicit validated `--approval-mode` for that launch;
2. `REMOTE_DEV_CODEX_APPROVAL_MODE` from the deployment;
3. the built-in `autonomous` default.

`run-codex --print-policy`, the menu and diagnostics report the selected project mode, exact upstream approval policy and selection source. Invalid values fail before Codex starts.

The launcher continues to reject raw Codex sandbox/approval flags, shortcut aliases and relevant `config.toml` overrides. Arguments after `--` are passed literally and are not interpreted as project policy controls. Users can still invoke the raw Codex binary manually from a shell, but doing so is outside the supported launcher contract.

Autonomous mode does not grant any access beyond the container's existing mounts, network and credentials. It is appropriate here only because this project is designed as a single-user appliance whose terminal operator is already trusted for that individual container. Do not use autonomous mode to justify broader mounts or weaker Docker/TrueNAS controls.
