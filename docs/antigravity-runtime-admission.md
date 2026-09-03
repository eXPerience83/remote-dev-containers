# Antigravity runtime admission

## Status and scope

Antigravity CLI is an optional Google product. Remote Dev does not bundle, copy or redistribute its installer or executable. Installation and update are explicit user actions performed inside the isolated Antigravity service.

The service must run with `REMOTE_DEV_ROLE=antigravity` and the explicit `REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1` opt-in. The Antigravity role remains unavailable while that experimental gate is disabled. The integration remains deliberately experimental under the current #53/#96 vendor-policy disposition: Remote Dev is a non-affiliated launcher/wrapper around the official `agy` CLI, not an alternate Antigravity client or an OAuth relay into another agent harness.

This document defines the runtime availability and integrity model implemented under issue #96 and the advisory review automation implemented under issue #83. Broad documentation/status synchronization remains under issue #92.

## Availability model

A compatible Antigravity release may be installed or updated from Google's fixed official installer endpoint without waiting for a new Remote Dev image. Committed inspection evidence describes the exact version already reviewed by Remote Dev; it is not an allowlist and absence from it is not a revocation.

Normal container startup, status checks, full verification and agent launches never contact the installer endpoint and never update the executable. Informational `status` and `status --menu` validate the executable/manifest structure and review state without hashing the complete executable or running vendor code. Immediately before a real session, Remote Dev performs one mandatory full SHA-256 verification of the canonical executable against its private manifest. `remote-dev-antigravity verify` performs the same full offline integrity check explicitly, and Run diagnostics invokes it before reporting lightweight status. `AGY_CLI_DISABLE_AUTO_UPDATE=true` remains mandatory for normal Antigravity sessions.

## Explicit installation and update

The manager:

1. shows the Google terms, privacy and non-affiliation disclosure;
2. downloads only from `https://antigravity.google/cli/install.sh` using HTTPS, ignores ambient curl configuration and rejects redirects outside the reviewed Google origin;
3. enforces installer and payload size limits and stores network bytes in private staging rather than piping them to a shell;
4. validates a regular installer file, Bash syntax and the required `--dir <path>` contract;
5. executes the installer with an empty environment, isolated home, controlled destination, bounded output/time and disabled auto-update;
6. drops from container root to the unprivileged `nobody` identity for installer and candidate execution when running in the production root container;
7. validates the installed file type, owner, Linux AMD64 ELF format, size, semantic version, bounded help response and stability during validation;
8. writes a private `0600` manifest recording source, fixed/final installer URL, installer hash/size, binary hash/size, version and timestamp;
9. publishes the executable and manifest only after all checks pass, restoring the previous pair after a failed or interrupted update.

An incompatible upstream contract is rejected. The manager does not relax validation automatically to regain availability.

## Runtime states

The menu and diagnostics expose only bounded, non-secret state. Menu status is informational; a successful full verification is still required immediately before execution:

- **Official and reviewed**: the structurally valid private manifest matches the committed Remote Dev inspection evidence. Full executable integrity is checked before launch and by explicit verification/diagnostics.
- **Official source; Remote Dev review pending**: the structurally valid private manifest records a payload admitted through the explicit official-origin flow, but the exact installer/payload is absent from current image evidence. It remains runnable only after the mandatory pre-execution full verification succeeds.
- **Damaged or locally modified**: the executable or manifest is missing, symlinked, permission-invalid, malformed or identity-mismatched. Launch is blocked until an explicit update repairs it.

“Official source; review pending” records the controlled download path and local manifest integrity. It is not a claim of cryptographic Google signing, Remote Dev certification, inclusion in the image SBOM or coverage by Apache-2.0.

## Image replacement and rollback

An intact installed version remains usable when a newer or older Remote Dev image contains different review evidence. Changing the image may change only the displayed review state. It does not invalidate or replace the persisted executable.

A successful explicit update replaces the persisted executable. A failed download, contract check, candidate validation or publication keeps the previous executable and manifest usable. The same explicit update command repairs partial state when either the executable or manifest is missing; a first-install command refuses to overwrite such damaged remnants silently.

## Threat boundary

The private manifest detects independent executable or manifest modification and accidental corruption. It does not protect against an attacker or process that already controls the Antigravity service user or container root and can coherently replace both files. That limitation matches the project's single-user outer-container trust model.

The downloaded installer remains vendor code. Running it as an unprivileged identity with an empty environment and a private staging subtree reduces exposure to mounted credentials, but does not transform it into a sandboxed or independently audited program.

## Scheduled review automation

`.github/workflows/check-upstream.yml` runs the shared upstream review at **05:17 UTC every day** and also supports manual dispatch. Antigravity is detected in a separate `antigravity-detect` job with `contents: read`, no persisted checkout credentials and no repository write capability. That job downloads only bounded metadata from the fixed reviewed Google origin and does **not execute a changed installer**. A safe same-origin redirect can be surfaced as review metadata, but executable review continues to require the exact fixed installer contract until a compatibility change is explicitly reviewed.

The detection artifact contains only a fixed JSON schema: source/final URL, content type, size, SHA-256, referenced HTTPS host names, the committed reviewed installer SHA-256 and a `changed` boolean. Raw installer content, stdout/stderr, OAuth/account data and proprietary binaries are not retained. The artifact is schema-validated before upload and revalidated after entering the separate write-capable PR-maintenance job.

The writer folds Antigravity state into the same `automation/update-upstreams` branch/PR used by the grouped upstream updater. A scheduled rerun starts from current `main` and may preserve only schema-valid Antigravity discovery or fully reviewed evidence that still corresponds to the currently detected installer and preserves the human-owned runtime/legal policy fields. Stale review state is dropped. The automation never auto-merges.

## Two explicit hash admissions

Changed Antigravity vendor bytes may execute only through manual `.github/workflows/review-antigravity-candidate.yml` dispatches from `main`:

1. **`discover-payload`** — a maintainer supplies the exact lowercase SHA-256 reported for the changed official installer. The credential-free read-only job verifies that hash before execution, runs only that admitted installer in an isolated temporary home and records the resulting `agy` path/size/SHA-256. It **does not execute `agy`**.
2. **`inspect-payload`** — after separately reviewing the discovery metadata, a maintainer supplies both the same installer SHA-256 and the exact discovered `agy` SHA-256. Only then may the existing bounded inspector execute `agy --version`/`--help` and produce proposed reviewed evidence.

The vendor-byte job has only read permission. It cannot write the repository, issues or pull requests. Only schema-validated metadata crosses to a second writer job; the writer validates that artifact again before modifying the automation branch. Installer bytes, `agy` bytes and raw vendor stdout/stderr are never uploaded as review artifacts or committed.

A completed full inspection updates `third_party/antigravity-cli-inspection.json`, the corresponding generated current-review block in `third_party/antigravity-cli-inspection.md`, and resets `third_party/antigravity-cli-detection.json` to the newly reviewed installer identity. Human review of compatibility and the current Google terms/privacy boundary is still required before merge.

## Review automation is not runtime admission

Scheduled detection, a pending automation PR, a failed inspection or absence from committed review evidence never revokes an intact locally admitted runtime. Runtime availability remains governed by the explicit-install/private-manifest/#153 integrity contract above. A specifically unsafe version/hash would require an explicit project revocation decision; it is not inferred merely from `review pending` state.
