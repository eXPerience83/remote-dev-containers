# Tool matrix

## Architecture status

The one-image, single-stack architecture is implemented. The current experimental stack instantiates fixed-role services from one intended `ghcr.io/experience83/remote-dev` image reference:

```text
Remote Dev stack
├── launcher      7680 — password-free navigation only
├── codex         7681 — authenticated terminal
└── antigravity   7682 — optional/experimental authenticated terminal
```

The launcher is not an agent container and is not a control plane: it has no agent mounts, credentials or container-engine socket. Mutable state remains private to each agent service even though executable image layers are shared.

## Public common baseline

Remote Dev-provided tools are directly available through the normal role PATH. Project-declared environments/toolchains are used explicitly when required and take precedence for that project's correctness. Remote Dev does not auto-activate project environments or mutate the global toolchain to satisfy one repository.

The canonical command inventory is [`config/common-tool-baseline.txt`](../config/common-tool-baseline.txt), installed once by the base image as root-owned mode `0444` at `/usr/share/remote-dev/common-tool-baseline.txt` and inherited by the final image. `remote-dev-base-verify` and Doctor for developer roles (Codex, Antigravity and shell) validate and read that same data file. Base Verify resolves every entry with `command -v` from `/`; Doctor reports command paths in the caller's environment. The file only defines availability checks; it does not select environments, modify PATH or install packages. Future accepted baseline additions must update this inventory and pass these checks.

| Area | Public commands |
|---|---|
| Terminal | `bash`, `tmux`, `ttyd`, `nano`, `less`, `fzf` |
| Git | `git`, `git-lfs`, `ssh`, `gh` |
| Network/TLS | `curl`, `wget`, `ip`, `ss`, `dig`, `nc`, `openssl` |
| Search/files | `rg`, `fd`, `jq`, `rsync`, `file`, `tree`, `patch` |
| Archives | `zip`, `unzip`, `tar`, `gzip`, `bzip2`, `xz`, `zstd` |
| Processes | `ps`, `pgrep`, `lsof` |
| Build | `make`, `pkg-config`, `gcc` |
| Data/templates | `sqlite3`, `envsubst` |
| Python | `python`, `python3`, `uv` |
| JavaScript | `node`, `npm`, `npx` |
| Tool manager | `mise` |
| Checks | `shellcheck` |

The image selects the Python 3.14, Node 24 LTS and npm 12 lines; exact versions remain pinned in the repository's build inputs. The existing build-essential package continues to provide additional native compiler/linker commands such as `g++`, but only `gcc` is part of the public command inventory in this phase; package membership alone does not promote every executable into the product API.

“Included” or “bundled” public tools means directly invokable from a normal developer/agent shell without activation or extra startup parameters. The navigation-only launcher is exempt from this baseline and keeps its independent reduced operational checks.

## Role-specific commands

Doctor checks these separately from the public common baseline. Codex provides `codex`, `run-codex` and its runtime/Context7/boundary managers. Antigravity provides `run-antigravity` and its admission/update/policy managers; vendor `agy` becomes directly invokable only after explicit successful admission into that role's private state. Missing optional runtimes remain unavailable without a silent download. These commands do not belong to the common inventory.

## Internal/incidental components

Remote Dev's operational commands (web startup, tmux attachment, menu, health, diagnostics and image identity) are checked separately. Image components such as `tini`, the `build-essential` package, native development libraries, CA certificates and incidental APT utilities are necessary for build/operation but are not automatically a public command API. Installing a package does not promote all its executables into the common baseline. The image also includes project-owned integration/admission code; that does not imply bundled hosted services or proprietary runtime-installed binaries.

The system Bubblewrap package/executable is deliberately absent. Supported Codex launches disable the unsupported inner sandbox explicitly; autonomous/guarded approval behavior does not replace the outer-container security boundary.

## Project toolchain resolution

Use global `python` for work that needs only the image default. For a repository's Python environment, use `.venv/bin/python -m pytest` (or its prescribed module), or explicitly run `source .venv/bin/activate` for that shell. Use `uv run ...` only when the repository declares that workflow; `pyproject.toml` alone does not establish uv ownership. For Node projects use `npm test` / `npm run ...` to reach local dependencies and executables.

The mere presence of `.venv`, `venv`, `.env`, Python metadata or `package.json` does not activate an environment, source a file or inject local executable directories into PATH. `.env` normally contains environment variables; `.venv` is a Python environment. Remote Dev does not search upward for local executables or wrap language commands to detect projects.

Project dependencies/tools such as pytest, Ruff, mypy, pre-commit, ESLint and TypeScript belong in the repository's selected environment. Global `pip install` and `npm install -g` are not fallbacks for project dependencies. `uv tool install` under the existing `UV_TOOL_DIR` remains writable development tooling state, outside the immutable baseline and outside the future trusted/persistent toolchain store (#180). Executable temporary environments use inherited `$TMPDIR`; `/tmp` remains `noexec`.

The immutable image provides the default Python/Node/uv toolchain through mise shims. A repository's normal version declarations select an installed version; an unavailable version fails clearly. Image-owned `MISE_NOT_FOUND_AUTO_INSTALL=false` and `MISE_NOT_FOUND_SYSTEM_FALLBACK=false` prevent not-found installation and silent fallback to another executable. Project `[settings]` cannot override these environment defaults.

Explicit mise actions remain available: `auto_install` and `exec_auto_install` keep their upstream defaults. A trusted declaration such as `python = { version = "3.12.1", lazy = true }` explicitly opts into installation on first use; this is outside the disabled not-found behavior and does not make the immutable store writable or provide additional supported toolchains. Remote Dev does not auto-activate project `.venv` environments.

To inspect the current project's selection, use `mise config`, `mise ls --current` and `mise which python` (or `node`/`uv`); executable project configuration remains subject to mise trust. `remote-dev-base-verify` checks the image baseline from `/`, independently of the caller's project directory.

## Service-private state

| State | Launcher | Codex | Antigravity |
|---|---:|---:|---:|
| Workspace/project collection | No | Private | Private |
| Agent authentication/configuration | No | Private | Private |
| Agent history/sessions | No | Private | Private |
| Runtime-installed agent package | No | Private optional Codex runtime | Private `agy` runtime |
| GitHub CLI configuration | No | Private | Private |
| Git global configuration | No | Private | Private |
| SSH keys/configuration | No | Private | Private |
| MCP/integration credentials | No | Private | Private when/if a reviewed integration exists |
| Browser password configuration | None in current supported launcher flow | Codex entry | Antigravity entry |

The launcher is password-free in the current supported private-network model and never receives an agent password. Codex and Antigravity keep separate password configuration entries so they can be changed independently, but the current product permits deliberate value reuse and imposes no minimum-length/composition rule. The supported stack does not mount broad home/tool roots, the parent Remote Dev data root or a Docker/Podman socket wholesale.

Each role-private `/workspace` is a project collection root. Normal agent Start/Resume selects a validated immediate child `/workspace/<project>` as the working directory; this selection is routing/session context, not isolation from sibling projects already mounted into the same role container.

## Agent availability

| Agent | Distribution in final image | Current state |
|---|---|---|
| Codex CLI | Immutable reviewed fallback bundled from the official pinned release path | **Reference implementation.** A newer compatible official runtime can be explicitly admitted into Codex-private state; the bundled CLI remains fallback |
| Antigravity (`agy`) | **Not bundled or redistributed.** Installed/updated explicitly from the reviewed official Google source into Antigravity-private persistent state | **Implemented, optional and experimental.** Project-scoped Start/Resume, conversation continuity, update/rollback, integrity and TrueNAS lifecycle evidence are complete; support remains deliberately experimental under the recorded #53 policy disposition |
| Claude Code | Not installed or advertised as available | Future dedicated research/implementation path only |
| OpenCode | Not part of this stack | Independent external project |

Missing optional vendor runtimes are reported as unavailable and are never downloaded silently during launcher/container startup.

### Codex runtime update boundary

The image-bundled Codex CLI remains immutable. `remote-dev-codex-runtime` may explicitly fetch and admit a newer compatible official release into Codex-only persisted runtime state after bounded provenance/integrity/compatibility checks. The optional runtime is outside the image build-time SBOM and never removes the bundled fallback.

### Antigravity runtime boundary

Remote Dev ships only its project-owned wrapper/admission/inspection logic. Google's installer/CLI proprietary bytes remain outside the repository and immutable image layers. Supported installation/update is explicit, vendor automatic update is disabled, and runtime integrity is checked against private admitted metadata.

The #83 maintenance path separates detection from execution:

- the scheduled read-only job downloads bounded installer/manifest/archive bytes as **data**, validates fixed origins/schema/integrity and computes installer/payload hashes without executing or extracting vendor code;
- a changed pair is represented as metadata-only review state;
- executable inspection runs only from the explicit trusted review workflow and verifies the exact pending pair before vendor execution;
- review automation is technical evidence collection, not legal/vendor approval.

## Browser authentication

Protected **agent** terminal endpoints use one runtime mechanism: `WEB_PASSWORD`.

- Codex and Antigravity keep separate configuration entries so each can be changed independently.
- A protected agent endpoint currently requires a non-empty single-line value; there is no enforced minimum length, composition rule or requirement for different values between agents.
- The operator may therefore reuse the same password value across Codex and Antigravity at this stage.
- The normal launcher is outside this password contract and remains password-free.
- The former file-backed browser-password mechanism is retired and is not part of the current persistent-data or Compose contract.
- TrueNAS/Docker root/admin can inspect deployment configuration and remains inside the trust boundary.
- Any stronger single-entry/gateway/password policy is future work under #181 or a dedicated browser-security decision.

## Optional integrations

| Integration | Bundled runtime/package | Network behavior | Private state | Current scope | Release status |
|---|---|---|---|---|---|
| Context7 for Codex | No Context7 runtime/package retained in the image; explicit device login may transiently download the reviewed `ctx7` CLI | Passive status/manual-key/remove paths are offline; explicit device login contacts Context7; explicit test and enabled Codex MCP use may contact the hosted service | Managed Context7 block in Codex config plus optional API key below Codex-private state; transient CLI/XDG/npm/login state removed after device login | Hosted Streamable HTTP MCP plus optional device-code onboarding; Remote Dev does not run `ctx7 setup` or give the transient CLI authority to rewrite Codex skills/`AGENTS.md` | Shipped in experimental `dev`/`edge`; not a stable-release claim yet |
| Context7 for Antigravity | None | None in current supported Antigravity integration | None | Tracked separately by #95 | Future/optional |

Context7 is an external service operated by Upstash and is not part of the Remote Dev image SBOM. See `docs/context7-codex.md` and `.es.md` for the lifecycle, privacy/terms and credential boundaries.

## TrueNAS host tooling

The image does not replace host-side TrueNAS administration. The supported YAML deployment uses repository scripts from the same source revision as the selected image/YAML:

| Host-side tool | Purpose |
|---|---|
| `scripts/init-data-layout.py` | Idempotently create only missing canonical role-private descendants below an already existing root dataset |
| `scripts/preflight-data-layout.py` | Validate the shared persistent-path contract before deployment |
| `scripts/truenas-acl-audit.py` | Read-only audit of the reference Generic/POSIX private-state ACL contract |

`docs/truenas-acl-contract.md` / `.es.md` own the ACL rationale and migration guidance.

## Version/release identity

The local development baseline is `0.1.1-dev`. It is a source/local-build default, not a stable release. Published edge builds use `edge-YYYY.MM.DD-<short-sha>` plus `Channel: edge`; explicit stable publication alone uses `vMAJOR.MINOR.PATCH` and moves `stable`/`latest`.

## Explicitly deferred

- Additional Python/Node major lines without an explicit migration review.
- Rust, Go, Java, Ruby, PHP, Swift, Erlang and Elixir universal preinstallation (#121 owns broader tooling decisions).
- ARM64 production support (#112).
- Optional role-scoped inbound SSH (#124).
- SMB project access (#71).
- Concurrent sessions/worktrees (#148).
- Isolated container build/test tooling without a host Docker socket (#151).
- Browser/frontend/mobile work tracked by #97/#90/#91/#152/#87.
- Native TrueNAS Community App/ixVolumes packaging (#170).
- Stronger browser access/gateway/passkey/password-policy work (#181 or a dedicated browser-security decision).
- A privileged inner-sandbox profile.
- A virtual-machine distribution.

Additions should be driven by real repositories or supported use cases and evaluated for image size, security, licensing, privacy and maintenance cost.
