# Antigravity CLI installer and package inspection

## Status

<!-- remote-dev-antigravity-current-review:start -->

Current committed normalized review evidence:

- inspection date: **2026-09-04 UTC**;
- official installer: `https://antigravity.google/cli/install.sh`;
- installer SHA-256: `ee1ea43ce4e9e56356c4ab6dad907ef357ae4bdfcaadb682735909fb57c9c640` (7,354 bytes);
- selected installer strategy: `custom-directory`;
- referenced HTTPS hosts: `antigravity-cli-auto-updater-974169037036.us-central1.run.app`;
- installed payload: `agy` **1.1.26**, SHA-256 `a0a6a8044d01accd39e6f5926d29648d212a2e519ff14102f09e1c061e6171dd` (210,247,936 bytes);
- blocking findings: **none**.

This summary is generated only from schema-validated metadata. It never embeds vendor stdout/stderr or proprietary bytes.

<!-- remote-dev-antigravity-current-review:end -->

The detailed sections below preserve the original 2026-08-05 baseline inspection and later runtime-validation notes. The machine-owned summary above is the canonical current committed artifact identity after later automated review PRs.

This report records bounded metadata from the installer and package served by Google during the historical baseline inspection. It does not contain or redistribute the installer or the Antigravity CLI binary.

The reproducible workflow is `.github/workflows/inspect-antigravity-cli.yml`. The normalized machine-readable evidence is `third_party/antigravity-cli-inspection.json`.

## Official sources reviewed

- Product repository: <https://github.com/google-antigravity/antigravity-cli>
- Installer: <https://antigravity.google/cli/install.sh>
- CLI overview: <https://antigravity.google/docs/cli-overview>
- CLI installation: <https://antigravity.google/docs/cli-installation>
- CLI settings: <https://antigravity.google/docs/cli-settings>
- CLI troubleshooting: <https://antigravity.google/docs/cli-troubleshooting>
- Terms: <https://antigravity.google/terms>
- Google Privacy Policy: <https://policies.google.com/privacy>

## Inspection method

The dedicated GitHub Actions job:

1. checks out the repository without persisting GitHub credentials;
2. creates a new temporary home directory;
3. downloads the installer from the fixed official HTTPS URL to a temporary file;
4. verifies that it is valid Bash and reads its live `--help` output;
5. uses only a currently advertised option to install under the isolated home;
6. fingerprints shell profiles before and after installation;
7. records file paths, modes, sizes and SHA-256 values without retaining file contents;
8. runs `agy --version` and `agy --help` without authenticating;
9. repeats the installer to observe its update/idempotency behavior;
10. uploads only a bounded JSON metadata artifact.

The job does not start an authenticated Antigravity session, does not provide a Google account and does not upload the installer or installed executable.

## Historical baseline: exact installer inspected on 2026-08-05

| Field | Value |
|---|---|
| URL | `https://antigravity.google/cli/install.sh` |
| Content type | `application/x-sh` |
| Size | `7,354` bytes |
| SHA-256 | `ee1ea43ce4e9e56356c4ab6dad907ef357ae4bdfcaadb682735909fb57c9c640` |
| Embedded release service host | `antigravity-cli-auto-updater-974169037036.us-central1.run.app` |

The live installer help at that baseline advertised only:

```text
-d, --dir <path>    Specify a custom directory to install the binary
-h, --help          Display this help menu
```

Older official documentation described `--skip-aliases` and `--skip-path`, but the inspected installer rejected those options. Remote Dev must therefore query and validate the live installer contract and currently use an explicit private `--dir` target. It must not assume the older flags are present.

## Historical baseline: installed package

The baseline installer detected `linux_amd64`, reported that it verified the downloaded package checksum and placed the executable at the requested path.

| Field | Value |
|---|---|
| Relative path | `.local/bin/agy` |
| Reported version | `1.1.10` |
| Size | `193,835,456` bytes |
| SHA-256 | `4217db798fd514cedce4e315013daea471a1a67666ab91547b2ad0dbee167a71` |
| Format | ELF 64-bit x86-64 PIE, dynamically linked, stripped |
| Interpreter | `/lib64/ld-linux-x86-64.so.2` |

Observed dynamic libraries were `libc`, `libdl`, `libm`, `libpthread`, `libresolv` and `librt` from the runner operating system. The inspection reported no unrecognized dynamic libraries and no blocking findings.

The package created only these relevant paths under the isolated home:

```text
.cache/antigravity/
.cache/antigravity/staging/
.local/bin/agy
```

No shell profile was created or modified. No separate `LICENSE`, `NOTICE`, `COPYING`, `COPYRIGHT` or `AUTHORS` file was installed alongside the binary.

Absence of an installed legal file is **not** evidence of redistribution permission.

## Update behavior

Running the baseline installer a second time returned success but did not replace the existing executable. Its SHA-256 remained unchanged. The installer stated that:

- Antigravity CLI automatically self-updates in the background during regular runs;
- a fresh installation requires deleting the existing binary first.

Google's troubleshooting documentation provides the opt-out:

```text
AGY_CLI_DISABLE_AUTO_UPDATE=true
```

It also documents updater state under:

```text
~/.gemini/antigravity-cli/updater/
```

A Remote Dev integration must set the opt-out for normal agent sessions so that starting Antigravity never mutates the executable silently. Updating must be a separate explicit action that uses an upstream-supported command or reviewed installation flow and reports the before/after versions.

## Runtime staging boundary

Remote Dev performs the explicit installer run inside a uniquely named directory below the validated Antigravity-owned runtime state directory. The canonical manager selects this location itself and does not honor a caller-supplied `TMPDIR`, so menu, shell and automation invocations all avoid a non-executable system `/tmp` mount without weakening that mount's security options. Temporary installer, isolated home and candidate payload data are removed when the operation exits.

## Persistent state and credentials

Official documentation places persistent CLI settings at:

```text
~/.gemini/antigravity-cli/settings.json
```

### Project configuration path follow-up (2026-08-24)

The [official public Antigravity CLI changelog for version
1.0.12](https://github.com/google-antigravity/antigravity-cli/blob/ee5766c17fce8f27ea85185f97183575058218ec/CHANGELOG.md#1012)
identifies project-specific configuration below:

```text
~/.gemini/config/projects/
```

Historical exact-candidate TrueNAS validation of
`030396a581187c44c847cbe4b50d71e50d8f9ba6` observed an explicitly admitted
Antigravity 1.1.19 session attempt to create `/root/.gemini/config/projects`;
it failed because the hardened container root was read-only and no narrow
writable mount covered that path. The subsequent PR fix adds the dedicated
Antigravity-private `state/antigravity/config` mount at
`/root/.gemini/config`, separate from `/root/.gemini/antigravity-cli` and
without making all of `/root/.gemini` writable. Exact-candidate TrueNAS
validation completed on 2026-08-25 for source revision
`15df3c3851ffabdc568ce8d2724424a4577f313a` and immutable image digest
`sha256:f22727a9976f4dfde90d3e40d5d333eaf0e7727f860312bf5adaef73678f118e`.
It confirmed the dedicated bind is writable, `/root/.gemini/config/projects`
can be created while the container root remains read-only, and a real
Antigravity 1.1.19 conversation can start and later continue successfully.

This path-topology follow-up is not a completed installer or binary review of
1.1.19 and does not change its truthful `official source; Remote Dev review
pending` status. The exact artifact evidence and inspection date above remain
the reviewed evidence for the version recorded there.

Authentication uses the official client and Google Sign-In, including a remote/SSH authorization URL flow. Credentials, histories, settings, updater files and optional plugins must remain inside the Antigravity service's private state mounts. Remote Dev must not inspect, print, transform, share or reuse those credentials.

Other real authentication and post-login state paths remain manual TrueNAS
validation items; CI deliberately performs no account login.

## Distribution decision

The installer is public, but no reviewed evidence grants this project permission to redistribute the proprietary executable. Therefore:

- the public Remote Dev image must not contain the installer or Antigravity binary;
- installation must be explicit and initiated by the user;
- the wrapper must download from the fixed official Google endpoint into a temporary file rather than piping remote content into a shell;
- the binary must be installed into Antigravity-owned persistent storage;
- Google terms, privacy disclosures, data-use behavior and the non-affiliation notice must be shown before installation;
- the integration must fail closed if installer options, destination paths or post-install checks differ from this reviewed contract.

## Re-review triggers

Repeat this inspection before support is claimed whenever any of these changes:

- installer SHA-256 or advertised options;
- installer endpoint or release-service host;
- executable location or packaging;
- automatic-update controls;
- state, credential or cache paths;
- vendor terms, privacy disclosures or data-use behavior;
- supported architectures.
