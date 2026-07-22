# Security model

This is a single-user development appliance, not a multi-tenant service.

## Root decision

The container intentionally runs as root. Root is constrained to the container and to the paths mounted into it. Any person who reaches the web terminal can operate everything accessible to that container.

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
