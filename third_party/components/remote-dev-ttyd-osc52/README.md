# Remote Dev ttyd 1.7.7 OSC 52 client notices

`web/ttyd-osc52/dist/index.html` is derived from the exact frontend embedded in
ttyd 1.7.7 at commit `40e79c706be14029b391f369bee6613c31667abb` and adds only
the Remote Dev write-only OSC 52 compatibility script. The ttyd license is
preserved separately at `third_party/components/ttyd/LICENSE`.

The subdirectories here preserve the license text from each exact npm package
represented in the upstream embedded bundle. `trzsz 1.1.5` carries prebundled
`base64-js 1.5.1`, `pako 2.1.0`, `ts-md5 1.3.1` and `tslib 2.6.2` in
`lib/trzsz.js`; Pako's `lib/zlib` code is recorded with its Zlib notice in
addition to Pako's MIT notice. `zmodem.js 0.1.10` is modified by ttyd's exact,
hash-bound Yarn patch,
preserved at `zmodem.js/ttyd-1.7.7.patch`.

Exact names, versions, package provenance, package and notice hashes are
recorded in `web/ttyd-osc52/bundle-components.json`; provenance also binds the
zmodem patch to the exact ttyd commit. The dedicated SPDX document records the
same distribution closure. Webpack roots alone are not treated as the complete
redistributed-code inventory.

This evidence triggers the out-of-cycle review in issue #53. Automated checks
verify consistency and do not constitute human legal or supply-chain approval.
