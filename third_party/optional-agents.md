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

## Current status

- **Antigravity CLI:** planned compatibility work only; not bundled and not currently supported.
- **Claude Code:** future compatibility path only; not bundled, installed or advertised as supported.

A public download URL or public source repository is not, by itself, evidence that redistribution is permitted.
