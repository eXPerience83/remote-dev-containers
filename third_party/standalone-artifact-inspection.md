# Standalone artifact inspection

This is a bounded inspection of the exact AMD64 and ARM64 release assets pinned by the repository. It records whether the distributed archive itself contains license-like files; repository-preserved notices remain the authoritative documents shipped in the image.

| Component | Version | Packaging | Legal files inside asset | Repository notices |
|---|---:|---|---|---|
| github-cli | `2.103.3` | tar.gz | LICENSE | LICENSE |
| codex-cli | `rust-v0.166.0` | tar.gz | None | LICENSE, NOTICE |
| codex-code-mode-host | `rust-v0.166.0` | tar.gz | None | LICENSE, NOTICE |
| ttyd | `1.7.7` | raw-binary | None | LICENSE |
| mise | `2026.10.25` | raw-binary | None | LICENSE |
| uv | `0.13.6` | tar.gz | None | LICENSE-APACHE-2.0, LICENSE-MIT |
| yq | `4.54.1` | raw-binary | None | LICENSE |
| shfmt | `3.14.1` | raw-binary | None | LICENSE |
| actionlint | `1.7.12` | tar.gz | LICENSE.txt | LICENSE.txt |

## Interpretation

- A raw executable cannot carry a separate license file as an archive member, so its exact repository license is preserved alongside the image.
- An archive with no license-like member likewise relies on the exact version-specific repository notice recorded in `third_party/inventory.json`.
- When an archive includes a legal file, the JSON report records its content hash and whether it exactly matches a preserved repository notice.
- The report is inspection evidence for the pinned versions, not a general binary or dependency-license scanner.
