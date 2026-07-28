# Locked mise runtimes

Python, Node.js and uv are installed by mise, but their build inputs are committed rather than resolved dynamically during the image build.

## Source of truth

The runtime pins are represented in three places for different purposes:

- `versions.env` supplies reviewed repository and build arguments.
- `mise.toml` declares the exact mise-managed runtime versions and enables provenance re-verification for locked installs.
- `mise.lock` records the resolved Linux AMD64 and ARM64 artifact URLs, SHA-256 checksums and available provenance requirements.

`scripts/validate-version-pins.sh` fails when these files or the base Dockerfile disagree. The Dockerfile copies `mise.toml` and `mise.lock` as read-only inputs and runs `mise install --locked`; a missing artifact entry, dynamic-resolution requirement, provenance failure or checksum mismatch stops the build. `locked_verify_provenance = true` ensures that Python and uv GitHub artifact attestations are checked during the build instead of trusting only the provenance marker already stored in the lockfile.

npm is intentionally excluded from `mise.lock` because the image installs it separately from the npm registry.

## Regenerate the lockfile

Use the exact mise release pinned by `MISE_VERSION` in `versions.env`. The helper rejects any other mise version and isolates the command from user-global mise configuration.

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
6. Run `make validate` and build the AMD64 images so mise verifies the downloaded artifacts and supported provenance.

The daily upstream workflow follows the same procedure with a freshly downloaded mise binary whose SHA-256 is verified before it regenerates the lock. A plain `mise lock` refreshes artifact metadata for the already pinned versions, so the workflow may propose a lock-only change when an upstream provider publishes a newer artifact for an unchanged runtime version.

## Recovery

Do not remove `--locked`, disable `locked_verify_provenance`, delete `mise.lock` or fall back to `mise use` to work around a stale lock. Regenerate the lock with the exact pinned mise version, review the artifact changes, and keep the version/config/lock updates in one pull request.

If a checksum has changed unexpectedly for an artifact URL that should be immutable, stop the update and investigate upstream before merging.
