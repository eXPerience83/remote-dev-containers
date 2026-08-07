# Antigravity runtime admission

## Status and scope

Antigravity CLI is an optional Google product. Remote Dev does not bundle, copy or redistribute its installer or executable. Installation and update are explicit user actions performed inside the isolated Antigravity service.

The service must run with `REMOTE_DEV_ROLE=antigravity` and the explicit `REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1` opt-in. The Antigravity role remains unavailable while that experimental gate is disabled. Enabling it does not make Antigravity a stable or fully supported Remote Dev component; the current edge integration remains experimental until its documented real-environment gates are complete.

This document defines the runtime availability and integrity model implemented under issue #96. Scheduled upstream detection and evidence-refresh automation remain separate under issue #83. Broad documentation/status synchronization remains under issue #92.

## Availability model

A compatible Antigravity release may be installed or updated from Google's fixed official installer endpoint without waiting for a new Remote Dev image. Committed inspection evidence describes the exact version already reviewed by Remote Dev; it is not an allowlist and absence from it is not a revocation.

Normal container startup, status checks and agent launches never contact the installer endpoint and never update the executable. Status verifies local file identity and performs a bounded `--version` check with a private temporary home and vendor auto-update disabled. `AGY_CLI_DISABLE_AUTO_UPDATE=true` remains mandatory for normal Antigravity sessions.

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

The menu and diagnostics expose only bounded, non-secret state:

- **Official and reviewed**: the executable and private manifest are intact and match the committed Remote Dev inspection evidence.
- **Official source; Remote Dev review pending**: the executable was admitted through the explicit official-origin flow and still matches its private manifest, but the exact installer/payload is absent from current image evidence. It remains runnable.
- **Damaged or locally modified**: the executable or manifest is missing, symlinked, permission-invalid, malformed or identity-mismatched. Launch is blocked until an explicit update repairs it.

“Official source; review pending” records the controlled download path and local manifest integrity. It is not a claim of cryptographic Google signing, Remote Dev certification, inclusion in the image SBOM or coverage by Apache-2.0.

## Image replacement and rollback

An intact installed version remains usable when a newer or older Remote Dev image contains different review evidence. Changing the image may change only the displayed review state. It does not invalidate or replace the persisted executable.

A successful explicit update replaces the persisted executable. A failed download, contract check, candidate validation or publication keeps the previous executable and manifest usable. The same explicit update command repairs partial state when either the executable or manifest is missing; a first-install command refuses to overwrite such damaged remnants silently.

## Threat boundary

The private manifest detects independent executable or manifest modification and accidental corruption. It does not protect against an attacker or process that already controls the Antigravity service user or container root and can coherently replace both files. That limitation matches the project's single-user outer-container trust model.

The downloaded installer remains vendor code. Running it as an unprivileged identity with an empty environment and a private staging subtree reduces exposure to mounted credentials, but does not transform it into a sandboxed or independently audited program.

## Review automation

Issue #83 may detect installer/package changes and open one human-review pull request containing normalized metadata and refreshed evidence. That automation must not approve, merge, publish or revoke a runtime version automatically. Runtime availability is governed by the compatible explicit-install contract above.
