# Image release channels

## Edge

`edge` is the public experimental development channel for the current `main` branch.

The **Publish edge AMD64** workflow runs automatically after relevant image, runtime or version changes merge into `main`. It can also be started manually from `main`. Each run builds and scans one final Remote Dev digest and promotes it to:

- canonical package:
  - `ghcr.io/experience83/remote-dev:edge`
  - `ghcr.io/experience83/remote-dev:edge-amd64`
  - `ghcr.io/experience83/remote-dev:sha-<full-commit-sha>`
- compatibility package, pointing to the same digest:
  - `ghcr.io/experience83/codex-remote-dev:edge`
  - `ghcr.io/experience83/codex-remote-dev:edge-amd64`
  - `ghcr.io/experience83/codex-remote-dev:sha-<full-commit-sha>`
- shared base package:
  - `ghcr.io/experience83/remote-dev-base:edge-amd64`
  - `ghcr.io/experience83/remote-dev-base:sha-<full-commit-sha>`

The edge workflow inspects every canonical and compatibility `edge`, `edge-amd64` and commit-addressed tag after promotion and verifies that each resolves to the exact digest that passed Trivy. The stable workflow performs the equivalent verification for every versioned, `stable`, `stable-amd64` and `latest` tag. The compatibility package is not a second build and does not duplicate the image's immutable content. PR candidate tags are intentionally published only under the canonical `remote-dev` package.

The canonical `remote-dev` package is public and is the deployment default. Generic and TrueNAS Compose use `REMOTE_DEV_IMAGE`, defaulting to `ghcr.io/experience83/remote-dev:edge-amd64`.

The current stack instantiates the same image reference twice:

- `launcher`, the primary authenticated browser entry on port 7680;
- `codex`, the independently authenticated ttyd endpoint on port 7681.

The launcher navigates to Codex and does not proxy terminal traffic. Its service receives no agent workspace or credential mounts. The Codex service retains the existing `CODEX_DATA_ROOT` layout until the later migration slice.

The `codex-remote-dev` compatibility package and `CODEX_IMAGE` variable remain supported throughout `v0.1.x` and will not be removed before `v0.2.0`. `REMOTE_DEV_IMAGE` takes precedence when both variables are set. A deprecation notice must appear in release notes before removal.

Public container-registry images can be pulled without authentication. The `sha-...` tag identifies the source commit, but container tags remain mutable in GHCR. Record and deploy the published `sha256:...` digest when immutable reproduction is required. Use `edge-amd64` only when intentionally following the latest development build.

The workflow refuses to publish from a branch other than `main`.

Stable upstream releases are checked daily. The updater tracks final Codex, GitHub CLI, ttyd, mise and uv releases plus maintenance updates within the selected Python 3.14, Node 24 LTS and npm 12 lines. It updates versions and architecture-specific hashes together and opens or refreshes a pull request; it never changes public image tags directly. Ubuntu LTS tag and digest updates remain managed by Renovate. Once an update PR passes the required build, launcher/Codex runtime checks, vulnerability gate and review and is merged, the edge publication workflow builds and publishes the updated image.

The default image does not install the system Bubblewrap package. On the supported TrueNAS profile, the Codex command launcher fixes `--sandbox danger-full-access`; the unsupported inner sandbox is disabled explicitly and the Codex outer container is the security boundary. The supported default approval mode is autonomous (`--ask-for-approval never`), while guarded mode (`untrusted`) remains a validated deployment or one-launch option. Approval prompts are not a sandbox or a substitute for narrow mounts.

APT package resolution follows the current security revisions available from the selected Ubuntu repositories rather than pinning exact revisions that may disappear after being superseded. APT resolution is therefore not claimed to be bit-for-bit reproducible; completed images are covered by smoke tests and Trivy before public tags are promoted.

> [!WARNING]
> Public availability does not make `edge` stable or production-ready. Breaking changes are possible, and neither port 7680 nor port 7681 may be exposed directly to the Internet.

## Stable

Stable publication is triggered only by an exact semantic version tag:

```text
vMAJOR.MINOR.PATCH
```

For example:

```text
v0.1.0
```

The tagged commit must belong to the history of `main`; a semantic-version tag placed on an unrelated branch is rejected. Stable publication produces identical versioned, `stable`, `stable-amd64` and `latest` tags under the canonical and compatibility packages. Pre-release tags such as `v0.1.0-rc.1` are intentionally rejected by the stable workflow.

Both publication workflows first push untagged candidates by digest, scan those exact digests and only then promote them to public moving or versioned tags. A fixable `CRITICAL` vulnerability blocks tag promotion. Critical findings without a known fix remain visible in the retained JSON reports but do not fail the gate.

## Promotion checklist

Before creating a stable version tag:

1. The AMD64 build, launcher/Codex runtime smoke tests and fixable-critical vulnerability gate pass on `main`.
2. The canonical `remote-dev` GHCR package is public and anonymously pullable.
3. Canonical and compatibility tags resolve to the same tested digest.
4. The stack has been deployed on TrueNAS from an exact published digest.
5. Docker reports launcher and Codex using the same image digest.
6. The TrueNAS portal opens the launcher on port 7680.
7. Launcher authentication, origin behavior, CSP and refresh have been verified in a real browser.
8. Selecting Codex navigates to the independent authenticated endpoint on port 7681 without exposing credentials in the URL.
9. The launcher has no Codex workspace, agent, GitHub, Git or SSH mounts and no Docker socket.
10. Codex browser access, authentication and tmux reconnection have been verified.
11. Codex device-code login persists across recreation.
12. GitHub CLI login, clone, push and pull-request creation have been verified.
13. The fixed sandbox and both Codex approval modes have been tested on the target TrueNAS host.
14. Changing the permanent approval setting affects subsequent sessions without silently changing an already running Codex process; a one-launch selection affects only that launch.
15. The changelog has a dated release section.
16. Third-party licenses and notices are complete.
17. The repository contains no credentials, personal paths or private infrastructure details.

The persistent-data migration and later cross-service hardening/canary work remain separate release gates before the architecture is described as complete.

## Rollback

Do not depend exclusively on moving tags. Record the tested image digest, its `sha-...` tag and the source commit. Set `REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<digest>` and recreate both stack services. Existing `v0.1.x` deployments may continue setting `CODEX_IMAGE=ghcr.io/experience83/codex-remote-dev@sha256:<digest>` when `REMOTE_DEV_IMAGE` is unset; both references identify the same promoted edge/stable digest.
