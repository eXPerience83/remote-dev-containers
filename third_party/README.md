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

## Maintenance contract

A version update is not complete until the same pull request:

1. updates `versions.env`;
2. updates the matching entry in `third_party/inventory.json`;
3. reviews and replaces any repository-preserved license or NOTICE file whose upstream text changed;
4. passes `scripts/validate-third-party-inventory.sh`;
5. builds both images and passes `remote-dev-notices --check`.

The daily upstream workflow runs `scripts/update-third-party-inventory.py --write` after changing version pins. For each already inventoried component it updates the exact reviewed source URL and downloads the legal document from the new version tag into the same pull request. Changed legal text is never accepted silently: it remains visible in the pull-request diff for human review. If the version-specific URL cannot be derived safely or the upstream document cannot be downloaded, the maintenance workflow fails before creating an incoherent update commit.

CI compares all tool version keys in `versions.env` with the declarative inventory. A new pinned tool therefore requires an explicit inventory entry, but the validator does not implement a general-purpose Docker or shell parser.

Generated SPDX SBOM files are uploaded with CI artifacts as a supplementary omission check. They do not replace upstream notices and are not treated as a perfect detector for standalone binaries.

## Distribution boundaries

The base image contains Ubuntu packages, GitHub CLI, ttyd, mise, Python, Node.js, npm and uv. The final image adds OpenAI Codex CLI.

Antigravity CLI, Claude Code and similar vendor-governed agents are not downloaded or redistributed by the current images. Their policy is documented in `optional-agents.md`.

The standard OCI `org.opencontainers.image.licenses` annotation is not set to a project-only value, because the images aggregate software under multiple licenses. Custom labels identify the Remote Dev project license and the notice path without relicensing bundled components.

This inventory is an attribution and maintenance record, not legal advice.
