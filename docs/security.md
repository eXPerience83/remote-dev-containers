# Security model

This is a single-user development appliance, not a multi-tenant service.

## Root decision

The container intentionally runs as root. Root is constrained to the container and to the paths mounted into it. Any person who reaches the web terminal can operate everything accessible to that container.

## Supported isolation boundary

The supported TrueNAS security boundary is the outer Docker container. The default image does not install Bubblewrap and does not enable deprecated Landlock as a fallback. Diagnostics report an inner sandbox only after a positive runtime test; otherwise they state that it is unavailable.

When Codex cannot sandbox a command, its normal approval flow remains the control before execution. The project does not add privileged mode, `SYS_ADMIN`, unconfined AppArmor/seccomp profiles, host security changes or a Docker socket to make a nested sandbox start.

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

The image does not force an unrestricted approval policy. Users choose Codex permission profiles in the official TUI. Community defaults must not silently enable a bypass or YOLO mode.
