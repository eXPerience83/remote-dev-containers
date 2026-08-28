# Remote Dev ttyd client

This directory builds the exact ttyd 1.7.7 frontend source at commit
`40e79c706be14029b391f369bee6613c31667abb`, plus the bounded patch in
`patches/`. The standalone ttyd server remains the unmodified 1.7.7 release.

The build uses the upstream Yarn 3.6.3 lock and fixed zmodem patch because an
npm translation did not preserve that resolution without a second bespoke
mapping. The Yarn executable is an exact, hash-verified build-only input. The
runtime image receives only `dist/index.html` and legal metadata.

Run `./web/ttyd-client/build.sh` to verify every vendored source input, apply
the patch with zero fuzz, perform two clean builds, compare them byte for byte,
and compare the result to the committed asset manifest.

The extension registry is intentionally empty. Issue #91 owns clipboard and
selection behavior; #90 owns touch controls. Neither is implemented here.
