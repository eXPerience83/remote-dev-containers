# Dual Python 3.14 / 3.15 runtime contract

Status: **PR #273 is merged into main and shipped in experimental edge**. Owning issue [#270](https://github.com/eXPerience83/remote-dev-containers/issues/270) is closed following exact-head CI and owner acceptance of its image-size exception. Universal CLI [PR2 #281](https://github.com/eXPerience83/remote-dev-containers/pull/281) is also merged and published in edge as of 2026-10-18, with its real TrueNAS operational acceptance still pending. Python upstream issue #257 was addressed by PR #271. This document describes implemented behavior, not proof of authenticated real-agent sessions.

## Supported versions and selection

The exact patches below describe reviewed PR #294 (2026-10-28). For a newer source revision, `versions.env`, `mise.toml` and `mise.lock` are authoritative; do not assume these examples stay current after future automated maintenance PRs.

- `PYTHON_VERSION=3.14.10` remains the image's default Python, both for unqualified `python`/`python3` in a neutral directory and for immutable administrative tooling. Maintenance updates stay within the reviewed 3.14.x line.
- `PYTHON_315_VERSION=3.15.2` is independently bundled; only a compatible project explicitly selecting the exact 3.15.x interpreter uses it. Maintenance updates stay within the reviewed 3.15.x line. The next minor line is never adopted silently.
- System `mise.toml` uses `python = ["3.14.10", "3.15.2"]` in that order. Project-owned `mise.toml` takes precedence; execution-capable project config remains subject to `mise trust`. Missing requested versions fail, without automatic downloads or fallback to the other Python.
- No startup flags, automatic venv activation, passive network fetches, mutation of `/opt/remote-dev/mise`, role sharing, Docker socket, or change to read-only root/`/tmp` noexec are introduced.

For a reviewed Python 3.15 project, use:

```toml
[tools]
python = "3.15.2"
```

After explicitly approving that project's configuration where trust is required, check `python --version`, `python3 --version`, and `mise which python`. To create an isolated project venv using the currently selected, **already installed** interpreter:

```bash
UV_PYTHON_DOWNLOADS=never uv venv --offline --python "$(mise which python)" .venv
.venv/bin/python -c 'import sys; print(sys.version)'
```

Do not imply `uv venv` activates a venv or installs packages into the image interpreter. Real project dependencies should follow the repository's own lock and package policy.

## Artifact provenance and maintenance

- Both Python versions are installed from reviewed `core:python` `mise.lock` entries with exact `linux-x64` and `linux-arm64` URLs, SHA-256 and attestation policy.
- A temporary **read-only** CI probe regenerated the two-runtime lock using the exact hash-verified `mise` binary; its output matched the candidate lock **byte-for-byte**. The temporary workflow was removed; this remains reproducible with `scripts/regenerate-mise-lock.sh`.
- Python 3.15's upstream license and independent full-distribution legal metadata are kept under `third_party/components/python-315/` and `third_party/components/python-build-standalone-315/`. The corresponding Python 3.14 legal evidence is preserved separately. Both are checked by the inventory/notice gates.
- `.github/workflows/check-upstream.yml` detects and preflights maintenance patches for 3.14 and 3.15 independently, using the fail-closed lockability rules from #257; one temporarily unavailable standalone artifact must not silently advance the affected line or block unrelated safe updates.

## October 2026 updater recovery (PRs #291–#294)

[PR #294](https://github.com/eXPerience83/remote-dev-containers/pull/294) updated the reviewed pins on `main` to Python 3.14.10 and 3.15.2 without changing the supported 3.14-default / explicit-3.15 selection contract. The [updater repairs #291](https://github.com/eXPerience83/remote-dev-containers/pull/291), [#292](https://github.com/eXPerience83/remote-dev-containers/pull/292) and [#293](https://github.com/eXPerience83/remote-dev-containers/pull/293) made this unattended *proposal* path work end to end:

- Regeneration first bootstraps the **exact reviewed Python 3.14 patch** through a validated, isolated mise lock/install. Native uv dependency graphs are then resolved with that interpreter available; inherited mise state or on-demand Python downloads are not trusted.
- A GitHub-release candidate for `ruff`, `pytest` or `pre-commit` is deferred **per tool** while any non-yanked PyPI distribution is less than 24 hours old, matching mise/uv's normal minimum-release-age protection. Other runtimes still advance. This is a routine safety policy, not proof a hotfix is safe; no automatic emergency bypass exists.
- The dual-Python updater regression derives fixture versions from the input it is actually validating (including an already-updated checkout). After the new `mise.lock` is generated, CLI wheel/license notices are regenerated **before** the strict pin and evidence checks.

See [dependency automation](dependency-automation.md) and [runtime lock maintenance](runtime-locks.md) for workflow and recovery details. CI validates AMD64 execution and the AMD64/ARM64 lock metadata; real ARM64 runtime support and live TrueNAS acceptance must not be inferred.

## Regression and acceptance gates

The CI `Build AMD64` workflow runs `scripts/build-local.sh` and the following guards:

| Contract | Required fixture/check |
| --- | --- |
| Both exact Python executables and 3.14 default | `scripts/smoke-test.sh` |
| 3.14/3.15 project selection in **both Codex and Antigravity roles** | `scripts/test-mise-project-resolution.sh` |
| Offline `uv` venvs for both interpreters, exact versions, distinct site-packages, no global version change | `scripts/test-mise-project-resolution.sh` (merged; PR CI passed) |
| Missing version, untrusted config, no fallback or implicit install, immutable tool store | `scripts/test-mise-project-resolution.sh` |
| State/mount/rootfs isolation, role credentials and launcher separation | `scripts/test-cross-service-isolation.sh` |
| Lock platform/backend/asset/provenance drift and safe regeneration | `scripts/test-validate-mise-lock.py`, `scripts/test-regenerate-mise-lock.sh` |
| Patch propagation delays and unexpected failures | `scripts/test_preflight_python_upstream.py` |
| Third-party notices and vulnerabilities | `scripts/validate-third-party-inventory.sh`, `remote-dev-notices --check`, SPDX SBOM, Trivy and no-fixable-CRITICAL gate |

CI proves AMD64 execution and complete AMD64/ARM64 lock **metadata**; it does **not** claim ARM64 runtime support (tracked separately by #112) or genuine authenticated vendor-agent sessions. Each newly published image still requires appropriate TrueNAS operational validation (agent browser sessions, histories, project selections and security boundaries); PR2 acceptance is tracked separately under #121.

## Size and release decision

The candidate with both versions has a measurable cost. At identical pinned component versions, the green `main` build at `b42f9c2` (run [38548947867](https://github.com/eXPerience83/remote-dev-containers/actions/runs/38548947867)) reports a final uncompressed image size of **1,547,987,128 bytes**. Candidate build at `bba44c0` (run [38633948930](https://github.com/eXPerience83/remote-dev-containers/actions/runs/38633948930)) reports **1,655,339,677 bytes**. Increment: **107,352,549 bytes / 102.38 MiB**. Base image grows by 107,351,674 bytes. This exceeds #121's 50 MiB **soft** review threshold: shipping an always-available second interpreter is an explicit functionality/size trade-off, not a free optimization. No exact compressed-pull delta is asserted.

## Decisions and remaining follow-up

- PR #273 has merged with exact-head CI validated and an explicit owner-accepted **+102.38 MiB** uncompressed image-size exception (2026-10-17). This is not a measured compressed-pull delta.
- PR2 #281 (six immutable validation CLIs) was merged and published in edge on 2026-10-18; live TrueNAS acceptance for that integrated image remains open under [#121](https://github.com/eXPerience83/remote-dev-containers/issues/121).
- PR3 agent-demand research and #180 persistent on-demand toolchains remain separate work. Neither should introduce extra startup parameters or passive downloads.
