# Image release channels

## Edge

`edge` is the public experimental development channel for the current `main` branch.

The **Publish edge AMD64** workflow runs automatically after relevant image, runtime or version changes merge into `main`. It can also be started manually from `main`. Each run publishes:

- `ghcr.io/experience83/remote-dev-base:edge-amd64`
- `ghcr.io/experience83/remote-dev-base:sha-<full-commit-sha>`
- `ghcr.io/experience83/codex-remote-dev:edge`
- `ghcr.io/experience83/codex-remote-dev:edge-amd64`
- `ghcr.io/experience83/codex-remote-dev:sha-<full-commit-sha>`

Public container-registry images can be pulled without authentication. The `sha-...` tag identifies the source commit, but container tags remain mutable in GHCR. Record and deploy the published `sha256:...` digest when immutable reproduction is required. Use `edge-amd64` only when intentionally following the latest development build.

The workflow refuses to publish from a branch other than `main`.

Stable upstream releases are checked daily. The updater tracks final Codex, GitHub CLI, ttyd, mise and uv releases plus maintenance updates within the selected Python 3.14, Node 24 LTS and npm 12 lines. It updates versions and architecture-specific hashes together and opens or refreshes a pull request; it never changes public image tags directly. Ubuntu LTS tag and digest updates remain managed by Renovate. Once an update PR passes the required build, runtime checks, vulnerability gate and review and is merged, the edge publication workflow builds and publishes the updated image.

The default image does not install Bubblewrap. On the supported TrueNAS profile, the outer container is the security boundary and Codex requests explicit approval when it cannot sandbox a command. Diagnostics report the inner-sandbox state separately and must not infer protection from package presence. The supported deployment does not enable privileged mode, `SYS_ADMIN`, unconfined security profiles or host changes merely to create a nested sandbox.

APT package resolution follows the current security revisions available from the selected Ubuntu repositories rather than pinning exact revisions that may disappear after being superseded. APT resolution is therefore not claimed to be bit-for-bit reproducible; completed images are covered by smoke tests and Trivy before public tags are promoted.

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

The tagged commit must belong to the history of `main`; a semantic-version tag placed on an unrelated branch is rejected. Stable publication produces versioned tags and updates the moving `stable`, `stable-amd64` and `latest` tags. Pre-release tags such as `v0.1.0-rc.1` are intentionally rejected by the stable workflow.

Both publication workflows first push untagged candidates by digest, scan those exact digests and only then promote them to public moving or versioned tags. A fixable `CRITICAL` vulnerability blocks tag promotion. Critical findings without a known fix remain visible in the retained JSON reports but do not fail the gate.

## Promotion checklist

Before creating a stable version tag:

1. The AMD64 build, runtime smoke tests and fixable-critical vulnerability gate pass on `main`.
2. The `edge` image has been deployed on TrueNAS.
3. Browser access, authentication and tmux reconnection have been verified.
4. Codex device-code login persists across recreation.
5. GitHub CLI login, clone, push and pull-request creation have been verified.
6. Codex approval behavior has been tested on the target TrueNAS host and diagnostics correctly report the outer-container isolation boundary and unavailable inner sandbox.
7. The changelog has a dated release section.
8. Third-party licenses and notices are complete.
9. The repository contains no credentials, personal paths or private infrastructure details.

## Rollback

Do not depend exclusively on moving tags. Record the tested image digest, its `sha-...` tag and the source commit. For an immutable rollback, set `CODEX_IMAGE` to `ghcr.io/experience83/codex-remote-dev@sha256:<digest>` and recreate the container.
