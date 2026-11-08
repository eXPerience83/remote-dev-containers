# OpenAI Docs MCP for Codex

Status: Unreleased functionality in PR #312, not included in the v0.2.0 stable image. To test it, inspect the source revision with `remote-dev-version` and match it to a PR candidate SHA containing this change; an older container does not provision the MCP even with an empty home.

The official OpenAI documentation MCP is enabled by default only when private Codex state is empty at first startup. Existing installations keep every file; Context7 remains optional. No new parameters or mounts are needed.

Offline initialization runs before Codex, with the image administrative interpreter. A private `.remote-dev-initial-config-v1/` transaction records the decision: an empty home without it starts provisioning; a pending transaction can recover; `done` prevents reinstating a removed or disabled server. Publication is atomic without replacing a destination, files use 0600, and initializers serialize with a directory lock. Avoid editing the same state during startup. Before the initial decision, any existing state skips provisioning. Once an empty-home decision is recorded, recovery can provision even if Codex has created other state; a competing config.toml always wins. The lock waits at most two seconds, then warns and continues. Existing homes record their skipped decision in `.remote-dev-initial-config-skipped-v1/`. Unsafe state or permission errors warn without adding a health dependency.

Provisioning does not use the network. Codex may connect to initialize the MCP and discover tools when a session opens, before a documentation query. `required=false`, a 10 s startup timeout and 60 s tool timeout bound waits; normal-session availability during an MCP outage is a design goal whose timing and behavior still require exact-candidate acceptance; it has not yet been demonstrated by the recorded tests. Global guidance adds a selective documentation reminder only to Codex; Antigravity retains the common guidance.

The public remote OpenAI server is read-only, needs no keys and does not invoke the OpenAI API on your behalf. Its operator receives connections and tool arguments; exclude secrets, private code and complete conversations. Schemas and results can consume context/tokens. No additional retention or private accounting guarantees are made. Configuration persists in the private CODEX_HOME mount; mount inspection does not replace a real TrueNAS recreation test.

```bash
# Inspect configuration (not a connectivity test)
codex mcp get openaiDeveloperDocs
# Inventory; may perform authentication discovery
codex mcp list
# Add manually only if absent (existing installations)
codex mcp add openaiDeveloperDocs --url https://developers.openai.com/mcp
# Explicit removal
codex mcp remove openaiDeveloperDocs
```

In a session, use `/mcp` and request a documentation search and read to verify actual operation. To disable without removal, set `enabled = false` in `[mcp_servers.openaiDeveloperDocs]`. Do not delete the marker to repair: first inspect `codex mcp get`, then add manually only if absent; preserve custom or disabled entries. Start a new session to verify changes.

Sources: [Docs MCP](https://developers.openai.com/learn/docs-mcp), [Codex MCP configuration](https://developers.openai.com/codex/mcp/).

If `done` is malformed, stop the service before repair. Verify the transaction is a real private directory with safe ownership and no symlinks, and preserve config.toml and any disable/removal decision. Remove only the `.remote-dev-initial-config.toml` staging link inside the transaction if present; do not delete config.toml. Atomically replace only `done`, using a private temporary in that directory, with the bytes `done` followed by a newline, mode 0600 and the correct owner. This records completion without installing or reactivating the MCP. Unsafe paths/ownership require manual administrator repair; do not run provisioning against them.
