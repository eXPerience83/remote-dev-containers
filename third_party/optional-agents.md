# Optional vendor agents

Antigravity CLI, Claude Code and similar agents are not bundled, downloaded or redistributed by the current Remote Dev images. They are not covered by the repository's Apache-2.0 license.

Any future optional-agent integration must be implemented in a separate pull request and must satisfy all of these conditions:

1. Installation is an explicit user action.
2. The package is downloaded directly from a vendor-controlled source.
3. Redistribution rights are verified before any binary is added to a public image.
4. The user is shown that separate vendor terms, privacy policies and account requirements apply.
5. Remote Dev does not claim vendor affiliation or endorsement.
6. Credentials and OAuth state remain inside that agent service's private storage.
7. Diagnostics do not read, print, export or reuse secret contents.
8. The official client is used rather than an unofficial service client.
9. Owned files, update behavior and uninstall behavior are documented before support is claimed.
10. The review is repeated when the vendor changes its installer, terms, privacy behavior or state paths.

## Antigravity inspection status

The official Linux AMD64 installer and resulting package were inspected on 2026-08-02 in an ephemeral, credential-free workflow. See:

- `third_party/antigravity-cli-inspection.md`;
- `third_party/antigravity-cli-inspection.json`;
- `.github/workflows/inspect-antigravity-cli.yml`.

The inspection confirms a viable explicit vendor-install path but does **not** grant redistribution permission or make the integration supported yet.

The current installer:

- supports `--dir <path>`;
- does not support the older documented `--skip-aliases` or `--skip-path` flags;
- can install without modifying shell profiles when given a private explicit destination;
- installs one proprietary `agy` executable and no separate license/notice files;
- reports that normal CLI runs perform background self-updates.

Consequently, the planned runtime integration must:

- keep the installer and binary out of the public image and repository;
- download the installer to a temporary file from the fixed official endpoint;
- verify the live installer contract before executing it;
- install only into Antigravity-owned persistent storage;
- set `AGY_CLI_DISABLE_AUTO_UPDATE=true` for normal launches;
- expose updates only through a separate explicit reviewed action;
- keep Antigravity state, credentials, histories, plugins and updater files isolated from Codex and the launcher.

## Current support status

- **Antigravity CLI:** installer/package inspection completed; optional runtime integration still pending under #27. Not bundled and not yet supported.
- **Claude Code:** future compatibility path only; not bundled, installed or advertised as supported.

A public download URL or public source repository is not, by itself, evidence that redistribution is permitted.
