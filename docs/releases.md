# Image release channels

Spanish version: [`releases.es.md`](releases.es.md)

Remote Dev uses one canonical runtime package:

```text
ghcr.io/experience83/remote-dev
```

The permanent maturity order is:

```text
dev -> edge -> stable = latest
```

These concepts stay separate from human-readable build identity and immutable provenance. Remote Dev has **not published a stable release yet**; current public integrated deployments use `edge`/`edge-amd64`.

The repository's local development baseline is `0.1.1-dev`. That value is a source/local-build default only: edge publication replaces it with a dated edge identity, and stable publication alone uses exact SemVer.

## Identity layers

From strongest reproduction identity to most human-oriented label:

1. **OCI digest** — `@sha256:<digest>` is the exact immutable registry object and the strongest rollback/reproduction reference.
2. **Full source revision** — the complete Git commit SHA identifies the source tree. Published `main` revisions also receive `sha-<full-sha>` tags.
3. **Build/release identity** — edge uses `edge-YYYY.MM.DD-<7-char-sha>`; stable uses exact `vMAJOR.MINOR.PATCH`; explicitly published PR candidates keep candidate-specific identity.
4. **Channel** — `dev`, `edge` or `stable` is the mutable maturity pointer. `latest` is always an alias of `stable`.

The date in an edge identity is the UTC publication date. It is never treated as stronger evidence than the full source SHA or OCI digest.

Runtime diagnostics expose the build identity and channel separately, for example:

```text
Image version: edge-2026.09.04-22a3bda
Channel: edge
Source revision: 22a3bda...<full SHA>
```

## Canonical tag contract

| Tag/reference | Source | Movement | Intended use |
| --- | --- | --- | --- |
| `dev` / `dev-amd64` | One explicitly owner-authorized reviewed PR head | Mutable only after the candidate publication gate | Pre-merge TrueNAS/development testing |
| `edge` / `edge-amd64` | Integrated `main` | Mutable after successful edge publication | Normal experimental deployment |
| `stable` / `stable-amd64` | Latest explicit stable SemVer release | Mutable only when a newer stable release is published | Stable deployment once available |
| `latest` | Exact same digest as `stable` | Moves only with `stable` | Conventional stable alias |
| `vMAJOR.MINOR.PATCH` | Exact stable release tag | Version-addressed | Named stable release |
| `candidate-pr-<PR>-<short-sha>` | One explicitly published PR candidate | Candidate-specific | Review/audit |
| `sha-<full-sha>` | One published `main` revision | Source-addressed | Integrated source audit |
| `@sha256:<digest>` | Exact OCI manifest | Immutable | Exact validation/reproduction/rollback |

`latest` must never point to `dev` or `edge`.

Until multi-architecture runtime publication is supported, the generic channel tags and `*-amd64` forms resolve to the AMD64 build. The architecture-specific `dev-amd64`, `edge-amd64` and future `stable-amd64` forms remain the recommended deployment selectors so an eventual architecture expansion can be explicit.

## Dev — reviewed pre-merge candidate

A normal PR push or CI run cannot move `dev`.

The supported candidate publication path requires an owner command on an open PR targeting `main`:

```text
/publish-candidate <full-40-character-head-sha>
```

The workflow verifies that the supplied SHA is still the exact PR head and belongs to this repository, builds/smoke-tests that exact source, performs independent artifact identity checks and the vulnerability gate, then promotes only the verified digest to:

```text
ghcr.io/experience83/remote-dev:dev
ghcr.io/experience83/remote-dev:dev-amd64
```

The candidate-specific audit tag is retained. Mutable `dev` promotion is serialized so two candidates cannot race the channel.

For temporary TrueNAS candidate testing:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:dev-amd64
```

After the reviewed change merges, return the deployment to `edge-amd64` unless intentionally remaining on an exact digest.

## Edge — integrated main

`edge` is the public experimental integrated channel for `main`.

The **Publish edge AMD64** workflow runs after relevant image/runtime/version changes merge into `main` and can also be started explicitly from trusted `main`. It refuses branch sources other than `main`.

A successful edge publication embeds:

```text
edge-YYYY.MM.DD-<7-char-sha>
Channel: edge
```

and promotes the exact scanned digest to:

```text
ghcr.io/experience83/remote-dev:edge
ghcr.io/experience83/remote-dev:edge-amd64
ghcr.io/experience83/remote-dev:sha-<full-main-sha>
```

The dated string is an embedded build identity, not a SemVer tag and not a replacement for the full source SHA or digest.

The normal current deployment selector is:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64
```

All enabled stack roles use the same intended image reference. The launcher remains navigation-only; mutable Codex/Antigravity runtime state remains role-private and is not implied to be part of the edge image digest.

## Automated changelog provenance

`CHANGELOG.md` is a stable-release changelog, not one top-level section per CI build. `## [Unreleased]` accumulates reviewed changes until a stable SemVer release is prepared.

Two bounded automation owners may update machine-owned subsections under `Unreleased`:

### Grouped upstream refreshes

`.github/workflows/check-upstream.yml` owns bundled/runtime/tool pins such as Codex CLI, GitHub CLI, ttyd, mise, uv and selected Python/Node/npm lines.

When actual component versions change, the same review PR updates the bounded `### Automated upstream refreshes` area using repository old/new values. Checksum-only churn does not invent a fake user-facing application-version change. Re-running against the same baseline is deterministic and the automation never auto-merges the PR.

### Renovate image refreshes

Renovate has a separate ownership boundary.

- Ubuntu LTS tag/digest changes materially affect the produced runtime image and therefore update the bounded `### Renovate image refreshes` area.
- The hidden Ubuntu state anchor must match the committed Ubuntu version/digest in `versions.env` and `images/base/Dockerfile`.
- Renovate's replacement derives the user-facing old -> new identity from the actual current/proposed Ubuntu tag and immutable digest and advances the anchor in the same grouped `Ubuntu LTS base` PR.
- Recreating the same Renovate PR from the same base reproduces the same output; a later merged Ubuntu update appends a new machine-owned delta without overwriting prior entries or human text.
- GitHub Action SHA-only maintenance and the pinned Dockerfile frontend remain CI/build maintenance and are **not** mislabeled as bundled runtime application upgrades.
- Renovate remains `automerge: false`.

The repository validator enforces both automation boundaries offline. Human-authored changelog text outside their explicit markers is not an automation target.

## Stable and latest

Stable publication is triggered only by an exact non-prerelease SemVer tag:

```text
vMAJOR.MINOR.PATCH
```

The tagged commit must belong to `main` and pass the stable publication gates. Stable images embed the SemVer identity and a separate `stable` channel.

After the exact stable candidate is built and scanned successfully, the same digest is promoted to:

```text
ghcr.io/experience83/remote-dev:vMAJOR.MINOR.PATCH
ghcr.io/experience83/remote-dev:stable
ghcr.io/experience83/remote-dev:stable-amd64
ghcr.io/experience83/remote-dev:latest
```

`latest` is therefore only the conventional alias for the newest stable digest. Publishing `dev` or `edge` never moves it.

Once stable releases exist, the normal stable AMD64 selector becomes:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:stable-amd64
```

## Operator channel choices

Use one maturity channel in normal deployment configuration and switch it only intentionally:

```dotenv
# Reviewed unmerged candidate
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:dev-amd64

# Current integrated experimental build
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64

# Stable, once a stable release exists
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:stable-amd64
```

For exact validation or rollback, pin the immutable digest instead:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<digest>
```

Do not rely on a mutable tag or the human-readable edge date when exact reproduction matters.

## Stable-release checklist

Before creating the first or any later stable version tag, verify on one exact `main` source revision/digest that:

1. Repository validation and the complete AMD64 build/smoke suite pass.
2. Base and final Remote Dev images pass the publication vulnerability gate; fixable `CRITICAL` findings block promotion.
3. Notices and SBOM generation pass and the retained reports match the image being promoted.
4. The intended administrator-owned TrueNAS root exists and the same-revision bootstrap/preflight succeed.
5. The reference TrueNAS Host Path layout satisfies the Generic/POSIX private-state ACL contract or an explicitly documented equivalent migration decision; run the host ACL audit where applicable.
6. Launcher and enabled agent services use the intended common image digest/reference while keeping disjoint writable/private mounts.
7. Launcher origin/CSP/navigation behavior is verified and it has no agent state/password or container-engine socket.
8. Codex and enabled Antigravity endpoints authenticate through their separate configuration entries; current support does not require those password values to differ or meet a project-imposed minimum length/composition policy.
9. Workspace/project, agent state, GitHub/Git/SSH state and intended runtime state persist across stop/start and recreation.
10. Codex device login, session Resume and the supported autonomous/guarded launch paths work on the target deployment.
11. If Antigravity is included in the support claim, its explicit vendor runtime path, current admission/integrity state and documented experimental support restrictions remain valid; #53 has no unresolved out-of-cycle blocker for the exact claim.
12. Optional external integrations included in the support claim retain their documented privacy/credential boundaries.
13. `CHANGELOG.md` has a dated stable section derived from the reviewed `Unreleased` content.
14. Repository/release evidence contains no credentials, private infrastructure paths or sensitive account/session data.
15. #31 has no unresolved issue that contradicts the stable support claim actually being made.

Optional/future #181/#170/#124/#95/#159/#71/#112/#121/#148/#151 work is not automatically a stable blocker unless #31 or the corresponding issue identifies a concrete dependency for the release claim.

## Rollback

Record the tested OCI digest and full source revision before changing maturity channels or deploying a new image.

To roll back the image without changing persistent-layout semantics:

```dotenv
REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev@sha256:<known-good-digest>
```

Then recreate all stack services from that exact reference.

Rollback must not broaden mounts or silently copy/migrate state. If a newer release changes an on-disk contract, follow the explicitly documented migration/rollback procedure for that contract rather than assuming an older image can safely reinterpret newer persistent data.
