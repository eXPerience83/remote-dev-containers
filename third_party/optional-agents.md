# Optional vendor agents

Antigravity CLI, Claude Code and similar vendor agents are not bundled or redistributed by Remote Dev images and are not covered by the repository's Apache-2.0 license. Where an optional integration exists, the vendor package is obtained only after an explicit user action from the vendor-controlled source.

Optional-agent integrations must satisfy all of these conditions:

1. Installation/update is an explicit user action.
2. The package is downloaded directly from a vendor-controlled source.
3. Redistribution rights are verified before any binary is ever added to a public image; public availability alone is not permission to redistribute.
4. The user is shown that separate vendor terms, privacy policies and account requirements apply.
5. Remote Dev does not claim vendor affiliation, endorsement or vendor-specific legal approval.
6. Credentials and OAuth state remain inside that agent service's private storage.
7. Diagnostics do not read, print, export, transform or reuse secret contents.
8. The official client is used rather than an unofficial service client or an OAuth relay into another agent harness.
9. Owned files, update behavior and uninstall/recovery behavior are documented before support is claimed.
10. Review is repeated when material installer/package, terms, privacy, authentication, state-path or supported-platform behavior changes.

## Antigravity support boundary

Antigravity is supported as an **experimental launcher/wrapper around Google's official `agy` CLI**. It is not bundled in the image. Remote Dev does not act as an alternate Antigravity client and does not reuse Antigravity OAuth tokens outside the official CLI.

The current project policy was reconciled in #53 and #96 on 2026-09-03: current Google documentation explicitly supports the official CLI in remote terminals/SSH and headless/CI workflows, which materially supports this architecture, while Google's broad service terms still leave some residual interpretation risk. The project therefore keeps the integration experimental, non-affiliated and subject to Google's current terms/privacy policy. This is a project support decision, not a claim that Google has specifically endorsed Remote Dev or provided legal approval.

The technical runtime/admission implementation is complete under #96/#153 and has been validated on TrueNAS with real official-source Antigravity versions. Its standing rules include:

- user-initiated download from the fixed official Google HTTPS installer origin;
- installer and proprietary `agy` bytes remain outside the repository and public image;
- download to private temporary state rather than piping remote bytes into a shell;
- bounded installer-contract and payload-integrity validation before publication to Antigravity-owned persistent state;
- private Antigravity settings/config/history/plugin/updater/credential state isolated from Codex;
- normal launch sets `AGY_CLI_DISABLE_AUTO_UPDATE=true`;
- an intact locally admitted installation can remain usable while repository review evidence is pending;
- real launch retains the mandatory full-integrity gate from #153;
- absence from committed review evidence is not automatic revocation.

## Antigravity committed review evidence

The normalized machine-readable review is:

- `third_party/antigravity-cli-inspection.json` — latest fully reviewed installer/payload identity;
- `third_party/antigravity-cli-detection.json` — latest scheduled metadata-only installer detection state;
- `third_party/antigravity-cli-inspection.md` — current generated safe summary plus historical inspection/runtime notes.

`.github/workflows/check-upstream.yml` performs the scheduled detection daily at 05:17 UTC and can also be dispatched manually. The detector has read-only repository permission, does not retain GitHub checkout credentials and **does not execute a changed installer merely because it changed**. It records only bounded normalized metadata.

A changed installer enters a two-stage explicit admission flow in `.github/workflows/review-antigravity-candidate.yml`:

1. a human explicitly supplies the detected installer SHA-256; only that admitted installer may run in an ephemeral credential-free environment to discover the resulting `agy` SHA-256, and `agy` is not executed;
2. a human separately supplies both the admitted installer SHA-256 and discovered payload SHA-256; only then may the bounded full inspection execute `agy --version`/`--help` and generate proposed reviewed metadata.

The vendor-byte job has no repository write permission. Only schema-validated metadata crosses to the writer job, and the same artifact is validated again after crossing that boundary. Raw vendor stdout/stderr, installer bytes and `agy` bytes are never committed or uploaded as review artifacts. The resulting changes share the single `automation/update-upstreams` human-reviewed PR; there is no auto-merge and review status does not gate runtime availability.

The original detailed 2026-08-05 baseline and later TrueNAS observations are preserved in `third_party/antigravity-cli-inspection.md`. The machine-owned summary at the top of that document, not the historical baseline section, is the canonical current committed reviewed identity.

## Current support status

- **Antigravity CLI:** experimental official-CLI wrapper/launcher support. Explicit vendor download only; not bundled or redistributed. Current technical admission/integrity behavior is shipped, with scheduled review automation maintaining advisory evidence rather than runtime availability.
- **Claude Code:** future compatibility path only; not bundled, installed or advertised as supported.

A public download URL or public source repository is not, by itself, evidence that redistribution is permitted.
