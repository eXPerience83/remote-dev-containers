# OpenAI Docs MCP for Codex

The official OpenAI documentation MCP is enabled by default only when private Codex state is empty at first startup. Existing installations keep every file; Context7 remains optional. No new parameters or mounts are needed.

Offline initialization runs before Codex, with the image administrative interpreter. A private `.remote-dev-initial-config-v1/` transaction records the decision: an empty home without it starts provisioning; a pending transaction can recover; `done` prevents reinstating a removed or disabled server. Publication is atomic without replacing a destination, files use 0600, and initializers serialize with a directory lock. Avoid editing the same state during startup. Independently created state wins and provisioning is skipped. Unsafe state or permission errors warn without adding a health dependency.

Provisioning does not use the network. Codex may connect to initialize the MCP and discover tools when a session opens, before a documentation query. `required=false`, a 10 s startup timeout and 60 s tool timeout bound waits; an MCP outage must not prevent normal sessions. Global guidance adds a selective documentation reminder only to Codex; Antigravity retains the common guidance.

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
