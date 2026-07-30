# Third-party software and notices

Remote Dev project code is licensed under Apache-2.0. That project license does not replace, extend or relicense software supplied by Ubuntu, OpenAI, GitHub, Google, Astral or other upstream projects.

This shared directory records what the published base and final Codex images distribute, where each component comes from and how its original license or notice is preserved. Rows marked final-image-only do not claim that the component is present in `remote-dev-base`. It is an attribution and maintenance record, not legal advice.

## Inspecting notices

In the repository, start with this file and `third_party/optional-agents.md`.

In a built image, run:

```text
remote-dev-notices
remote-dev-notices --versions
remote-dev-notices --list
remote-dev-notices --check
```

The canonical image path is:

```text
/usr/share/doc/remote-dev/third_party
```

`BUILD-VERSIONS.env` records the exact base, runtime and direct-download values used to build the image. For Python, Node.js and uv it includes the version, architecture-specific URL and SHA-256 selected from `mise.lock`. A final Codex image also contains `CODEX-BUILD.env` with its exact source revision, image version and Codex release asset pins. These files are generated from build inputs rather than duplicated manually in this inventory.

Ubuntu package copyright files remain available under `/usr/share/doc/<package>/copyright`. Generated release SBOMs supplement this human-maintained inventory; they do not replace required license or NOTICE files.

Because the image aggregates software under many licenses, it deliberately does not set the OCI-standard `org.opencontainers.image.licenses` field to a project-only value. Project-owned code is identified separately by `io.github.experience83.remote-dev.project-license=Apache-2.0`, while the notice-path and license-scope annotations direct users to the complete bundled inventory. The final image's documentation URL is pinned to its embedded source revision.

## Bundled component inventory

Versions are resolved from `versions.env`, `mise.toml` and the exact versions, URLs and checksums in `mise.lock`. Architecture-specific release assets use the same license entry. The exact values embedded in a particular image are shown by `remote-dev-notices --versions`.

| Component | Version source and distributed artifact | Upstream source | License / notice treatment | Image notice location |
|---|---|---|---|---|
| Ubuntu base | `UBUNTU_VERSION` and `UBUNTU_DIGEST` | `docker.io/library/ubuntu` | Ubuntu and installed APT packages use multiple licenses. Package-provided copyright files are retained under `/usr/share/doc`; exact packages are also represented in the SBOM. | `/usr/share/doc/<package>/copyright` |
| APT-installed tools and libraries | `images/base/Dockerfile` | Ubuntu archives and the individual upstream projects | Multiple licenses. The image does not delete package copyright files. | `/usr/share/doc/<package>/copyright` |
| OpenAI Codex CLI (**final Codex image only**) | `CODEX_RELEASE_TAG`; official musl release archive from `github.com/openai/codex` | <https://github.com/openai/codex> | Apache-2.0. The upstream NOTICE is preserved verbatim. The Apache-2.0 text is the same text as the repository root `LICENSE` and is copied into the component notice directory in the final image. The `remote-dev-base` image does not install Codex. | `components/codex/` |
| GitHub CLI | `GH_VERSION`; official release archive from `github.com/cli/cli` | <https://github.com/cli/cli> | MIT; exact upstream copyright and license text preserved. | `components/github-cli/LICENSE` |
| ttyd | `TTYD_VERSION`; official release binary from `github.com/tsl0922/ttyd` | <https://github.com/tsl0922/ttyd> | MIT; exact upstream copyright and license text preserved. | `components/ttyd/LICENSE` |
| mise | `MISE_VERSION`; official release binary from `github.com/jdx/mise` | <https://github.com/jdx/mise> | MIT; exact upstream copyright and license text preserved. | `components/mise/LICENSE` |
| Python runtime | `PYTHON_VERSION`; exact `astral-sh/python-build-standalone` `install_only_stripped` archive pinned in `mise.lock` | <https://github.com/astral-sh/python-build-standalone> and <https://github.com/python/cpython> | The stripped runtime archive omits CPython's primary license. The exact `LICENSE` from the matching CPython `v3.14.6` tag is therefore preserved at `components/python/LICENSE` and copied into `runtime/python/LICENSE.cpython.txt`. Its reviewed version, source URL and Git content identity are recorded in `components/python/SOURCE.env` and validated against `mise.lock` and the preserved file. License, NOTICE and metadata files that remain in the installed standalone artifact are copied alongside it for bundled dependencies. The build-system repository itself is MPL-2.0; that does not relicense CPython or its bundled dependencies. | `components/python/LICENSE`, `components/python/SOURCE.env` and `runtime/python/` |
| Node.js runtime | `NODE_VERSION`; exact official Node.js archive pinned in `mise.lock` | <https://github.com/nodejs/node> | MIT for Node.js plus the third-party terms embedded in Node's upstream `LICENSE`. The complete upstream file is copied from the installed runtime. | `runtime/node/LICENSE` |
| npm CLI | `NPM_VERSION`; npm package installed verbatim from the npm registry with lifecycle scripts disabled | <https://github.com/npm/cli> | Artistic-2.0 for the npm application, plus dependency-specific terms. The build copies every license/notice file included in the exact installed package and generates `DEPENDENCIES.txt` from its installed `package.json` metadata, including legacy `licenses` arrays. | `runtime/npm/` |
| uv | `UV_VERSION`; exact official release archive pinned in `mise.lock` | <https://github.com/astral-sh/uv> | Dual-licensed Apache-2.0 OR MIT. Both upstream license choices are preserved. | `components/uv/` |
| Remote Dev scripts and configuration | repository revision embedded in the final image | <https://github.com/eXPerience83/remote-dev-containers> | Apache-2.0 project license. | `/usr/share/doc/remote-dev/LICENSE` |

## Components not redistributed by the image

Antigravity CLI, Claude Code and other proprietary or separately governed agents are not covered by the project Apache-2.0 license merely because Remote Dev can integrate with them. The binding policy and reviewed vendor links are in `optional-agents.md`.

In particular:

- no optional proprietary agent may be downloaded silently during image build, first start or launcher startup;
- no vendor binary may be copied into GHCR unless redistribution rights are explicitly confirmed and recorded;
- installation must be initiated by the user and download directly from the vendor-controlled source;
- OAuth credentials, API tokens and account identifiers remain private to the agent service and are never copied into project diagnostics or another service;
- product names are used descriptively and do not imply affiliation, sponsorship or endorsement.

## Maintenance checklist

Every dependency or version update must preserve the following:

1. `versions.env` direct-download components and `mise.lock` runtime artifacts remain represented in this inventory.
2. The upstream project, exact version source, license identifier and required NOTICE or attribution are reviewed.
3. Any changed upstream license or NOTICE file and its reviewed source record are updated, copied verbatim and reviewed in the same pull request.
4. APT package copyright files are not removed from the image.
5. Runtime-provided license files are still discovered and copied by the image build.
6. `remote-dev-notices --check` succeeds and `remote-dev-notices --versions` reports the exact values used for that image.
7. The SBOM and the human inventory are compared for obvious omissions.
8. New vendor-hosted or proprietary tools are classified as bundled, user-installed optional software, external service, or unsupported future work.
9. Documentation does not claim that upstream products or hosted services are licensed under this repository's Apache-2.0 license.
10. Trademark and non-affiliation wording remains accurate.

## Reviewed source records

The component files under `third_party/components/` are copied from the corresponding exact upstream tags used by the current image or from stable license files that are unchanged at that tag. `components/python/SOURCE.env` ties the preserved CPython license to the Python version in `mise.lock`, its exact upstream URL and its committed Git blob identity. The version-pinning and third-party validation scripts are intended to make omissions or stale records fail CI rather than relying only on this prose.
