# Security model

This is a single-user development appliance, not a multi-tenant service.

## Root decision

The Codex container intentionally runs as root. Root is constrained to that container and to the paths mounted into it. Any person who reaches the Codex terminal can operate everything accessible to that service.

The launcher container starts with UID 0 only long enough to read its root-readable password secret. Before binding its HTTP server or accepting requests, the launcher clears supplementary groups and drops permanently to UID/GID `65532`. Automated tests verify the effective serving UID. The launcher has no agent-state mounts, so this startup step does not grant access to Codex data.

## Launcher boundary

The supported stack starts an authenticated launcher service and an independently authenticated Codex service from the same immutable image. Sharing image layers does not share mutable state or credentials.

The launcher:

- receives no Codex workspace, agent state, GitHub CLI configuration, Git configuration or SSH mounts;
- receives no Codex terminal password or other agent web credential;
- receives no Docker or Podman socket and performs no container-management operation;
- serves only a fixed navigation page for reviewed, declared services;
- does not relay or proxy the Codex terminal's HTTP or WebSocket traffic;
- uses HTTP Basic authentication from its own mounted launcher-password secret;
- validates DNS names and IP literals and rejects a destination host containing an embedded port;
- restricts configured paths to safe RFC 3986 URL-path characters before embedding them into the page;
- checks that an `Origin` header, when present, matches the request host;
- sends a restrictive Content Security Policy and rejects state-changing HTTP methods;
- exposes an unauthenticated, secret-free health endpoint.

The launcher calculates the Codex URL from validated fixed routing values and, by default, the browser's current hostname and scheme. It never embeds a password or forwards an Authorization header. The Codex endpoint uses a separate mounted password secret, authenticates independently and may produce a second browser challenge.

Port `7680` is the normal launcher entry point. Port `7681` remains the direct Codex endpoint used after navigation and for troubleshooting. Neither port should be exposed directly to the public Internet.

## Supported Codex isolation boundary

The supported TrueNAS security boundary for Codex is its outer Docker container. The default image does not install the system Bubblewrap package or executable and does not enable deprecated Landlock as a fallback. The pinned Codex release may carry its own packaged Bubblewrap fallback, but the supported command launcher starts Codex with `--sandbox danger-full-access` so that fallback is not invoked and no unsupported nested sandbox is attempted.

`danger-full-access` describes the Codex inner sandbox only. It does not add Docker privileges, `SYS_ADMIN`, host mounts, unconfined AppArmor/seccomp profiles or a Docker socket. The container's normal isolation and narrow mounts remain the security boundary.

Approval prompts are never a sandbox or an isolation boundary. Whether the selected approval policy is `never` or `untrusted`, Codex can access every path and credential mounted into its service. The guarded policy adds command-by-command friction in cases classified as untrusted; it does not hide mounted state, and some built-in editing operations may not map to a shell-command prompt.

Separate future agent services must receive separate narrow mounts and separate web credentials. The outer-container boundary protects one agent service from state that is not mounted into it; it does not protect files or credentials from a person who already controls that service's terminal.

## Required controls

- Do not expose ports 7680 or 7681 directly to the public Internet.
- Use LAN, Tailscale, WireGuard, or an explicitly reviewed authenticated HTTPS design.
- Configure different strong passwords for launcher and Codex through their separate mounted secret files.
- Keep launcher and agent authentication independent; never place credentials in navigation URLs.
- Never mount an agent password, state or workspace into the launcher.
- Never mount Docker or Podman sockets, including `/var/run/docker.sock` or `/run/docker.sock`.
- Never use `privileged: true`, host PID, or host networking.
- Mount only the documented persistent directories into the Codex service.
- Treat `/root/.codex/auth.json`, GitHub credentials and SSH keys as secrets.
- Keep `no-new-privileges:true` enabled on both services.

## Codex approval modes

The project-owned Codex command launcher always fixes the inner sandbox to `danger-full-access` and accepts only these reviewed modes:

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

The command launcher continues to reject raw Codex sandbox/approval flags, shortcut aliases and relevant `config.toml` overrides. Arguments after `--` are passed literally and are not interpreted as project policy controls. Users can still invoke the raw Codex binary manually from a shell, but doing so is outside the supported launcher contract.

Autonomous mode does not grant any access beyond the Codex container's existing mounts, network and credentials. It is appropriate here only because this project is designed as a single-user appliance whose terminal operator is already trusted for that individual agent container. Do not use autonomous mode to justify broader mounts or weaker Docker/TrueNAS controls.
