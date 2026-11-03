# WeTTY v4.2.1 — Gate 0 build/PTY research spike

**Research only, tracked by #247.** The shipped backend remains ttyd 1.7.7; this change does not affect image contents, runtime entrypoints, Compose, environment variables or production credentials.

## Verified upstream baseline (2026-11-03)

- GitHub latest stable: [WeTTY v4.2.1](https://github.com/butlerx/wetty/releases/tag/v4.2.1), released 2026-10-25; exact tag commit `116189487c52759afec2b40ff293631f64e1fb6e`.
- Upstream Node engines: `^22.23.4 || ^24.22.1 || >=26.12.1`; Remote Dev already pins Node 24.22.2.
- Frozen source `pnpm-lock.yaml` resolves `@xterm/xterm 6.0.0`, `node-pty 1.1.0`, `socket.io 4.8.4`, `express 5.3.0`. Source declares pnpm 9.4.0.
- **Provenance caveat:** GitHub tag's `package.json` still declares 3.0.0 even though npm/GitHub publish 4.2.1. Do not equate source version with registry tarball integrity; research packaging separately.

## v4.2.1 source audit versus v3.3.5

| Topic | Current observation | Status |
| --- | --- | --- |
| Browser lifecycle | `term/session.ts` releases terminal, socket and event listeners on disconnect | Improved; repeated-reconnect test pending |
| Server/PTy cleanup | `server/session.ts`, `server/spawn/index.ts` own and release PTY/session resources | Improved; persistent tmux survival untested |
| Editor message channel | `term/configuration.ts` validates source and origin | Improved; omit editor from first minimal client |
| Socket Origin | `socketServer/socket.ts` checks allowed origins and hosts | Exists; **not equivalent to authentication** |
| Auth and max clients | No `WEB_PASSWORD` Basic-auth + Engine.IO WebSocket admission or `WEB_MAX_CLIENTS` contract | Hard blockers |
| Secret inheritance | `pty/options.ts` captures `process.env` at import time | Must clear credential before module import |
| Native `/copy` | `configuration/clipboard.ts` silently ignores Clipboard API rejection; Ctrl+Shift+C collides with Firefox | OSC 52 write-only compatibility still needed |
| Android scrolling | Locked xterm 6.0.0 retains touch-scroll regression [#5489](https://github.com/xtermjs/xterm.js/issues/5489) | Hard blocker; review fix #5563 |
| Runtime endpoints | `socketServer/index.ts` exposes metrics/service worker; `serviceWorker.ts` registers caching | Must disable/review in first integration |
| Mobile Ctrl | `term/controls.ts` still injects a delayed Backspace | Test/rewrite for Samsung/Gboard and AltGr |

## Manual Gate 0

Run **only in a disposable credential-free research environment** with Node exactly matching `versions.env`, and git, npm, Python, a C compiler and Make:

```bash
WETTY_RESEARCH_ISOLATED=1 bash scripts/spike-wetty-build.sh
```

The script refuses common credentials, checks exact upstream tag SHA and key lock entries, then installs the locked source dependencies using an exact pnpm version, builds the source and proves a native `node-pty` spawn. It cleans the temporary directory on exit. It does not launch a network listener or alter the image. It executes downloaded package build scripts, so **do not run it in the TrueNAS production instance or an authenticated development session**.

**Validation status:** script authored and subject to repository syntax/CI; third-party source build and native PTY probe are **not yet executed**, because this authoring environment cannot reach GitHub/npm. This is not evidence of WeTTY compatibility with the real image.

## Next acceptance gates (issue #247)

1. Execute Gate 0 on a reviewed disposable AMD64 runner; record dependency sizes/provenance, build results and resource cost, then reproduce against the exact Remote Dev base image (ARM64 later).
2. Loopback-only WeTTY → `attach-remote-dev-tmux` prototype: no SSH, persistent tmux, resize, OSC 8, roles, reconnect.
3. Credential-safe bootstrap + HTTP/Socket.IO polling/WebSocket upgrade auth **before PTY spawn**, Origin, max-clients, base path and elimination of public metrics/PWA/file-download behavior.
4. Native Codex OSC 52 `/copy` on plain-HTTP Firefox, selection/copy feedback, paste, full-screen mouse/TUI, Android scrolling and keyboard layout.
5. Same-digest TrueNAS A/B validation, measured image/RAM/startup cost, security/legal/SBOM and immediate ttyd rollback. Only then decide `PROCEED_WITH_WETTY` vs bounded backport/defer/reject.

Do not ship WeTTY or remove ttyd based on this research spike alone. Reuse #90/#91 for mobile and clipboard follow-up.
