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

`.github/workflows/check-upstream.yml` runs the shared upstream review at **05:17 UTC every day** and also supports manual dispatch. Antigravity discovery runs in a separate `antigravity-detect` job with `contents: read`, no persisted checkout credentials and no repository write capability.

That job fetches bounded installer bytes from the exact canonical `https://antigravity.google/cli/install.sh`, bounded JSON from the fixed reviewed Linux AMD64 manifest endpoint, and the bounded payload archive referenced by that manifest. Every initial URL, redirect target and final URL is checked against a narrow HTTPS policy before the request can proceed; ambient proxy settings are disabled. The manifest must retain its exact reviewed `version`/`url`/`sha512` schema and the archive URL must stay on the reviewed Google Storage path.

All of those vendor bytes are treated strictly as **data**. The installer is hash-checked and inspected only for the reviewed static contract markers; it is not run. The archive SHA-512 is checked against the manifest, then the single regular `antigravity` member is streamed directly from the tar to calculate the `agy` SHA-256. The archive is not extracted and neither `install.sh` nor `agy` executes during scheduled discovery. Links, devices, unexpected regular files, malformed manifests, unsafe redirects and size-boundary violations fail closed.

The uploaded artifacts contain only fixed normalized metadata schemas for installer detection and static payload discovery: source/final URLs, bounded sizes/content types, hashes, reviewed installer identity, manifest version/archive integrity and the discovered payload path/size/SHA-256. Raw installer/manifest/archive content, stdout/stderr, OAuth/account data and proprietary binaries are not retained. Metadata is schema-validated before upload and revalidated after entering the separate write-capable PR-maintenance job.

The writer folds Antigravity state into the same `automation/update-upstreams` branch/PR used by the grouped upstream updater. A scheduled rerun starts from current `main` and may preserve only schema-valid Antigravity discovery or fully reviewed evidence that still corresponds to the currently detected installer/payload pair and preserves the human-owned runtime/legal policy fields. Fresh static discovery supersedes stale candidate/full-review proposals. The candidate path is staged before the no-change decision so a newly created file cannot be lost as untracked state. The automation never auto-merges.

## One explicit execution admission

Scheduled discovery can identify a changed installer and/or changed `agy` payload without executing either one. Vendor code may execute only through a manual `.github/workflows/review-antigravity-candidate.yml` dispatch from `main` after a maintainer has reviewed the automation PR and supplies **both** exact lowercase SHA-256 values: the statically discovered installer hash and the statically discovered `agy` hash.

The credential-free read-only execution job first downloads the installer through the same strict URL/redirect/proxy-disabled policy and rejects it unless its SHA-256 exactly matches the supplied installer admission. Only after that prefetch gate passes is the verified local file handed to the bounded inspector. The inspector verifies the installer hash again, runs the admitted installer in an isolated temporary home, verifies that the resulting `agy` exactly matches the separately supplied payload SHA-256 **before invoking it**, and only then runs bounded `agy --version`/`--help` and the existing compatibility checks.

The execution job has only `contents: read`; it cannot write the repository, issues or pull requests. It uploads only schema-validated normalized metadata. A separate writer job downloads and validates that metadata again, confirms the supplied hashes match the pending static candidate, and only then proposes refreshed reviewed evidence on the automation branch. Installer bytes, archives, `agy` bytes and raw vendor stdout/stderr are never uploaded as review artifacts or committed.

A completed full inspection updates `third_party/antigravity-cli-inspection.json`, the corresponding generated current-review block in `third_party/antigravity-cli-inspection.md`, removes the superseded static candidate, and resets `third_party/antigravity-cli-detection.json` to the newly reviewed installer identity. Human review of compatibility and the current Google terms/privacy boundary is still required before merge.

## Review automation is not runtime admission

Scheduled detection, a pending automation PR, a failed inspection or absence from committed review evidence never revokes an intact locally admitted runtime. Runtime availability remains governed by the explicit-install/private-manifest/#153 integrity contract above. A specifically unsafe version/hash would require an explicit project revocation decision; it is not inferred merely from `review pending` state.
