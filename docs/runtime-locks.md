# Locked mise runtimes

Python, Node.js and uv are installed by mise, but their build inputs are committed rather than resolved dynamically during the image build.

## Source of truth

The runtime pins are represented in three places for different purposes:

- `versions.env` supplies reviewed repository and build arguments.
- `mise.toml` declares the exact mise-managed runtime versions and enables provenance re-verification for locked installs.
- `mise.lock` records the resolved Linux AMD64 and ARM64 artifact URLs, SHA-256 checksums and available provenance requirements.

`scripts/validate-version-pins.sh` fails when these files or the base Dockerfile disagree. The lock validator treats both TOML files as security-sensitive schemas: unknown sections or fields, malformed platform values, unexpected backends or URLs, invalid checksums, missing provenance, mixed Python build dates and reused uv asset IDs are rejected. Adversarial fixtures exercise these rejection paths on every validation run.

The Dockerfile copies `mise.toml` and `mise.lock` as read-only inputs and runs `mise install --locked`; a missing artifact entry, dynamic-resolution requirement, provenance failure or checksum mismatch stops the build. `locked_verify_provenance = true` ensures that Python and uv GitHub artifact attestations are checked during installation instead of trusting only the provenance marker already stored in the lockfile.

For the repository's unqualified Ubuntu/glibc Linux targets, uv is intentionally locked to the official GNU artifacts for both AMD64 and ARM64. The exact GNU artifact is part of the fail-closed URL policy: a regenerated musl entry or any other asset requires explicit review and is rejected rather than treated as interchangeable.

The current CI builds Linux AMD64, so it downloads, checksums, installs and re-verifies provenance for the AMD64 artifacts. ARM64 entries are checked for exact schema, platform, backend, URL, checksum and provenance metadata coherence, but are not executed by the current AMD64 job. A future ARM64 image build will use the same locked installation and re-verification path before ARM64 publication.

npm is intentionally excluded from `mise.lock` because the image installs it separately from the npm registry.

## Regenerate the lockfile

Use the exact mise release pinned by `MISE_VERSION` in `versions.env`. The helper rejects any other mise version. It copies only `versions.env`, `mise.toml` and the existing `mise.lock` into a temporary workspace, clears inherited `MISE_*` settings, uses isolated config/data/cache/system/tmp directories, bounds network and command time, validates the generated lock and replaces the repository lock only after validation succeeds. A failed or malformed regeneration leaves the previous lock untouched.

```bash
source versions.env
mise --version
bash scripts/regenerate-mise-lock.sh
bash scripts/validate-version-pins.sh
```

When changing Python, Node.js or uv:

1. Update the version in `versions.env`.
2. Update the matching `ARG` default in `images/base/Dockerfile`.
3. Update the matching tool in `mise.toml`.
4. Run `scripts/regenerate-mise-lock.sh` with the pinned mise release.
5. Review every changed URL, SHA-256 and provenance field for both `linux-x64` and `linux-arm64`.
6. Run `make validate` and build the AMD64 images so mise verifies the current-platform downloaded artifacts and supported provenance.

The daily upstream workflow follows the same procedure with a freshly downloaded mise binary whose SHA-256 is verified before it regenerates the lock. A plain `mise lock` refreshes artifact metadata for the already pinned versions, so the workflow may propose a lock-only change when an upstream provider publishes a newer artifact for an unchanged runtime version. The workflow is restricted to `main`, serialized to prevent competing writers and uses a force-with-lease update for its dedicated automation branch.

## Recovery

Do not remove `--locked`, disable `locked_verify_provenance`, delete `mise.lock` or fall back to `mise use` to work around a stale lock. Regenerate the lock with the exact pinned mise version, review the artifact changes, and keep the version/config/lock updates in one pull request.

If a checksum has changed unexpectedly for an artifact URL that should be immutable, stop the update and investigate upstream before merging.
