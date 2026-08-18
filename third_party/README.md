# Third-party software and notices

Remote Dev project code is licensed under Apache-2.0. Software bundled into the images keeps its own upstream license, notices, trademarks and terms.

The source of truth for **distributed image components** is `third_party/inventory.json`. It lists only the components currently distributed by the base and Codex images, their pinned version source and the notice paths shipped with the image. It is intentionally declarative: this project does not attempt to parse every possible Docker, shell or package-manager command. `versions.env` may additionally carry explicitly documented review metadata for optional software that is **not** distributed; such keys must be excluded deliberately from the image-inventory comparison and must not be represented as image/SBOM content.

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

`standalone-artifact-inspection.md` and its JSON companion record a bounded inspection of the exact AMD64 and ARM64 GitHub CLI, Codex, ttyd, mise and uv assets currently pinned by the repository. The inspection confirms whether each release archive carries separate legal files and whether an embedded file matches the version-specific notice preserved here. It is current-version evidence, not a generic dependency-license scanner.

`scripts/sync-standalone-artifact-inspection.py` refreshes this evidence only for those five explicitly supported components. It downloads an asset only when its pinned version, URL, SHA-256 or preserved repository notice changed, verifies the repository-controlled digest before inspection, supports only the known `tar.gz` and raw-binary packaging forms and never extracts an archive into the filesystem. The daily upstream workflow runs it after updating pins and `mise.lock`, so the generated JSON and Markdown remain in the same reviewable pull request as the version change.

CI remains offline for this evidence: `scripts/validate-standalone-artifact-inspection.py` compares the committed report's component versions, asset URLs and SHA-256 values with `versions.env` and `mise.lock`. An update PR cannot pass validation with stale evidence, while ordinary builds do not redownload release assets.

`antigravity-cli-inspection.md` and its JSON companion record the separate pre-implementation inspection of Google's optional proprietary CLI. The dedicated read-only workflow downloads the current official installer into an ephemeral credential-free home, records bounded metadata for the installer and resulting executable, and uploads no vendor bytes. This evidence supports the no-redistribution and explicit vendor-install decision in `optional-agents.md`; Antigravity remains outside the image inventory and image SBOM because it is not bundled.

Context7 follows the same non-distribution accounting boundary for its optional authentication CLI. `CONTEXT7_CLI_VERSION` and `CONTEXT7_CLI_SRI_SHA512` in `versions.env` record only the exact top-level CLI artifact whose transient `login --no-browser` surface Remote Dev has reviewed. The CLI is resolved/downloaded from the official public npm registry only after explicit user action and is removed afterward; it is intentionally absent from `third_party/inventory.json`, image notices and image SBOM content.

The broader human review is tracked by the standing six-month maintenance issue #53, with additional reviews before stable releases and when distribution terms, packaging, authentication or optional-agent policies change.

## Maintenance contract

For a version update to a **distributed image component**, the same pull request must:

1. update `versions.env`;
2. update the matching entry in `third_party/inventory.json`;
3. review and replace any repository-preserved or artifact-derived license or NOTICE file whose upstream text changed;
4. refresh the bounded standalone-artifact report when GitHub CLI, Codex CLI, ttyd, mise or uv changes;
5. pass `scripts/validate-third-party-inventory.sh` and the component-specific notice validators;
6. build both images and pass `remote-dev-notices --check`.

Explicit non-distributed review metadata is maintained separately from that image-inventory contract. Changing such a pin still requires the owning legal/privacy/supply-chain review and focused tests, but must not create a fake distributed-component inventory entry.

Renovate owns standard dependency references that it understands directly, such as Dockerfile frontend images, the Ubuntu base image and pinned GitHub Actions. The custom upstream workflow owns Codex, GitHub CLI, ttyd, mise, Python, Node.js, npm and uv because those updates also require architecture-specific digests, runtime-lock regeneration and legal-inventory synchronization. It also owns detection/proposal of reviewed metadata for optional Context7 CLI and, once #83 is complete, Antigravity review evidence without turning either optional agent into image content. Each dependency has one automation owner.

The daily upstream workflow runs `scripts/update-third-party-inventory.py --write` after changing distributed version pins. For each already inventoried repository-sourced component it updates the exact source URL and downloads the legal document from the new version tag into the same pull request. When `mise.lock` changes the Python artifact, `scripts/regenerate-mise-lock.sh` regenerates and compacts the bounded Python legal metadata before the update commit is created. It then runs `scripts/sync-standalone-artifact-inspection.py` to refresh exact packaging evidence for any changed supported standalone asset. Downloads are restricted to explicitly approved HTTPS hosts and preserved notice paths are confined to `third_party/`.

Changed legal text and changed packaging evidence are never accepted silently: they remain visible in the pull-request diff for human review. The robot updates `refreshed_on` when it prepares new candidate documents; `reviewed_on` records a human review and is not changed automatically. If a version-specific URL cannot be derived safely, an upstream document cannot be downloaded, an artifact digest disagrees, AMD64 and ARM64 legal-file findings differ or a referenced license is missing, the maintenance workflow fails before creating an incoherent update commit.

CI compares distributed tool version keys in `versions.env` with the declarative image inventory. Explicitly documented non-distributed review metadata such as `CONTEXT7_CLI_VERSION` and `CONTEXT7_CLI_SRI_SHA512` is excluded from that equality check and validated by its owning feature tests. A new **distributed** pinned tool still requires an explicit inventory entry; the validator does not implement a general-purpose Docker or shell parser.

Generated SPDX SBOM files are uploaded with CI artifacts as a supplementary omission check. They do not replace upstream notices and are not treated as a perfect detector for standalone binaries.

## Distribution boundaries

The base image contains Ubuntu packages, GitHub CLI, ttyd, mise, Python, Node.js, npm and uv. The final image adds OpenAI Codex CLI.

Antigravity CLI, Context7 CLI, Claude Code and similar vendor-governed/optional tools are not downloaded or redistributed by the current images. Context7 CLI may be downloaded transiently from npm only during explicit device authentication and is removed before the resulting key is adopted. Their policy is documented in the relevant optional-agent/integration documentation.

The standard OCI `org.opencontainers.image.licenses` annotation is not set to a project-only value, because the images aggregate software under multiple licenses. Custom labels identify the Remote Dev project license and the notice path without relicensing bundled components.

This inventory is an attribution and maintenance record, not legal advice.
