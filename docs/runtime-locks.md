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

## Generated graph retention

The old graph directories must remain available until a replacement lock has been published and validated. The daily updater subsequently runs `scripts/prune-mise-locks.py --write` in its exclusive, trusted Git checkout, after lock, notice and inventory checks. It derives active graphs from the validated `mise.lock` and only removes unchanged tracked generated graph pairs (`uv.lock` and `pyproject.toml`) for the three reviewed Python tools. Unknown paths, extra files, links, modified graphs and invalid active locks cause a failure before deletion. Git subprocesses discard inherited Git-specific environment overrides, check staged and working-tree changes separately, and compare candidate bytes directly with HEAD so index flags cannot hide local edits. The script does not recursively delete directories or touch installed environments, host mounts or project data. Manual regeneration remains non-pruning; the helper defaults to a read-only plan without `--write`. Git history and immutable published images retain prior graphs for rollback. Do not run concurrent lock regeneration/pruning in the same checkout.

## Regenerate the lockfile

Use the exact mise release pinned by `MISE_VERSION` in `versions.env`. The helper rejects any other mise version. It copies only `versions.env`, `mise.toml` and the existing `mise.lock` into a temporary workspace, clears inherited `MISE_*` settings, uses isolated config/data/cache/system/tmp directories, and bounds network and command time. Since [PR #291](https://github.com/eXPerience83/remote-dev-containers/pull/291), regeneration **first creates and validates a Python-only bootstrap lock**, installs the exact selected administrative Python in the isolated workspace, and makes that interpreter available to uv before generating the full native PyPI graphs. `UV_PYTHON_DOWNLOADS=never` remains enforced. The helper validates the resulting two-platform lock before publishing graphs and replacing the repository lock. Resolution or validation failure before publication leaves the previous lock untouched. Graph paths are keyed by tool/options, not by the graph digest, so publishing a same-path graph and its referencing lock is not a single atomic operation; do not reuse a failed publication checkout.

```bash
source versions.env
mise --version
bash scripts/regenerate-mise-lock.sh
# If Python CLI uv graphs changed, refresh their hash-checked legal notices first:
python3 scripts/sync-python-cli-notices.py --write
bash scripts/validate-version-pins.sh
```

When changing Python, Node.js or uv:

1. Update the version in `versions.env`.
2. Update the matching `ARG` default in `images/base/Dockerfile`.
3. Update the matching tool in `mise.toml`.
4. Run `scripts/regenerate-mise-lock.sh` with the pinned mise release.
5. If the Python CLI uv graphs have changed, refresh the hash-verified wheel/license notices with `python3 scripts/sync-python-cli-notices.py --write` **before** strict version validation. Refresh the Python runtime's own version-specific legal metadata and inventory with their repository scripts as part of the same change.
6. Review every changed URL, SHA-256 and provenance field for both `linux-x64` and `linux-arm64`.
7. Run `make validate` and build the AMD64 images so mise verifies the current-platform downloaded artifacts and supported provenance.

The daily upstream workflow follows the same procedure with a freshly downloaded mise binary whose SHA-256 is verified before it regenerates the lock. It gates new `ruff`, `pytest` and `pre-commit` PyPI candidates on **24 hours since the newest non-yanked distribution file**, matching mise/uv's normal minimum-release-age cutoff. An immature release keeps only its previously reviewed pin; Python and other unrelated updates may proceed. The workflow regenerates Python CLI notices after lock generation and **before** running `validate-version-pins.sh`, and its dual-Python regression checks both original and already-updated pins ([PRs #292–#293](https://github.com/eXPerience83/remote-dev-containers/pull/293)). There is no automatic hotfix bypass; an urgent exception would require a separate explicit security review and aligned resolver policy. A plain `mise lock` refreshes artifact metadata but reuses the recorded Python dependency graphs. In the disposable CI checkout only, the updater opts into `--refresh-pypi` to run `mise lock --platform linux-x64,linux-arm64 --minimum-release-age 24h --bump pypi:pre-commit pypi:pytest pypi:ruff` inside the same isolated resolver workspace. Exact top-level pins remain unchanged by this refresh; the complete lock validator, hash-verified notices and ordinary review gates still apply. A same-version dependency update can therefore produce a lock-only PR. The mode is rejected outside `CI=true`; CI must discard a failed checkout and never stage or publish partial changes. Manual regeneration retains its normal non-bump behavior. See [pinned mise documentation](https://github.com/jdx/mise/blob/v2026.11.14/docs/dev-tools/backends/pypi.md#updating-dependencies). The workflow is restricted to `main`, serialized to prevent competing writers and uses a force-with-lease update for its dedicated automation branch.

## Recovery

Do not remove `--locked`, disable `locked_verify_provenance`, delete `mise.lock` or fall back to `mise use` to work around a stale lock. Regenerate the lock with the exact pinned mise version, review the artifact changes, and keep the version/config/lock updates in one pull request.

If a checksum has changed unexpectedly for an artifact URL that should be immutable, stop the update and investigate upstream before merging.
