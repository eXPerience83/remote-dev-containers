# Optional vendor agents

Antigravity CLI, Claude Code and similar vendor agents are not covered by this repository's Apache-2.0 license. Remote Dev does not redistribute their installers, executables, credentials or account state.

## Distribution and availability policy

An optional vendor agent may be integrated only when all of these conditions are satisfied:

1. Installation and update are explicit user actions.
2. The package is downloaded directly from a fixed vendor-controlled HTTPS source.
3. Network bytes are saved to a private bounded staging file and are never piped directly into a shell.
4. The manager validates the final origin, minimum installer contract, expected package location, executable type, architecture and version behavior before publication.
5. Normal startup, health checks, diagnostics and agent launch never download or update the product.
6. Vendor self-update is disabled when the vendor provides a supported control.
7. The installed executable is recorded in a private local integrity manifest and rechecked before every launch.
8. A failed update leaves the previous working installation usable, with a local rollback copy where the integration implements one.
9. The user is shown that separate vendor terms, privacy policies and account requirements apply.
10. Credentials and OAuth state remain inside that agent service's private storage and are never copied, inspected, exported or reused by Remote Dev.
11. Review evidence and documentation are refreshed when the vendor changes its installer, packaging, terms, privacy behavior or state paths.
12. Remote Dev never claims vendor affiliation or endorsement.

The Remote Dev image controls the hardened installation method, but it must not become a routine availability gate for software it cannot redistribute. A version installed explicitly through the fixed official-source flow may remain usable while Remote Dev's human review is pending, provided the local executable still matches the integrity manifest created during that installation.

## Review states

Optional vendor installations use three distinct states:

- **Official, reviewed:** the local version, size and SHA-256 match the current committed inspection evidence.
- **Official, review pending:** the version was installed through the hardened fixed official-source flow and still matches its private local manifest, but the committed Remote Dev evidence describes a different version or payload.
- **Damaged or locally modified:** the executable or manifest is absent, malformed or no longer matches. This state is blocked until an explicit repair/update succeeds.

`Review pending` is not a claim that Remote Dev has audited the new payload. It means only that the local copy was produced by the explicit official-source installation flow and has not changed since. Absence from the review catalogue is not a revocation. Any future revocation must identify a specific version or hash and be separately documented and tested.

## Antigravity CLI

Antigravity is integrated as an **experimental**, isolated service. The public Remote Dev image contains only project-owned wrappers, path definitions and metadata-only review evidence. It does not contain Google's installer or `agy` executable.

The canonical manager supports:

```text
remote-dev-antigravity install
remote-dev-antigravity update
remote-dev-antigravity rollback
remote-dev-antigravity status
```

Installation and update:

- use only `https://antigravity.google/cli/install.sh`;
- require explicit confirmation or `--yes`;
- reject redirects outside the fixed official endpoint;
- enforce bounded installer and payload sizes;
- validate the live `--dir <path>` contract in a credential-free isolated home;
- install to Antigravity-owned staging under persistent runtime state rather than executable `/tmp`;
- require a Linux AMD64 ELF candidate with bounded `--version` and `--help` behavior;
- write a private local manifest containing version, sizes, hashes, source and install time;
- atomically publish only after validation;
- retain one previous working executable/manifest for rollback;
- leave `AGY_CLI_DISABLE_AUTO_UPDATE=true` for validation and normal sessions.

An image update does not force an Antigravity update and does not invalidate an intact earlier installation. Conversely, Google may publish a newer version that an older compatible image can install without waiting for Remote Dev to publish another image. A new image is needed only when Google's live contract changes beyond what the existing hardened manager can safely validate.

The latest committed review snapshot is described in:

- `third_party/antigravity-cli-inspection.md`;
- `third_party/antigravity-cli-inspection.json`;
- `.github/workflows/inspect-antigravity-cli.yml`.

Those files are review evidence, not redistributed vendor bytes and not a routine runtime allowlist.

## Codex CLI

Codex remains bundled in the Remote Dev image from an official pinned OpenAI release and is the guaranteed fallback. It is not governed by the Antigravity runtime installer.

A future explicit Codex runtime-update feature may install a newer official OpenAI release into separate persistent agent-owned storage, but it must:

- retain the bundled image copy unchanged;
- verify the optional candidate independently;
- select the optional copy only when valid;
- fall back automatically to the bundled copy when the optional installation is absent or invalid;
- never update during normal startup;
- be implemented and reviewed in a separate focused issue and pull request.

## Claude Code and other agents

Claude Code remains a future compatibility path only. No package, mount, menu entry, credential variable or support claim should be added until the triggers and research in #30 authorize focused implementation work.

A public download URL or source repository is not, by itself, evidence that redistribution is permitted.
