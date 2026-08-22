# Security model

Remote Dev is a single-user development appliance, not a multi-tenant service.

## Root decision

Agent containers intentionally run as root. Root is constrained to that container and to the paths mounted into it. Anyone who reaches an agent terminal can operate everything accessible to that service.

The launcher starts with UID 0 only long enough to read an optional configured password. Before binding its HTTP server, it clears supplementary groups and drops permanently to UID/GID `65532`. The launcher has no agent-state mounts.

The launcher starts with only `DAC_READ_SEARCH`, `SETGID` and `SETUID`. `DAC_READ_SEARCH` lets it read a mode-`0600` file-backed password whose host ownership Compose preserves; `SETGID` and `SETUID` perform the permanent drop. After the drop, the network-facing process has no supplementary groups and zero effective capabilities.

## Launcher boundary

The launcher and Codex run as separate containers from the same immutable image. Sharing image layers does not share mutable state or credentials.

The launcher:

- receives no agent workspace, state, GitHub CLI configuration, Git configuration, SSH state or agent password;
- receives no Docker or Podman socket;
- performs no container-management operation;
- serves only fixed reviewed navigation;
- does not proxy terminal HTTP or WebSocket traffic;
- requires no password by default on localhost/LAN/Tailscale deployments;
- supports optional file-backed Basic authentication only through `compose/launcher-auth.yml`;
- validates route inputs, matching origins and URL paths;
- sends a restrictive Content Security Policy;
- rejects state-changing HTTP methods;
- exposes a secret-free health endpoint.

The base launcher has no mounts. The optional authentication overlay adds only its dedicated read-only launcher password secret. The launcher never embeds a password or forwards an Authorization header, and each agent endpoint authenticates independently.

## Outer-container isolation

The supported TrueNAS security boundary is the outer agent container. The default image does not install system Bubblewrap and the project-owned Codex launcher fixes `--sandbox danger-full-access` so no unsupported nested sandbox is attempted.

`danger-full-access` describes only the Codex inner sandbox. It does not add Docker privileges, capabilities, host mounts, unconfined profiles or a container-engine socket.

Approval prompts are not a sandbox. Autonomous and guarded modes can access every path and credential mounted into Codex. Guarded mode adds confirmation friction only.

## Enforced container hardening

Both deployment files make the launcher, Codex and Antigravity root filesystems read-only, drop every capability and then restore only the exact role minimum. They retain `no-new-privileges`, do not configure supplementary groups, and set PID ceilings of `64` for the launcher and `1024` for each agent.

Codex and Antigravity keep the established root-agent model because the authenticated terminal is trusted for that one service and must initialize and harden role-private bind mounts whose host ownership can differ. Their exact capability whitelist is:

- `CHOWN` for ownership of fixed unprivileged candidate/login staging;
- `DAC_OVERRIDE` for root access to the service's narrow private bind mounts when host UID ownership differs;
- `FOWNER` for `chmod` and persistent-state hardening on those mounts;
- `KILL` so bounded supervisors can terminate a candidate running as another UID;
- `SETGID` and `SETUID` to execute reviewed candidate/login probes as UID/GID `65534` with supplementary groups cleared.

All other capabilities are dropped. In particular, no role receives `SYS_ADMIN`, `NET_ADMIN`, `NET_RAW`, `MKNOD`, `SETPCAP`, `SETFCAP`, `SYS_CHROOT` or `NET_BIND_SERVICE`.

The application-managed transient writable filesystems are private per-container tmpfs mounts:

| Role | `/tmp` | `/run` |
| --- | --- | --- |
| launcher | `rw,noexec,nosuid,nodev,size=64m,mode=1777` | `rw,noexec,nosuid,nodev,size=16m,mode=755` |
| Codex | `rw,noexec,nosuid,nodev,size=512m,mode=1777` | `rw,exec,nosuid,nodev,size=1536m,mode=755` |
| Antigravity | `rw,noexec,nosuid,nodev,size=512m,mode=1777` | `rw,noexec,nosuid,nodev,size=64m,mode=755` |

Docker also provides each role a private per-container `/dev/shm` shared-memory tmpfs. Codex and Antigravity retain their configured `shm_size: 256m` ceilings. `/dev/shm` is transient rather than persistent state and is not shared between role containers. Codex `/run` deliberately remains executable for the bounded `/run/remote-dev-codex-update` staging contract and transient Context7 device-login tooling. Its `1536m` ceiling covers the published 300 MiB package and 1 GiB unpacked limits plus working overhead; tmpfs size is a ceiling, not preallocated memory. npm and uv caches use narrow paths below the existing `/tmp` tmpfs and are transient. Antigravity installation/update staging remains in its private persistent runtime state rather than moving into `/tmp`.

Everything in `/tmp` and `/run`, including tool caches and tmux sockets, disappears when a container is recreated. Credentials, configuration, workspaces and admitted runtimes persist only through the existing role-private binds. Generic Compose file-backed secrets remain read-only below `/run/secrets`; the TrueNAS reference keeps its distinct environment-backed terminal-password mode.

## Canonical persistent-data boundary

All generic Compose persistence is derived from one administrative root, `REMOTE_DEV_DATA_ROOT`, but that root is never mounted into a container.

The Codex service receives only:

```text
workspaces/codex               -> /workspace
state/codex/agent              -> /root/.codex
state/codex/runtime            -> /root/.local/share/remote-dev/codex-runtime
state/codex/gh                 -> /root/.config/gh
state/codex/git                -> /root/.config/git
state/codex/ssh                -> /root/.ssh
secrets/codex/web_password.txt -> /run/secrets/web_password
```

The base launcher remains free of agent mounts. Future agent services must receive their own separate child paths and credentials.

The authoritative host check is `scripts/preflight-data-layout.py`. It rejects missing paths, symlinks, a missing or empty password file, and password permissions broader than `0600` on POSIX hosts before deployment. Compose also requests `create_host_path: false` for every persistent bind, but this is defense-in-depth because some Compose implementations may ignore that option at runtime.

The optional Codex runtime stays separate from `CODEX_HOME` and is mounted only into the Codex service. After an explicit confirmed action, the updater allows only reviewed HTTPS URL origins, including redirects, and verifies TLS against the system CA bundle; a configured HTTP(S) proxy may act as an intermediary, and `CODEX_CA_CERTIFICATE` may add an operator-supplied CA to that verification. It verifies the release digest, package identity and bounded compatibility probes before publication, and records file identities for later local verification. Missing, damaged or modified runtime state is rejected in favor of the immutable bundled Codex fallback; launcher and Antigravity do not receive this runtime mount.

The project does not automatically copy, migrate, delete or symlink experimental data. Automatic migration would risk credential exposure or ambiguous ownership. Existing experimental state must be moved or recreated manually after backup.

Optional SMB sharing is outside the core security contract and tracked under #71. Only the workspace boundary may be considered for sharing; `state` and `secrets` must never be exposed through SMB.

## Required controls

- Do not expose ports 7680 or 7681 directly to the public Internet.
- Bind the password-free launcher only to localhost, a trusted LAN, Tailscale or WireGuard.
- Keep every agent terminal independently authenticated with a strong password.
- Use a distinct launcher password when the optional authentication overlay is enabled.
- Keep credentials out of navigation URLs, diagnostics, logs, tests and rendered environment output.
- Keep agent data and credentials out of the launcher.
- Do not mount Docker or Podman sockets.
- Do not use `privileged: true`, host PID or host networking, and do not add capabilities beyond the exact role whitelists above.
- Do not mount the parent data root, host root, `/root`, `/home`, `/mnt`, `/opt` or `/usr/local` wholesale.
- Treat Codex authentication, GitHub credentials and SSH keys as secrets.
- Keep `no-new-privileges:true` enabled on every service.
- Keep writable workspaces and credentials private per agent service.
- Run the canonical host-path preflight before every first deployment or path change.

## Codex approval modes

The project-owned Codex command launcher accepts only:

- `autonomous`, mapped to `--ask-for-approval never`;
- `guarded`, mapped to `--ask-for-approval untrusted`.

Configure the permanent service value with:

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# or: guarded
```

The menu can select another mode for one start or resume. That override is consumed before invocation and does not rewrite the deployment setting.

The command launcher rejects raw sandbox/approval flags and relevant configuration overrides before Codex starts. Users may invoke the raw Codex binary manually from a shell, but that is outside the supported launcher contract.

## Optional vendor agents

Antigravity, Claude Code and other proprietary agents are not bundled or downloaded by the current image. An optional integration must:

- use an explicit user action;
- download from an official vendor-controlled source;
- pass dedicated legal/package inspection;
- keep credentials and state inside that agent's private mounts;
- document vendor terms, privacy, telemetry, updates and uninstall behavior;
- never weaken the outer-container boundary.

A missing optional agent must remain unavailable and must not download silently during startup.
