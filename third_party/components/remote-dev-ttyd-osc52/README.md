# Remote Dev ttyd 1.7.7 OSC 52 client notices

`web/ttyd-osc52/dist/index.html` is derived from the exact frontend embedded in
ttyd 1.7.7 at commit `40e79c706be14029b391f369bee6613c31667abb` and adds only
the Remote Dev write-only OSC 52 compatibility script. The ttyd license is
preserved separately at `third_party/components/ttyd/LICENSE`.

The subdirectories here preserve the license text from each exact npm package
represented in the upstream embedded bundle. Exact names, versions, license
identifiers and file hashes are recorded in
`web/ttyd-osc52/bundle-components.json`; the dedicated SPDX document records
the same distribution closure.

This evidence triggers the out-of-cycle review in issue #53. Automated checks
verify consistency and do not constitute human legal or supply-chain approval.
