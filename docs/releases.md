# Image release channels

## Edge

`edge` is the public experimental development channel for the current `main` branch.

The **Publish edge AMD64** workflow runs automatically after relevant image, runtime or version changes merge into `main`. It can also be started manually from `main`. Each run builds and scans one final Remote Dev digest and promotes it to canonical `remote-dev` tags and the `codex-remote-dev` compatibility tags. The compatibility package is not a second build and does not duplicate immutable image content.

Generic and TrueNAS Compose use `REMOTE_DEV_IMAGE`, defaulting to:

```text
ghcr.io/experience83/remote-dev:edge-amd64
```

The current stack instantiates the same image reference twice:

- `launcher`, the stateless primary browser entry on port 7680;
- `codex`, the independently authenticated ttyd endpoint on port 7681.

The launcher navigates to Codex and does not proxy terminal traffic. It receives no agent workspace, state or credentials. Optional launcher Basic authentication remains available through `compose/launcher-auth.yml`.

Persistent data follows the canonical role-neutral contract:

```text
REMOTE_DEV_DATA_ROOT/
├── workspaces/codex/
├── state/codex/{agent,gh,git,ssh}/
└── secrets/codex/web_password.txt
```

The parent data root is never mounted wholesale. Required bind sources use `create_host_path: false`, so operators must create the intended paths before deploying.

The data layout has no compatibility alias or automatic migration because no stable release or external installed base exists yet. Image-name compatibility remains separate: `CODEX_IMAGE` and the `codex-remote-dev` package continue throughout `v0.1.x`, with `REMOTE_DEV_IMAGE` taking precedence.

Public container-registry images can be pulled without authentication. The `sha-...` tag identifies the source commit, but container tags remain mutable in GHCR. Record and deploy the published `sha256:...` digest when immutable reproduction is required.

The workflow refuses to publish from a branch other than `main`.

Stable upstream releases are checked daily. The updater tracks final Codex, GitHub CLI, ttyd, mise and uv releases plus maintenance updates within the selected Python 3.14, Node 24 LTS and npm 12 lines. Ubuntu LTS tag and digest updates remain managed by Renovate.

The default image does not install the system Bubblewrap package. On the supported TrueNAS profile, the Codex command launcher fixes `--sandbox danger-full-access`; the outer Codex container and its narrow mounts are the security boundary. Autonomous and guarded approval modes do not change that boundary.

> [!WARNING]
> Public availability does not make `edge` stable or production-ready. Breaking changes are possible, and neither port 7680 nor port 7681 may be exposed directly to the Internet.

## Stable

Stable publication is triggered only by an exact semantic version tag:

```text
vMAJOR.MINOR.PATCH
```

The tagged commit must belong to `main`. Pre-release tags are intentionally rejected by the stable workflow.

Both publication workflows push candidates by digest, scan those exact digests and only then promote public tags. A fixable `CRITICAL` vulnerability blocks promotion. Critical findings without a known fix remain visible in retained reports.

## Promotion checklist

Before creating a stable version tag:

1. The AMD64 build, runtime smoke tests and fixable-critical vulnerability gate pass on `main`.
2. Canonical and compatibility image tags resolve to the same tested digest.
3. The stack has been deployed on TrueNAS from an exact published digest.
4. Docker reports launcher and Codex using the same image digest.
5. The TrueNAS portal opens the launcher on port 7680.
6. The launcher opens on the trusted private endpoint and preserves origin/CSP behavior.
7. Selecting Codex navigates to the independent authenticated endpoint without exposing credentials.
8. The launcher has no mounts and no Docker/Podman socket.
9. Neither service uses host networking, privileged mode or added capabilities.
10. The canonical data directories were created deliberately and no unexpected host directory was generated.
11. Workspace, agent state, GitHub CLI state, Git configuration and SSH state persist across stop/start and recreation.
12. Codex device-code login persists across recreation.
13. GitHub CLI login, clone, push and pull-request creation have been verified.
14. Autonomous and guarded Codex behavior has been tested on the target TrueNAS host.
15. Optional `WEB_PASSWORD_FILE` authentication has been validated under #69.
16. The changelog has a dated release section.
17. Third-party licenses and notices are complete.
18. The repository contains no credentials, personal paths or private infrastructure details.

Cross-service hardening/canary work and optional-agent validation remain separate gates before the architecture is described as complete. Optional SMB/ACL testing is tracked under #71.

## Rollback

Do not depend exclusively on moving tags. Record the tested image digest, its `sha-...` tag and source commit. Set:

```text
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<digest>
```

and recreate all stack services. Existing `v0.1.x` deployments may continue setting the image-name alias `CODEX_IMAGE` when `REMOTE_DEV_IMAGE` is unset; both image references identify the same promoted digest.

The canonical data layout is independent from the image tag. Rollback must not broaden mounts or copy state automatically. Keep a backup or snapshot before manually moving experimental data into the new paths.
