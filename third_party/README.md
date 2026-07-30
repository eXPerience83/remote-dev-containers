# Third-party software and notices

Remote Dev project code is licensed under Apache-2.0. That project license does not replace, extend or relicense software supplied by Ubuntu, OpenAI, GitHub, Google, Astral or other upstream projects.

This file is generated from `third_party/inventory.json` and the current build recipes. Edit the machine-readable inventory, then run `python3 scripts/legal-inventory.py render`. It is an attribution and maintenance record, not legal advice.

## Inspecting notices

In a built image, run:

```text
remote-dev-notices
remote-dev-notices --versions
remote-dev-notices --list
remote-dev-notices --check
```

The canonical image path is `/usr/share/doc/remote-dev/third_party`.

`BUILD-VERSIONS.env` records exact build values and locked runtime artifact URLs/checksums. `sources.lock.json` binds every repository-preserved upstream legal document to its exact version, URL and Git blob identity. Ubuntu package copyright files remain under `/usr/share/doc/<package>/copyright`. Generated SPDX SBOMs are reconciled against this inventory in CI; they supplement rather than replace required notices.

Because the image aggregates software under many licenses, it deliberately does not set `org.opencontainers.image.licenses` to a project-only value. Project-owned code is identified separately by `io.github.experience83.remote-dev.project-license=Apache-2.0`.

## Bundled component inventory

| Component | Exact version source | Distribution and upstream | License / notice treatment | Image notice location | SBOM treatment |
|---|---|---|---|---|---|
| Ubuntu base | `UBUNTU_VERSION` = `26.04` | Pinned OCI base image (base and final images); https://hub.docker.com/_/ubuntu | Multiple upstream licenses. The pinned base digest and package database identify the exact Ubuntu content. Ubuntu is named descriptively; no Canonical affiliation or endorsement is claimed. | `/usr/share/doc/<package>/copyright` | required |
| APT-installed tools and libraries | Parsed from the apt-get install block | Packages installed from Ubuntu archives (base and final images); Ubuntu archives and each package's upstream project | Multiple upstream licenses. Package-provided copyright and license files are retained. The direct package list is generated below from the Dockerfile. Package and project names are used only to identify shipped software. | `/usr/share/doc/<package>/copyright` | covered-by-ecosystem |
| OpenAI Codex CLI | `CODEX_RELEASE_TAG` = `rust-v0.146.0` | Official pinned musl release archive (final image only); https://github.com/openai/codex | Apache-2.0. The upstream NOTICE from the exact selected release is preserved verbatim. The Apache-2.0 license text is available through the project license copy and is not used to relicense Codex. OpenAI and Codex are used descriptively; the image states that it is community maintained and not affiliated with OpenAI. | `components/codex/NOTICE`<br>`components/codex/LICENSE-APACHE-2.0` | not-guaranteed: A standalone Rust binary may not be represented as a package by every SBOM generator; direct-download discovery and build manifests remain authoritative. |
| GitHub CLI | `GH_VERSION` = `2.96.0` | Official pinned release archive (base and final images); https://github.com/cli/cli | MIT. The exact upstream LICENSE from the matching release tag is preserved verbatim and version-locked. GitHub and GitHub CLI are used descriptively; no GitHub affiliation or endorsement is claimed. | `components/github-cli/LICENSE` | not-guaranteed: The installed standalone Go binary may not be emitted as a package; its direct-download pin and source-locked license are validated separately. |
| ttyd | `TTYD_VERSION` = `1.7.7` | Official pinned release binary (base and final images); https://github.com/tsl0922/ttyd | MIT. The exact upstream LICENSE from the matching release tag is preserved verbatim and version-locked. The project name is used only to identify the shipped executable. | `components/ttyd/LICENSE` | not-guaranteed: The installed standalone binary may not be emitted as a package; its direct-download pin and source-locked license are validated separately. |
| mise | `MISE_VERSION` = `2026.7.17` | Official pinned release binary (base and final images); https://github.com/jdx/mise | MIT. The exact upstream LICENSE from the matching release tag is preserved verbatim and version-locked. The project name is used only to identify the shipped executable. | `components/mise/LICENSE` | not-guaranteed: The installed standalone binary may not be emitted as a package; its direct-download pin and source-locked license are validated separately. |
| Python runtime | `mise.lock` tool `python` = `3.14.6` | Exact astral-sh/python-build-standalone install_only_stripped archive selected by mise.lock (base and final images); https://github.com/astral-sh/python-build-standalone and https://github.com/python/cpython | Python-2.0 plus bundled dependency licenses. The stripped archive omits CPython's primary license, so the exact matching CPython LICENSE is source-locked and copied alongside every license or notice still present in the installed artifact. Python is used descriptively; no Python Software Foundation endorsement is claimed. | `components/python/LICENSE`<br>`runtime/python/` | covered-by-ecosystem |
| Node.js runtime | `mise.lock` tool `node` = `24.18.1` | Exact official Node.js archive selected by mise.lock (base and final images); https://github.com/nodejs/node | MIT plus third-party terms embedded in Node.js LICENSE. The complete LICENSE is copied from the exact installed runtime artifact. Node.js is used descriptively; no OpenJS Foundation endorsement is claimed. | `runtime/node/LICENSE` | not-guaranteed: Runtime package detection varies by SBOM generator; the exact mise artifact URL/checksum and copied runtime LICENSE are validated in the image. |
| npm CLI and bundled dependencies | `NPM_VERSION` = `12.0.2` | Exact npm registry package installed globally with lifecycle scripts disabled (base and final images); https://github.com/npm/cli and the npm registry | Artistic-2.0 plus dependency-specific licenses. Every LICENSE, COPYING and NOTICE file in the exact installed npm package tree is copied; dependency metadata is generated from installed package.json files. npm is used descriptively; no npm or GitHub endorsement is claimed. | `runtime/npm/`<br>`runtime/npm/DEPENDENCIES.txt` | covered-by-ecosystem |
| uv | `mise.lock` tool `uv` = `0.12.0` | Exact official release archive selected by mise.lock (base and final images); https://github.com/astral-sh/uv | Apache-2.0 OR MIT. Both exact upstream license choices from the matching release tag are preserved verbatim and version-locked. The project name is used only to identify the shipped executable. | `components/uv/LICENSE-APACHE-2.0`<br>`components/uv/LICENSE-MIT` | not-guaranteed: The standalone Rust binary may not be emitted as a package; the exact mise artifact and both source-locked licenses are validated separately. |
| Remote Dev scripts and configuration | repository/build revision (`0.1.0-dev`) | Project-owned repository content copied into the image (project files); https://github.com/eXPerience83/remote-dev-containers | Apache-2.0. The repository root LICENSE is copied into the image. This project license applies only to project-owned content. Documentation expressly disclaims affiliation with OpenAI, Google, Anthropic and other vendors. | `/usr/share/doc/remote-dev/LICENSE` | not-applicable: Project scripts are image content rather than a separately versioned third-party package. |

## Direct APT package set

The following package names are parsed directly from the `apt-get install --no-install-recommends` block. Adding or removing a package changes this generated list and is validated against the image SPDX SBOM:

```text
bash
build-essential
ca-certificates
curl
fd-find
fzf
git
git-lfs
gzip
jq
less
libbz2-dev
libffi-dev
liblzma-dev
libreadline-dev
libsqlite3-dev
libssl-dev
make
nano
openssh-client
patch
pkg-config
procps
ripgrep
rsync
shellcheck
sqlite3
tar
tini
tmux
tzdata
unzip
wget
xz-utils
zip
zlib1g-dev
```

## Components not redistributed by the image

Antigravity CLI, Claude Code and other separately governed agents are not covered by the project Apache-2.0 license merely because Remote Dev can integrate with them. The binding policy and reviewed vendor links are in `optional-agents.md`.

## Maintenance behavior

- Version automation refreshes repository-preserved legal documents from exact upstream tags and updates `sources.lock.json` in the same pull request.
- Changed license or NOTICE text is never silently accepted: it appears as a normal reviewed diff.
- A new version/checksum input, direct-download URL, mise runtime, global npm package or SBOM package ecosystem fails validation until it has an inventory owner.
- Runtime-provided Python, Node.js and npm notices are copied from the exact installed artifacts during image construction.
- A new APT package is discovered automatically, rendered in this file and required to appear in the generated SPDX SBOM.
- Optional proprietary integrations remain user-initiated and vendor-sourced; they require a separate terms, privacy, ownership and uninstall review before support is claimed.
