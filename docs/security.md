# Security model

This is a single-user development appliance, not a multi-tenant service.

## Root decision

The container intentionally runs as root. Root is constrained to the container and to the paths mounted into it. Any person who reaches the web terminal can operate everything accessible to that container.

## Supported isolation boundary

The supported TrueNAS security boundary is the outer Docker container. The default image does not install Bubblewrap and does not enable deprecated Landlock as a fallback. The supported launcher starts Codex with `--sandbox danger-full-access` so it does not attempt an unsupported nested sandbox.

`danger-full-access` describes the Codex inner sandbox only. It does not add Docker privileges, `SYS_ADMIN`, host mounts, unconfined AppArmor/seccomp profiles or a Docker socket. The container's normal isolation and narrow mounts remain the security boundary.

The launcher also sets `--ask-for-approval untrusted`. Commands that Codex does not classify as trusted require approval, as validated on TrueNAS with read-only and write-command probes. Approval prompts are not a sandbox and must not be described as one: after approval, Codex can access every path and credential mounted into that service, and some built-in editing operations may not map to a shell-command prompt.

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

## Codex permissions

The default launcher fixes the supported TrueNAS policy to outer-container isolation plus `untrusted` approvals. The menu, resume action and `START_MODE=codex` all use the same launcher so they cannot silently diverge. Users can still start Codex manually from the shell with different flags, but doing so is outside the supported default and may weaken the approval behavior.
