# Dependency automation ownership

Each versioned input has one automation owner. Human review remains the approval layer and automation never merges dependency changes automatically.

Renovate owns only pinned GitHub Actions, the pinned `docker/dockerfile` frontend, and the Ubuntu LTS version/digest pair. Native Dockerfile dependencies are denied by default and only the frontend is explicitly allowed. Ubuntu is updated exclusively by the bounded custom regex managers so `versions.env`, `images/base/Dockerfile`, and the Renovate-owned Ubuntu changelog state remain synchronized. Future `FROM`, `COPY --from`, `RUN --mount`, or other native Dockerfile image references remain unowned until this contract is explicitly reviewed.

Renovate runtime/image provenance is intentionally separate from grouped upstream-tool provenance. `CHANGELOG.md` contains a dedicated `### Renovate image refreshes` subsection inside `Unreleased`, bounded by `remote-dev-renovate-runtime-refreshes` start/end markers. Only the Ubuntu changelog custom manager may write inside that boundary. Its hidden state anchor stores the exact currently committed Ubuntu version and OCI digest and must match the same pair in `versions.env` and `images/base/Dockerfile`. When Renovate proposes a newer Ubuntu tag or digest, `autoReplaceStringTemplate` inserts the exact old-to-new version/digest delta immediately before the state anchor and advances the anchor to the proposed pair. Regenerating the same Renovate PR from the same base reproduces the same text instead of duplicating it; after a reviewed update is merged, a later Ubuntu update appends a new machine-owned delta without overwriting earlier entries or human-authored changelog text.

Pinned GitHub Action updates and the pinned `docker/dockerfile` frontend remain build/CI maintenance. They do not target the Renovate changelog manager and therefore are not presented as bundled runtime application upgrades. This provenance design uses only Renovate's declarative regex/custom-manager replacement contract: there is no repository write workflow, `pull_request_target`, `postUpgradeTasks`, or privileged changelog script. The existing `Ubuntu LTS base` package rule groups the runtime pins and changelog state into the same human-reviewed Renovate PR, while `automerge: false` remains mandatory.

The scheduled `check-upstream.yml` workflow separately owns bundled runtime and tool pins, architecture hashes, mise configuration and lock data, notices, inventory, standalone-artifact evidence, the reviewed transient Context7 CLI pin, and metadata-only Antigravity review detection/discovery. Its `### Automated upstream refreshes` changelog section is distinct from the Renovate image section. Native mise management remains disabled because those files must change as one validated set. Optional runtime availability and project image release references remain outside Renovate ownership.

Context7 is not installed into an image by this automation. The updater reads only bounded metadata for the exact `ctx7` package from the fixed public npm registry, requires the reviewed MIT license, exact stable version, exact tarball URL and SHA-512 integrity, then proposes the version/integrity change in the same human-reviewed automation PR. The runtime helper, `versions.env` and the reviewed-version regression assertions change atomically. The transient package is still downloaded only during an explicit Context7 device-login action and therefore remains outside the image inventory and build-time SBOM.

Antigravity uses a separate review boundary because its official installer and payload are proprietary vendor bytes. The scheduled read-only job downloads bounded bytes from the exact installer URL, fixed Linux AMD64 manifest endpoint and reviewed Google Storage payload path using strict URL/redirect policies with ambient proxies disabled. It validates installer hash/static contract markers, manifest schema and archive SHA-512, then streams the single `antigravity` archive member to calculate its SHA-256. Neither installer nor payload is executed or extracted during scheduled discovery, and proprietary bytes are never retained as artifacts or committed.

The scheduler can therefore identify both the current installer SHA-256 and current `agy` SHA-256 without a preliminary human execution admission. If either differs from committed reviewed evidence, the same `automation/update-upstreams` PR records the statically discovered pair. A maintainer then manually dispatches `.github/workflows/review-antigravity-candidate.yml` from trusted `main`; the workflow has no hash input fields and resolves the exact pending installer/payload pair from validated automation-branch metadata. The read-only execution job prefetches the installer through the strict downloader, rejects a hash mismatch before Bash execution, runs only the admitted installer in an isolated temporary home, verifies the installed `agy` hash before invoking it, and only then performs bounded `agy --version`/`--help` and compatibility inspection. A separate writer job consumes only revalidated normalized metadata.

All grouped upstream maintenance shares the single `automation/update-upstreams` branch/PR and the `check-upstream` concurrency group. A scheduled rerun regenerates the branch from current `main` while preserving only schema-valid Antigravity discovery/full-review metadata that still matches the current statically discovered installer/payload pair. Fresh discovery invalidates stale review state. Candidate state is staged before the no-change decision so a newly created untracked candidate cannot be lost. Neither pending Context7 review nor pending/failed Antigravity review revokes or disables an intact runtime admitted under its separate runtime contract.

`scripts/validate-renovate-ownership.py` enforces the Renovate boundary offline. It requires the exact two approved Ubuntu custom managers, synchronizes the changelog state anchor with both runtime pin locations, verifies that the anchor remains inside its machine-owned `Unreleased` boundary, and keeps the existing native-Dockerfile/default-deny and no-automerge guarantees. Regression tests cover a runtime-affecting Ubuntu digest update, deterministic refresh/append behavior, and a GitHub Action SHA-only change that must leave runtime changelog provenance untouched. Adding another manager or transferring a dependency requires a focused review of this contract.

## Periodic published-image vulnerability monitoring

`.github/workflows/rescan-published-images.yml` is a separate **read/scan/alert** maintenance boundary. It does not own versions, rebuild images or publish packages.

Once per week, and on explicit manual dispatch from trusted `main`, the scan job:

1. pulls only the public `edge-amd64` tags for `remote-dev-base` and `remote-dev`;
2. resolves each mutable tag to exactly one canonical `name@sha256:<digest>` reference and rejects missing/ambiguous/noncanonical results;
3. scans only those immutable digest references with Trivy using a fresh runner and with restored Trivy DB caching disabled;
4. retains CRITICAL JSON reports plus `trivy --version` scanner/database metadata for 30 days;
5. renders a bounded deterministic state/body offline;
6. applies the same `scripts/enforce-trivy-gate.sh` policy used by normal image workflows: only `CRITICAL` findings with a known `FixedVersion` are actionable/failing, while unfixed critical findings remain visible evidence.

The scan job has only `contents: read` and `packages: read`. A separate writer job has only `contents: read` and `issues: write`; it cannot read/write packages. Before using its write permission, the writer downloads the scan artifact, re-runs the repository renderer from trusted `main` against the raw reports and exact refs, and requires byte-for-byte equality with the transferred state/body.

At most one managed issue uses the exact title `[security] published image vulnerability alert` plus the hidden `remote-dev-periodic-rescan-alert` marker. An actionable scan creates, updates or reopens that issue. The first later clean scan records the clean exact-digest result and closes it. A clean scan with no open managed alert is a no-op. If an exact-title issue is not marked as automation-owned, or multiple managed candidates exist, the workflow fails closed instead of overwriting ambiguous human content.

A registry-resolution, Trivy setup/database, scan, report-parse, render or writer-revalidation failure fails visibly and cannot close an existing alert. Reports must contain the reviewed Trivy schema and a present `Results` list; incomplete JSON is never interpreted as a clean result.

### Actionable-finding runbook

When the managed alert opens or reopens:

1. use the alert's workflow link and artifact to identify the exact affected `name@sha256:<digest>` and CVE/package pair;
2. confirm the Trivy `FixedVersion` and follow the included `PrimaryURL`/reference when available; never infer a fix solely from a mutable tag;
3. determine whether remediation is an Ubuntu/APT refresh, a tracked bundled dependency update or another image-input change;
4. apply the fix through the normal reviewed source/update path. For moving Ubuntu package revisions without a source-pin change, #93 owns the controlled rebuild-and-edge-promotion path;
5. do not manually retag, overwrite or promote an unscanned digest to silence the alert;
6. after a reviewed image has been published, run or wait for a new periodic rescan and verify that it resolves/scans the new exact digest;
7. let only a successful clean rescan update and close the managed alert. A failed scan is not evidence of remediation.

For an unfixed `CRITICAL`, keep the report as evidence and review upstream status, but do not change the repository's gate semantics ad hoc. If project policy changes, update the shared Trivy gate and this monitoring workflow together in a focused review.

This monitoring workflow contains no package-write permission, `docker push`, build/promotion path or `stable`/`latest` mutation. Stable images are intentionally absent until a first stable release exists; adding stable rescans later must resolve immutable stable digests without weakening versioned-tag immutability. #93 separately owns any future scheduled **rebuild and edge promotion** needed to pick up moving Ubuntu APT security revisions; #20 monitoring must not silently grow into that higher-privilege responsibility.

## Controlled edge security rebuilds

`.github/workflows/publish-edge-amd64.yml` is also the single publication implementation for the controlled #93 rebuild cadence. There is no second scheduler with copied registry/tag logic. Besides reviewed `main` pushes and explicit manual dispatch, the same publisher runs every Sunday at **01:11 UTC**, leaving substantial separation from the daily 05:17 upstream-review schedule and the Monday 04:23 published-image rescan.

A scheduled rebuild intentionally re-evaluates moving package repositories used by the Dockerfiles. In particular, the Ubuntu image is pinned by immutable base digest, but `apt` installs the current package revisions available from that pinned Ubuntu release's configured repositories at build time. Therefore the repository source SHA and version pins may stay unchanged while the resulting Remote Dev image digest changes because newer Ubuntu security package revisions were resolved. The dated `edge-YYYY.MM.DD-<short-sha>` label records the rebuild date while the full source SHA still identifies the exact repository source used.

The publisher's trust order is deliberately stricter than “build then tag”:

1. validate trusted `main` repository configuration;
2. build/push the untagged AMD64 base candidate by digest;
3. build/push the untagged AMD64 Remote Dev candidate from that exact base digest;
4. pull those exact immutable candidates and verify source-revision/version/channel labels;
5. run bundled-notice checks and the exact runtime candidate smoke, Context7 isolation, `noexec` staging, browser-agent authentication and cross-service isolation suites;
6. generate explicit SPDX JSON SBOMs from the exact candidate digests;
7. run Trivy CRITICAL scans on the same exact candidate digests;
8. apply the shared no-fixable-critical gate;
9. only then promote those validated digests to the mutable `edge`/`edge-amd64` and commit-addressed edge tags and verify the promoted tags resolve back to the candidate digests.

The workflow default permission is `contents: read`; only the trusted `publish-edge` job receives `packages: write`. It has no pull-request trigger. A failure during build, candidate smoke, notice validation, SBOM/Trivy generation, vulnerability gate, registry operation or digest verification prevents the promotion step, so the previously promoted mutable edge tags remain unchanged. Runtime-installed Antigravity bytes remain outside the image and are not redistributed by a rebuild.

### Scheduled rebuild investigation and rollback

For a failed scheduled rebuild, inspect the workflow step and retained `edge-publication-reports` artifact before changing anything. A failed candidate has no mutable edge tag, so do not “repair” the failure by manually tagging its digest. Fix the source/package/repository cause through the normal reviewed path and run the publisher again.

For a successfully promoted rebuild that later shows a runtime regression, use the previously recorded immutable `ghcr.io/experience83/remote-dev@sha256:<digest>` as the rollback identity while investigating. Do not infer rollback identity from a mutable `edge` tag after it has moved. Restore the known-good digest in the deployment, confirm its embedded source revision/channel/version with `remote-dev-version`, and keep the newer digest available for diagnosis. Any later promotion must again pass the complete exact-candidate gate above.

Scheduled rebuilds never create or move `stable`, `latest` or versioned stable tags. A first stable release remains an explicit separate release action with its own immutable candidate/review boundary.
