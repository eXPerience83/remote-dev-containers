# Security model

Remote Dev is a single-user development appliance, not a multi-tenant service.

## Root decision

Agent containers intentionally run as root. Root is constrained to that container and to the paths mounted into it. Anyone who reaches an agent terminal can operate everything accessible to that service.

The launcher is different: production Compose starts it directly as UID/GID `65532`, with no supplementary groups, no mounts and no added capabilities after `cap_drop: [ALL]`. It therefore does not need a root startup phase merely to obtain its browser password.

The launcher runtime still defensively drops to UID/GID `65532` if somebody invokes it manually as root outside the reviewed Compose profile, but the supported deployment no longer relies on that transition.

## Browser authentication contract

Browser endpoints use one password-delivery mechanism: `WEB_PASSWORD`.

- Codex receives its own non-empty value.
- Antigravity receives a distinct non-empty value when enabled.
- Optional launcher Basic authentication uses a separate launcher value mapped to its own `WEB_PASSWORD`.
- Agent endpoints fail closed when `WEB_PASSWORD` is empty unless that specific endpoint deliberately sets `ALLOW_INSECURE_WEB=1`. The reviewed Codex and Antigravity Compose defaults keep that override at `0`.
- The normal navigation-only launcher is the reviewed exception: base Compose profiles explicitly set `ALLOW_INSECURE_WEB=1` only for an already protected private endpoint. The optional launcher-auth override sets it back to `0` and requires its own password.
- No browser password is persisted below `REMOTE_DEV_DATA_ROOT`, mounted from `/run/secrets`, or selected from multiple runtime sources.

A sufficiently privileged TrueNAS/Docker administrator can inspect deployment configuration and container metadata. Host root/admin is inside the trust boundary; moving an application password to another host file would not create an administrator-secrecy boundary for this product. The supported protection is private network exposure plus role/container/mount isolation.

Passwords must be non-empty single-line values. Runtime validation rejects carriage returns/newlines rather than logging or transforming them. Never print password values, lengths, hashes or credential-derived material in diagnostics, tests or issue evidence.

For agent roles, startup copies the configured password into a non-exported shell variable and removes `WEB_PASSWORD` from the child-process environment before running external startup helpers or executing ttyd. ttyd still receives the credential it requires for Basic authentication; this reduces incidental inheritance by unrelated child tools and terminal sessions, but it does not hide deployment configuration from the trusted host administrator.

## Launcher boundary

The launcher and Codex run as separate containers from the same immutable image. Sharing image layers does not share mutable state or credentials.

The launcher:

- receives no agent workspace, state, GitHub CLI configuration, Git configuration, SSH state or agent password;
- receives no Docker or Podman socket;
- performs no container-management operation;
- serves only fixed reviewed navigation;
- does not proxy terminal HTTP or WebSocket traffic;
- requires no password by default on localhost/LAN/Tailscale deployments;
- supports optional configuration-backed Basic authentication through `compose/launcher-auth.yml`;
- validates route inputs, matching origins and URL paths;
- sends a restrictive Content Security Policy;
- rejects state-changing HTTP methods;
- exposes a secret-free health endpoint.

The launcher remains mount-free with or without optional authentication. It never embeds an agent password or forwards an Authorization header, and each agent endpoint authenticates independently.

## Outer-container isolation

The supported TrueNAS security boundary is the outer agent container. The default image does not install system Bubblewrap and the project-owned Codex launcher fixes `--sandbox danger-full-access` so no unsupported nested sandbox is attempted.

`danger-full-access` describes only the Codex inner sandbox. It does not add Docker privileges, capabilities, host mounts, unconfined profiles or a container-engine socket.

Approval prompts are not a sandbox. Autonomous and guarded modes can access every path and credential mounted into Codex. Guarded mode adds confirmation friction only.

## Enforced container hardening

Both deployment files make the launcher, Codex and Antigravity root filesystems read-only and apply `cap_drop: [ALL]`. The launcher restores no capabilities and runs directly as UID/GID `65532`; Codex and Antigravity restore only their exact reviewed agent capability minimum. All roles retain `no-new-privileges`, configure no supplementary groups, and use PID ceilings of `64` for the launcher and `1024` for each agent.

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

Docker also provides each role a private per-container `/dev/shm` shared-memory tmpfs. Codex and Antigravity retain their configured `shm_size: 256m` ceilings. `/dev/shm` is transient rather than persistent state and is not shared between role containers. Codex `/run` deliberately remains executable for the bounded `/run/remote-dev-codex-update` staging contract and transient Context7 device-login tooling. Its `1536m` ceiling covers the published 300 MiB package and 1 GiB unpacked limits plus working overhead; tmpfs size is a ceiling, not preallocated memory. Antigravity installation/update staging remains in its private persistent runtime state rather than moving into `/tmp`.

Normal Codex and Antigravity child sessions receive `/workspace/.remote-dev-tmp/tmp` through `TMPDIR`, `TMP` and `TEMP`, plus sibling `uv-cache`, `npm-cache` and `pip-cache` directories through their package-manager variables. Startup opens and validates the fixed workspace path without following symlinks, rejects unexpected object types or ownership, and enforces mode `0700` only on the fixed root and children. It does not recursively inspect, trust, clean, chmod or chown cache contents. The tree is untrusted development state, persists with that role's already-private workspace bind and is not shared across roles. It is not a trusted staging location.

Trust-sensitive managers retain their own contracts even when invoked with hostile inherited temporary variables: Codex updates and Context7 device login use fixed private roots under `/run`; Antigravity install, admission and publication use canonical private runtime state; Context7 atomic configuration writes stage beside their target; and Antigravity OAuth retains its explicit small `/tmp` files. Remote Dev-owned Codex and GitHub credential-onboarding commands explicitly restore `TMPDIR`, `TMP` and `TEMP` to `/tmp` and remove the three development cache variables. The launcher receives neither a workspace nor development-scratch defaults.

Everything in `/tmp` and `/run`, including tmux sockets and intentionally small internal temporary files, disappears when a container is recreated. Credentials, configuration, workspaces, workspace-backed development scratch and admitted runtimes persist only through the existing role-private binds. Browser-terminal passwords are deployment configuration and are not part of this persistent-data tree.

## Canonical persistent-data boundary

All generic Compose persistence is derived from one administrative root, `REMOTE_DEV_DATA_ROOT`, but that root is never mounted into a container.

The Codex service receives only:

```text
workspaces/codex    -> /workspace
state/codex/agent   -> /root/.codex
state/codex/runtime -> /root/.local/share/remote-dev/codex-runtime
state/codex/gh      -> /root/.config/gh
state/codex/git     -> /root/.config/git
state/codex/ssh     -> /root/.ssh
```

The experimental Antigravity service uses only its own corresponding private children. Its project configuration mount is narrowly scoped as `state/antigravity/config -> /root/.gemini/config` and remains separate from `state/antigravity/vendor -> /root/.gemini/antigravity-cli`. Codex and the launcher receive neither source nor target, and the stack never makes all of `/root/.gemini` writable.

The base launcher remains free of agent mounts. Future agent services must receive their own separate child paths and credentials.

The authoritative host check is `scripts/preflight-data-layout.py`. It rejects missing paths and symlinks before deployment. It intentionally validates persistent storage layout only; browser-password validity is enforced by the endpoint runtime. Compose also requests `create_host_path: false` for every persistent bind, but this is defense-in-depth because some Compose implementations may ignore that option at runtime.

The optional Codex runtime stays separate from `CODEX_HOME` and is mounted only into the Codex service. After an explicit confirmed action, the updater allows only reviewed HTTPS URL origins, including redirects, and verifies TLS against the system CA bundle; a configured HTTP(S) proxy may act as an intermediary, and `CODEX_CA_CERTIFICATE` may add an operator-supplied CA to that verification. It verifies the release digest, package identity and bounded compatibility probes before publication, and records file identities for later local verification. Missing, damaged or modified runtime state is rejected in favor of the immutable bundled Codex fallback; launcher and Antigravity do not receive this runtime mount.

The project does not automatically copy, migrate, delete or symlink experimental data. Automatic migration would risk credential exposure or ambiguous ownership. Existing experimental state must be moved or recreated manually after backup.

Optional SMB sharing is outside the core security contract and tracked under #71. Only the workspace boundary may be considered for sharing; `state` must never be exposed through SMB.

## Required controls

- Do not expose ports 7680, 7681 or 7682 directly to the public Internet.
- Bind the password-free launcher only to localhost, a trusted LAN, Tailscale or WireGuard.
- Keep `ALLOW_INSECURE_WEB=0` for agent services unless a specific endpoint is deliberately placed behind another reviewed private authentication boundary.
- Keep every agent terminal independently authenticated with a strong, distinct password.
- Use a distinct launcher password when the optional authentication overlay is enabled.
- Protect a generic Compose `.env` containing browser passwords from other host users, for example with mode `0600` on POSIX systems, and keep it out of version control.
- Keep credentials out of navigation URLs, diagnostics, logs and tests; remember that host administrators can inspect deployment configuration.
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
- `guarded`, which marks only the active project untrusted through an in-memory launch override. Codex then prompts for commands unless an explicit exec-policy rule allows them; trusted-project `on-request` is not this guarded contract.

Configure the permanent service value with:

```dotenv
REMOTE_DEV_CODEX_APPROVAL_MODE=autonomous
# or: guarded
```

The menu can select another mode for one start or resume. That override is consumed before invocation and does not rewrite the deployment setting.

The command launcher rejects raw sandbox/approval flags, profiles and project-trust configuration overrides before Codex starts. The guarded override is not written to the user's `config.toml`, so another project or a later autonomous launch cannot inherit it. Users may invoke the raw Codex binary manually from a shell, but that is outside the supported launcher contract. Approval prompts do not change the outer-container isolation boundary.

## Optional vendor agents

Antigravity, Claude Code and other proprietary agents are not bundled or downloaded by the current image. An optional integration must:

- use an explicit user action;
- download from an official vendor-controlled source;
- pass dedicated legal/package inspection;
- keep credentials and state inside that agent's private mounts;
- document vendor terms, privacy, telemetry, updates and uninstall behavior;
- never weaken the outer-container boundary.

A missing optional agent must remain unavailable and must not download silently during startup.
