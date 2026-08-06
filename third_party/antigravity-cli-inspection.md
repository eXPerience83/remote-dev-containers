# Antigravity CLI installer and package inspection

## Status

Inspection date: **2026-08-05 UTC**

This report records bounded metadata from the installer and package that Google served on the inspection date. It does not contain or redistribute the installer or the Antigravity CLI binary.

The reproducible workflow is `.github/workflows/inspect-antigravity-cli.yml`. The normalized machine-readable evidence is `third_party/antigravity-cli-inspection.json`.

## Role of this evidence

The exact hashes below identify the most recently human-reviewed Antigravity installer and payload. They are a compatibility and review snapshot, not a routine runtime availability allowlist.

Remote Dev does not redistribute Antigravity. An explicit user-requested install or update may obtain the version currently served by the same fixed official Google endpoint even when its hash is newer than this report, provided the existing hardened manager can still validate the live origin, bounded installer contract, package location, Linux AMD64 executable and version/help behavior.

Such an installation is recorded locally as **official, review pending**. It may run while its private local integrity manifest remains valid. It must not be described as having completed Remote Dev's human review until this evidence is refreshed through a reviewed pull request.

A Docker image update does not invalidate an intact earlier installation merely because the reviewed snapshot changed. Conversely, publishing another image is not required for ordinary vendor version/hash churn. A new image remains necessary when the installer or executable contract changes beyond what the existing manager can safely validate.

Absence from this review snapshot is not a revocation. Any future revocation must identify a specific unsafe version or hash and be explicit, documented and tested.

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
4. verifies the committed reviewed installer hash before executing Bash;
5. verifies that it is valid Bash and reads its live `--help` output;
6. uses only a currently advertised option to install under the isolated home;
7. fingerprints shell profiles before and after installation;
8. records file paths, modes, sizes and SHA-256 values without retaining file contents;
9. verifies the committed reviewed payload hash before invoking the executable;
10. runs `agy --version` and `agy --help` without authenticating;
11. repeats the installer to observe its update/idempotency behavior;
12. uploads only a bounded JSON metadata artifact.

The dedicated review workflow deliberately remains stricter than the user-requested runtime installation path: changed bytes fail the committed-evidence comparison and require human review. That failure must not disable a separate locally intact installation.

The job does not start an authenticated Antigravity session, does not provide a Google account and does not upload the installer or installed executable.

## Exact inspected installer

| Field | Value |
|---|---|
| URL | `https://antigravity.google/cli/install.sh` |
| Content type | `application/x-sh` |
| Size | `7,354` bytes |
| SHA-256 | `ee1ea43ce4e9e56356c4ab6dad907ef357ae4bdfcaadb682735909fb57c9c640` |
| Embedded release service host | `antigravity-cli-auto-updater-974169037036.us-central1.run.app` |

The live installer help advertised only:

```text
-d, --dir <path>    Specify a custom directory to install the binary
-h, --help          Display this help menu
```

Older official documentation described `--skip-aliases` and `--skip-path`, but the inspected installer rejected those options. Remote Dev therefore validates the live minimum contract and uses an explicit private `--dir` target. It does not assume the older flags are present.

## Installed package

The installer detected `linux_amd64`, reported that it verified the downloaded package checksum and placed the executable at the requested path.

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

## Runtime installation and local integrity

The runtime manager never pipes the installer into Bash. After explicit consent it:

1. downloads from the fixed official endpoint into a private bounded file;
2. verifies the effective origin and response metadata;
3. checks the shell syntax and live `--dir <path>` contract in a credential-free home;
4. installs into an Antigravity-owned staging directory;
5. checks that the candidate is a bounded executable Linux AMD64 ELF;
6. runs bounded `--version` and `--help` checks with automatic update disabled;
7. writes a private local manifest containing source, version, sizes and hashes;
8. publishes the executable and manifest only after validation;
9. preserves the prior valid executable and manifest for rollback during an update.

Later launches do not contact the installer endpoint. They verify that the local executable still matches its manifest before execution. A missing, malformed or mismatched manifest/executable is blocked and requires an explicit update or repair.

The local manifest is an integrity record for the single-user container threat model; it is not a signature from Google and does not replace this repository's human review evidence.

## Update behavior

Running the inspected installer a second time returned success but did not replace the existing executable. Its SHA-256 remained unchanged. The installer stated that regular CLI runs self-update in the background and that a fresh installation requires deleting the existing binary first.

Google's troubleshooting documentation provides the opt-out:

```text
AGY_CLI_DISABLE_AUTO_UPDATE=true
```

It also documents updater state under:

```text
~/.gemini/antigravity-cli/updater/
```

Remote Dev sets the opt-out during candidate validation and every normal agent session. Updating is a separate explicit manager action that stages and validates the current official package before replacing the active copy. A failed update leaves the previous installation usable.

## Runtime staging boundary

Remote Dev performs explicit installation and update inside a uniquely named directory below the validated Antigravity-owned runtime state directory. The canonical manager selects this location itself and does not honor a caller-supplied `TMPDIR`, so menu, shell and automation invocations avoid a non-executable system `/tmp` mount without weakening that mount's security options.

Temporary installer, isolated home and candidate payload data are removed when the operation exits. One validated previous executable and manifest may remain in the private rollback directory.

## Persistent state and credentials

Official documentation places persistent CLI settings at:

```text
~/.gemini/antigravity-cli/settings.json
```

Authentication uses the official client and Google Sign-In, including a remote/SSH authorization URL flow. Credentials, histories, settings, updater files and optional plugins remain inside the Antigravity service's private state mounts. Remote Dev does not inspect, print, transform, share or reuse those credentials.

Real authentication and exact post-login state paths remain manual TrueNAS validation items; CI deliberately performs no account login.

## Distribution decision

The installer is public, but no reviewed evidence grants this project permission to redistribute the proprietary executable. Therefore:

- the public Remote Dev image does not contain the installer or Antigravity binary;
- installation and update are explicit and initiated by the user;
- the wrapper downloads only from the fixed official Google endpoint into a temporary file;
- the binary is installed into Antigravity-owned persistent storage;
- Google terms, privacy disclosures, data-use behavior and the non-affiliation notice are shown before installation/update;
- review automation retains metadata only and never uploads or republishes the proprietary bytes.

## Re-review triggers

Repeat or refresh this inspection whenever any of these changes:

- installer SHA-256, size, content type or advertised options;
- installer endpoint or release-service host;
- executable version, hash, location, format or packaging;
- automatic-update controls;
- state, credential or cache paths;
- vendor terms, privacy disclosures or data-use behavior;
- supported architectures.

A changed reviewed snapshot should open or refresh a human-reviewed pull request. It should not silently merge, publish stable tags or disable an intact local installation.
