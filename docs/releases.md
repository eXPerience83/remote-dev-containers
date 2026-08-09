# Image release channels

Spanish version: [`releases.es.md`](releases.es.md)

Remote Dev uses one canonical runtime package:

```text
ghcr.io/experience83/remote-dev
```

The human-facing release channels are permanently ordered by release maturity as:

```text
dev  ->  edge  ->  stable = latest
```

They are deliberately separate. `dev` may contain unmerged pull-request code, `edge` contains only integrated `main` code, and `stable`/`latest` contain only an exact stable semantic-version release.

## Canonical tag contract

| Tag | Source | Movement | Intended use |
| --- | --- | --- | --- |
| `dev` / `dev-amd64` | Explicitly owner-authorized reviewed PR candidate | Mutable, only after `/publish-candidate <full-head-sha>` passes its gates | Active pre-merge TrueNAS/development testing |
| `edge` / `edge-amd64` | Current `main` | Mutable after a successful edge publication | Normal experimental integrated deployment |
| `stable` / `stable-amd64` | Latest stable `vMAJOR.MINOR.PATCH` release | Mutable only when a newer stable release is published | Stable deployment |
| `latest` | Same digest as `stable` | Moves only with `stable` | Conventional alias for the newest stable release |
| `vMAJOR.MINOR.PATCH` | Exact stable release tag | Version-addressed | Reproducible named stable release |
| `candidate-pr-<PR>-<short-sha>` | One explicitly published PR candidate | Candidate-specific audit tag | Debugging/audit, not a deployment channel |
| `sha-<full-sha>` | One published `main` revision | Source-addressed edge tag | Source-revision lookup/audit |
| `@sha256:<digest>` | Exact registry manifest | Immutable reference | Exact validation, reproduction and rollback |

`latest` is always an alias of `stable`. It must never point to `edge` or `dev`.

Until Remote Dev publishes a supported multi-architecture runtime, the generic channel tags and their `*-amd64` forms resolve to the same AMD64 digest. The architecture-specific `dev-amd64`, `edge-amd64` and `stable-amd64` tags remain the recommended deployment form on the current supported platform so a future multi-architecture transition can be explicit rather than silently changing an installed architecture.

## Dev

`dev` is the mutable pre-merge testing channel. It is intentionally more volatile than `edge` and may contain code that has not merged into `main`.

A normal pull-request push or CI run cannot move `dev`. The only supported publication path is an owner comment on an open PR targeting `main`:

```text
/publish-candidate <full-40-character-head-sha>
```

The candidate workflow verifies that the supplied SHA is still the exact PR head and that the branch belongs to this repository. It then builds/smoke-tests that exact head without package-write permission, exports the resulting images, independently reloads and identity-checks the artifact, applies the fixable-critical vulnerability gate, and only then allows the package-enabled job to publish the candidate.

A successful publication keeps the candidate-specific tag and promotes the exact same verified digest to both:

```text
ghcr.io/experience83/remote-dev:dev
ghcr.io/experience83/remote-dev:dev-amd64
```

Mutable `dev` promotion is serialized so two candidate publications cannot race the tag update. The immutable digest remains the authoritative evidence for a specific TrueNAS validation.

For a TrueNAS installation used mainly to validate work before merge, set once:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:dev-amd64
```

After an explicitly authorized candidate is published, recreate/update the stack normally. No per-candidate YAML edit is required. Do not use `dev` where unmerged code is unacceptable.

## Edge

`edge` is the public experimental integrated channel for the current `main` branch.

The **Publish edge AMD64** workflow runs automatically after relevant image, runtime or version changes merge into `main`. It can also be started manually from `main`. Each run builds and scans one final Remote Dev digest and promotes only that exact scanned digest to the canonical edge tags:

```text
ghcr.io/experience83/remote-dev:edge
ghcr.io/experience83/remote-dev:edge-amd64
ghcr.io/experience83/remote-dev:sha-<full-main-sha>
```

The workflow refuses to publish `edge` from a branch other than `main`.

Generic and TrueNAS Compose continue to default to:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

That remains the recommended channel for normal experimental deployments that should receive integrated changes without consuming unmerged PR candidates.

The current stack instantiates the same image reference for its enabled roles. The launcher remains navigation-only and receives no agent workspace, state or credentials; Codex and optional agents retain their isolated role-specific mounts and authentication boundaries.

Public container-registry images can be pulled without authentication. Container tags are mutable in GHCR, so record and deploy the published `sha256:...` digest whenever immutable reproduction is required.

Stable upstream releases are checked daily. The updater tracks final Codex, GitHub CLI, ttyd, mise and uv releases plus maintenance updates within the selected Python 3.14, Node 24 LTS and npm 12 lines. Ubuntu LTS tag and digest updates remain managed by Renovate.

The default image does not install the system Bubblewrap package. On the supported TrueNAS profile, the Codex command launcher fixes `--sandbox danger-full-access`; the outer Codex container and its narrow mounts are the security boundary. Autonomous and guarded approval modes do not change that boundary.

> [!WARNING]
> Public availability does not make `edge` stable or production-ready. Breaking changes are possible, and the Remote Dev web endpoints must not be exposed directly to the Internet.

## Stable and latest

Stable publication is triggered only by an exact semantic version tag:

```text
vMAJOR.MINOR.PATCH
```

The tagged commit must belong to `main`. Pre-release tags are intentionally rejected by the stable workflow.

After the exact stable candidate is built and scanned successfully, the same digest is promoted to:

```text
ghcr.io/experience83/remote-dev:vMAJOR.MINOR.PATCH
ghcr.io/experience83/remote-dev:stable
ghcr.io/experience83/remote-dev:stable-amd64
ghcr.io/experience83/remote-dev:latest
```

`stable` is the semantic deployment channel. `latest` exists only as the conventional registry alias for the same stable digest. Publishing `dev` or `edge` must never move `latest`.

Once stable releases exist, the recommended stable AMD64 deployment is:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:stable-amd64
```

Both edge and stable publication workflows push candidates by digest, scan those exact digests and only then promote public tags. A fixable `CRITICAL` vulnerability blocks promotion. Critical findings without a known fix remain visible in retained reports.

## Operator channel choices

Use one channel in deployment configuration and change it only when intentionally changing release maturity:

```dotenv
# Active review / pre-merge testing
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:dev-amd64

# Normal experimental deployment (repository default)
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64

# Stable deployment, once stable releases exist
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:stable-amd64
```

For a one-off exact validation or rollback, temporarily replace the channel with the immutable digest:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<digest>
```

## Promotion checklist

Before creating a stable version tag:

1. The AMD64 build, runtime smoke tests and fixable-critical vulnerability gate pass on `main`.
2. Canonical `remote-dev` runtime tags being promoted resolve to the tested `REMOTE_DEV_DIGEST`, and `remote-dev-base` promotion metadata separately matches the tested `BASE_DIGEST`.
3. The stack has been deployed on TrueNAS from an exact published digest.
4. Docker reports launcher and enabled agent services using the intended common image digest.
5. The TrueNAS portal opens the launcher on port 7680.
6. The launcher opens on the trusted private endpoint and preserves origin/CSP behavior.
7. Selecting Codex navigates to the independent authenticated endpoint without exposing credentials.
8. The base launcher has no agent mounts and no Docker/Podman socket; optional launcher authentication receives only its dedicated read-only password secret.
9. No service uses host networking, privileged mode or added capabilities beyond the reviewed contract.
10. The canonical host-path preflight passes on the target system before deployment, and no unexpected host directory was generated.
11. Workspace, agent state, GitHub CLI state, Git configuration and SSH state persist across stop/start and recreation as documented.
12. Codex device-code login persists across recreation.
13. GitHub CLI login, clone, push and pull-request creation have been verified.
14. Autonomous and guarded Codex behavior has been tested on the target TrueNAS host.
15. Optional `WEB_PASSWORD_FILE` authentication has been validated under #69.
16. The changelog has a dated release section.
17. Third-party licenses and notices are complete.
18. The repository contains no credentials, personal paths or private infrastructure details.

Cross-service hardening/canary work and optional-agent validation remain separate gates before the architecture is described as complete. Optional SMB/ACL workspace testing is tracked separately.

## Rollback

Do not depend exclusively on moving channel tags. Record the tested image digest, source revision and, where applicable, the candidate or version tag.

Set:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<digest>
```

and recreate all stack services. Existing `v0.1.x` deployments may continue setting the image-name alias `CODEX_IMAGE` when `REMOTE_DEV_IMAGE` is unset, but the value should use the canonical `ghcr.io/experience83/remote-dev` package.

The canonical data layout is independent from the image tag. Rollback must not broaden mounts or copy state automatically. Keep a backup or snapshot before manually moving experimental data into new paths.
