# ttyd 1.7.7 OSC 52 compatibility asset

This directory produces the smallest supported browser-side addition needed
for native Codex `/copy`. The ttyd server remains the stable upstream 1.7.7
binary and serves `dist/index.html` through its public `--index` option.

`generate.py` downloads (or accepts with `--archive`) the exact upstream commit
archive, verifies the archive and `src/html.h`, extracts only the expected byte
array, decompresses and verifies the embedded HTML, then inserts the readable
`osc52-write.js` immediately before the single upstream bundle script. The
committed asset is verified byte-for-byte in CI; image builds only copy that
asset and never download or build frontend code.

Regenerate and check with:

```bash
python3 web/ttyd-osc52/generate.py
make ttyd-osc52-check
```

This compatibility layer is deliberately hard-bound to ttyd 1.7.7. A future
`TTYD_VERSION` change must fail closed and trigger issue #174. Do not port it by
updating hashes: first test whether the next stable ttyd release makes the
custom index unnecessary.

The handler accepts only OSC 52 writes for the empty selector observed through
tmux and selector `c`. It rejects reads and other selectors, validates canonical
base64 and fatal UTF-8 with a 100,000-byte raw limit, uses a temporary selected
textarea plus checked `document.execCommand('copy')`, and retains no text after
the attempt. It adds no UI, storage, telemetry, endpoint or clipboard-read path.
