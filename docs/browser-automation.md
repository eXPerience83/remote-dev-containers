# Browser automation shared by all coding agents

Remote Dev bundles a pinned Playwright MCP server and its matching Chromium
headless-shell browser in the common base image. No Snap, Docker socket, web
port, image-time user credentials, or runtime package downloads are required.

At session start, Remote Dev **adds the missing** `playwright` MCP entry to the
private provider config:

- Codex: `/root/.codex/config.toml` (`[mcp_servers.playwright]`).
- Antigravity CLI: `/root/.gemini/config/mcp_config.json`
  (`mcpServers.playwright`).
- Claude Code, when supported later, can use the same already installed
  command: `claude mcp add --scope user playwright -- /usr/local/bin/remote-dev-playwright-mcp`.
  Claude is **not installed or auto-configured** by this change.

If the user already defines `playwright`, it stays untouched, including disabled
custom definitions. Other provider settings are retained; invalid or unsafe
private files are never replaced. Provisioning does not run for `--help` or
passive vendor commands, and no provider configuration is shared across roles.

The MCP server is spawned on-demand over **stdio**, uses an isolated browser
profile, does not expose a listening port, and stops with its agent session.
`playwright --version` checks the image's CLI installation.

## Security and operational considerations

The container runs its coding agents as root behind the outer container
boundary. Chromium therefore uses `chromiumSandbox: false`; this does **not**
provide a second browser isolation boundary. Only browse trusted destinations,
avoid typing credentials into untrusted sites, and retain the existing hardened
container deployment (no privileged mode or Docker socket). Any future
sandboxed non-root browser needs a separate hardening review.

Do not install browser binaries into `/tmp` or at runtime. Browser payloads
live read-only in `/opt/remote-dev/playwright-browsers`, distinct from the
ephemeral profile. Installation must pass AMD64 image-build and runtime smoke
tests before merging.

## Validation

1. Run `python scripts/test-browser-config.py`.
2. Build the common image: the bundled Chromium headless shell and libraries
   must install without Snap or a runtime download.
3. Start Codex and Antigravity with existing private configs, verify the
   `playwright` server is present, and navigate to an inert local page.
4. Confirm custom `playwright` definitions, other MCP servers, and private
   credentials remain unchanged. Confirm no new listening port is opened.
