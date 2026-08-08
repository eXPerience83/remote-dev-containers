# Codex runtime updates

Remote Dev always ships an immutable, image-tested Codex CLI. An administrator may also install a newer official Codex runtime explicitly without rebuilding or replacing the container image.

This mechanism is deliberately similar to the Antigravity runtime admission model, with one important difference: OpenAI currently publishes the Codex CLI/package under its own upstream Apache-2.0 license terms and provides complete package archives. Those upstream terms and notices remain applicable to the downloaded Codex package; the Remote Dev project license does not extend to third-party components. Remote Dev therefore downloads the exact official Codex package instead of executing the mutable upstream installer.

These trust states describe the upstream Codex runtime package, not the stability of Remote Dev itself. The public Remote Dev `edge` image remains experimental and is not a stable Remote Dev release; see [release channels and promotion criteria](releases.md).

## Trust states

The menu, `remote-dev-version` and `remote-dev-doctor` distinguish these states:

- **Bundled** — the Codex release built into the Remote Dev image. This is the image-tested fallback.
- **Official source; Remote Dev review pending** — a newer stable Codex package was explicitly downloaded from OpenAI's official GitHub release, its release-metadata SHA-256 and package identity were verified, and bounded compatibility probes passed. Remote Dev has not yet reviewed and real-world tested that exact upstream release as part of an image build.
- **Damaged or locally modified** — the persistent optional runtime no longer matches its private manifest or violates the expected file/directory identity. Remote Dev refuses it and uses the bundled fallback.
- **Bundled preferred** — an optional runtime is equal to or older than the Codex release now bundled in the image. The newer/equivalent image-tested copy wins automatically.

“Review pending” does **not** mean that the download is accepted without integrity checks. Source origin, stable release tag, architecture, release digest, package layout, file identities and compatibility probes are verified before publication. The pending part is Remote Dev's review and real deployment validation for that exact Codex release.

## Explicit-only network access

Normal startup, `status`, `resolve`, Codex launch, resume, health checks and diagnostics do not contact the update endpoint.

Network access happens only after an explicit update action:

```bash
remote-dev-codex-runtime update
```

The interactive command asks for confirmation **before** contacting the official release endpoint. `--yes` is available for an administrator who is already making an explicit non-interactive update request:

```bash
remote-dev-codex-runtime update --yes
```

The menu exposes the same explicit update action. There is no background updater and no silent runtime replacement.

## Official package boundary

The updater accepts only the latest exact stable `rust-vX.Y.Z` release and only the matching Linux musl architecture package:

```text
codex-package-x86_64-unknown-linux-musl.tar.gz
codex-package-aarch64-unknown-linux-musl.tar.gz
```

The complete upstream package is used because Codex resolves required companions and resources relative to that package root. The expected layout includes:

```text
bin/codex
bin/codex-code-mode-host
codex-path/rg
codex-resources/bwrap
codex-package.json
```

Additional normal files under the canonical upstream package directories are allowed, but absolute paths, traversal, links, devices, FIFOs, unexpected top-level paths and excessive archive sizes/member counts are rejected.

The package is kept outside the real `CODEX_HOME`. This is intentional. `CODEX_HOME=/root/.codex` remains exclusively the user credential/config/session boundary, while the optional runtime lives at:

```text
/root/.local/share/remote-dev/codex-runtime
```

That path is mounted only into the Codex service. The launcher and Antigravity service do not receive it.

Keeping the package outside `CODEX_HOME/packages/standalone/releases` also prevents Codex from classifying the Remote Dev-managed copy as its own standalone installation and bypassing this explicit update manager through the upstream self-update path.

## Admission checks

Before an optional runtime becomes active, Remote Dev:

1. fetches release metadata from the fixed official OpenAI Codex GitHub repository;
2. requires an exact stable release tag;
3. selects only the package matching the current supported architecture;
4. verifies the package size and GitHub release SHA-256 metadata while streaming the download;
5. extracts with bounded archive rules and rejects links/special files/path traversal;
6. verifies canonical Codex package metadata and required executables;
7. executes changed vendor bytes with a synthetic credential-free `HOME`/`CODEX_HOME`, outside the user workspace and, when running as root, under a fixed unprivileged UID/GID;
8. bounds candidate execution time and captured output;
9. checks `codex --version`, required launcher flags and the `codex-code-mode-host --listen ws://127.0.0.1:0` + `/readyz` contract;
10. fingerprints every published file into a restrictive private manifest;
11. atomically switches the active pointer only after all checks pass.

Mutation is serialized with a private lock. Failed or interrupted admission leaves the previous active runtime untouched. Normal launch does not use that lock: it verifies the immutable published file set and can fall back immediately to the bundled CLI.

## Launch and fallback

All supported Codex start/resume paths continue through `run-codex`. The launcher first validates the project-owned approval/sandbox policy and then asks the local runtime manager for the active executable.

A newer valid optional runtime is selected. If the resolver fails, state is damaged, the selected executable is unavailable, or the optional release is no newer than the bundled release, `run-codex` selects `/usr/local/bin/codex` instead.

The existing isolation contract is unchanged: Remote Dev still passes `--sandbox danger-full-access` because the outer container is the supported isolation boundary. The complete optional package contains the upstream Bubblewrap resource, but Remote Dev does not install a system `bwrap` command and does not enable the nested sandbox.

## Status and removal

```bash
remote-dev-codex-runtime status
remote-dev-codex-runtime status --menu
remote-dev-codex-runtime resolve
remote-dev-codex-runtime remove
```

`resolve` is intended for the project launcher and prints the selected executable path. It performs local integrity checks only.

`remove` deletes only the optional Remote Dev-managed runtime state and returns immediately to the immutable bundled fallback. It never modifies `/usr/local/bin/codex` or `/root/.codex`.

## Persistent host layout

The canonical host data root adds one Codex-only directory:

```text
state/codex/runtime/
```

For the generic example, create it together with the other Codex state directories before running the preflight. For the TrueNAS example, the canonical host path is:

```text
/mnt/Pool1/remote-dev/state/codex/runtime
```

The host-side preflight rejects symlinks in this path. Container startup hardens the mounted runtime tree to private modes before it is used.
