# Image release channels

## Edge

`edge` is the public experimental development channel for the current `main` branch.

It is published manually through the **Publish edge AMD64** workflow and may change without notice. Each run publishes:

- `ghcr.io/experience83/remote-dev-base:edge-amd64`
- `ghcr.io/experience83/remote-dev-base:sha-<full-commit-sha>`
- `ghcr.io/experience83/codex-remote-dev:edge`
- `ghcr.io/experience83/codex-remote-dev:edge-amd64`
- `ghcr.io/experience83/codex-remote-dev:sha-<full-commit-sha>`

Public container-registry images can be pulled without authentication. Use the immutable `sha-...` tag when reproducing a specific test. Use `edge-amd64` only when intentionally following the latest development build.

The workflow refuses to publish from a branch other than `main`.

> [!WARNING]
> Public availability does not make `edge` stable or production-ready. Breaking changes are possible, and the ttyd port must not be exposed directly to the Internet.

## Stable

Stable publication is triggered only by an exact semantic version tag:

```text
vMAJOR.MINOR.PATCH
```

For example:

```text
v0.1.0
```

Stable publication produces versioned tags and updates the moving `stable`, `stable-amd64` and `latest` tags. Pre-release tags such as `v0.1.0-rc.1` are intentionally rejected by the stable workflow.

## Promotion checklist

Before creating a stable version tag:

1. The AMD64 build and runtime smoke tests pass on `main`.
2. The `edge` image has been deployed on TrueNAS.
3. Browser access, authentication and tmux reconnection have been verified.
4. Codex device-code login persists across recreation.
5. GitHub CLI login, clone, push and pull-request creation have been verified.
6. Codex sandbox and approval behavior have been tested.
7. The changelog has a dated release section.
8. Third-party licenses and notices are complete.
9. The repository contains no credentials, personal paths or private infrastructure details.

## Rollback

Do not depend exclusively on moving tags. Record the tested `sha-...` image tag and the source commit. To roll back, set `CODEX_IMAGE` to a previously validated immutable tag and recreate the container.
