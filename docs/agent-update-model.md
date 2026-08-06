# Agent installation, updates and image independence

## Decision

Remote Dev separates three concerns that must not be conflated:

1. **Image delivery:** immutable project code, shared tools and a bundled Codex fallback.
2. **Explicit vendor installation:** user-requested acquisition of software that Remote Dev cannot redistribute.
3. **Human review evidence:** metadata and compatibility evidence maintained by pull request.

Publishing a new Docker image must not be required for every normal upstream agent release. An image is required only when project code, compatibility logic or security policy must change.

## Antigravity

Antigravity is downloaded only after an explicit install or update action. The manager uses Google's fixed official HTTPS installer endpoint, validates the response and installer contract, installs into a private staging area, validates the resulting Linux AMD64 executable and records a local integrity manifest before atomic publication.

Normal launch performs no network download. It validates the installed executable against its local manifest and sets `AGY_CLI_DISABLE_AUTO_UPDATE=true`.

The committed inspection report identifies the most recently reviewed payload. A newer official-source installation is shown as `official, review pending`; it remains usable while its local integrity checks pass. A changed or corrupt local copy is blocked.

One previous working Antigravity executable and manifest are retained for explicit rollback. A failed update does not replace the active installation.

## Codex

Codex remains included in every Remote Dev image as a known fallback. The current implementation continues to use that bundled executable.

The planned explicit Codex updater will be separate from the Antigravity implementation. It must obtain an official OpenAI artifact, verify it, store it outside immutable image paths and fall back to the bundled executable whenever the optional copy is missing or invalid.

## Review automation

Issue #83 tracks scheduled detection and human review of Antigravity changes. The automation should:

- detect changes at the fixed installer endpoint;
- retain and upload metadata only;
- open or refresh one review pull request;
- run the dedicated inspection, runtime regressions, AMD64 build/smoke, SBOM, Trivy and critical-vulnerability gate;
- never auto-merge or silently promote evidence;
- never disable an intact installed version solely because review is pending.

Review evidence improves confidence and catches contract drift. It is not a licence to redistribute the product and is not the normal availability gate.

## Failure boundary

An older image may still require an update if the vendor changes the installer URL, origin, flags, package layout, architecture, executable behavior or another contract beyond the manager's bounded validators. The design removes routine version/hash churn as an image dependency; it cannot safely promise compatibility with arbitrary future vendor changes.
