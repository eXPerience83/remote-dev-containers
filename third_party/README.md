# Third-party software and notices

Remote Dev project code is licensed under Apache-2.0. Software bundled into the images keeps its own upstream license, notices, trademarks and terms.

The source of truth is `third_party/inventory.json`. It lists only the components currently distributed by the base and Codex images, their pinned version source and the notice paths shipped with the image. It is intentionally declarative: this project does not attempt to parse every possible Docker, shell or package-manager command.

## Inspecting a built image

```text
remote-dev-notices
remote-dev-notices --versions
remote-dev-notices --list
remote-dev-notices --check
```

The canonical path is `/usr/share/doc/remote-dev`.

Repository-preserved license and NOTICE files live below `third_party/components/`. Node.js and npm notices are copied from the exact installed runtime artifacts during the image build. Ubuntu packages retain their package-provided files under `/usr/share/doc/<package>/copyright`.

The Python runtime comes from architecture-specific `python-build-standalone` `install_only_stripped` artifacts recorded in `mise.lock`. Those compact artifacts omit the full distribution's top-level `PYTHON.json` and `licenses/` metadata, so `scripts/sync-python-runtime-notices.py` selects the matching full archive from the same immutable release, verifies its GitHub-published SHA-256 and extracts only the legal metadata. `scripts/compact-python-runtime-notices.py` then preserves a reviewable subset containing the Python version, target, license identifiers, extension-to-license relationships and referenced license paths instead of committing the complete build metadata. AMD64 and ARM64 must expose the same license texts. The exact install and full artifact URLs, sizes and hashes remain in `components/python-build-standalone/manifest.json`.

The current upstream full archives reference but omit the zlib-ng 2.2.4 and zstd 1.5.7 license files. Those two texts are supplemented from the exact official `python/cpython-source-deps` tags with reviewed SHA-256 values. Any other referenced-but-missing license makes synchronization fail rather than being guessed or silently omitted.

## Maintenance contract

A version update is not complete until the same pull request:

1. updates `versions.env`;
2. updates the matching entry in `third_party/inventory.json`;
3. reviews and replaces any repository-preserved or artifact-derived license or NOTICE file whose upstream text changed;
4. passes `scripts/validate-third-party-inventory.sh` and the component-specific notice validators;
5. builds both images and passes `remote-dev-notices --check`.

Renovate owns standard dependency references that it understands directly, such as Dockerfile frontend images, the Ubuntu base image and pinned GitHub Actions. The custom upstream workflow owns Codex, GitHub CLI, ttyd, mise, Python, Node.js, npm and uv because those updates also require architecture-specific digests, runtime-lock regeneration and legal-inventory synchronization. Each dependency has one automation owner.

The daily upstream workflow runs `scripts/update-third-party-inventory.py --write` after changing version pins. For each already inventoried repository-sourced component it updates the exact source URL and downloads the legal document from the new version tag into the same pull request. When `mise.lock` changes the Python artifact, `scripts/regenerate-mise-lock.sh` regenerates and compacts the bounded Python legal metadata before the update commit is created. Downloads are restricted to explicitly approved HTTPS hosts and preserved notice paths are confined to `third_party/`.

Changed legal text is never accepted silently: it remains visible in the pull-request diff for human review. The robot updates `refreshed_on` when it prepares new candidate documents; `reviewed_on` records a human review and is not changed automatically. If a version-specific URL cannot be derived safely, an upstream document cannot be downloaded, an artifact digest disagrees or a referenced license is missing, the maintenance workflow fails before creating an incoherent update commit.

CI compares all tool version keys in `versions.env` with the declarative inventory. A new pinned tool therefore requires an explicit inventory entry, but the validator does not implement a general-purpose Docker or shell parser.

Generated SPDX SBOM files are uploaded with CI artifacts as a supplementary omission check. They do not replace upstream notices and are not treated as a perfect detector for standalone binaries.

## Distribution boundaries

The base image contains Ubuntu packages, GitHub CLI, ttyd, mise, Python, Node.js, npm and uv. The final image adds OpenAI Codex CLI.

Antigravity CLI, Claude Code and similar vendor-governed agents are not downloaded or redistributed by the current images. Their policy is documented in `optional-agents.md`.

The standard OCI `org.opencontainers.image.licenses` annotation is not set to a project-only value, because the images aggregate software under multiple licenses. Custom labels identify the Remote Dev project license and the notice path without relicensing bundled components.

This inventory is an attribution and maintenance record, not legal advice.
