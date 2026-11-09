# OpenAI Docs MCP for Codex

Status: merged through [PR #312](https://github.com/eXPerience83/remote-dev-containers/pull/312) and included in the `v0.2.1` source release cut, not in the previously published `v0.2.0` stable image. A `v0.2.1` container is available only after its independent stable-tag publisher has passed. Inspect the actual image source revision with `remote-dev-version`; older images never auto-provision this MCP, even with empty Codex state.

The official OpenAI documentation MCP is enabled by default only when private Codex state is empty at first startup. Existing installations keep every file; Context7 remains optional. No new parameters or mounts are needed.

Offline initialization runs before Codex, with the image administrative interpreter. A private `.remote-dev-initial-config-v1/` transaction records the decision: an empty home without it starts provisioning; a pending transaction can recover; `done` prevents reinstating a removed or disabled server. Publication is atomic without replacing a destination, files use 0600, and initializers serialize with a directory lock. Avoid editing the same state during startup. The initial directory scan is the cutoff: state observed by that scan skips provisioning. Other files such as auth.json created after the scan, even before the transaction directory is created, do not change that decision. A competing config.toml still prevents publication. Once an empty-home decision is recorded, recovery can provision even if Codex has created other state; a competing config.toml always wins. The lock waits at most two seconds, then warns and continues. Existing homes record their skipped decision in `.remote-dev-initial-config-skipped-v1/`. Unsafe state or permission errors warn without adding a health dependency.

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

In a session, use `/mcp` and request a documentation search and read to verify actual operation. To disable without removal, set `enabled = false` in `[mcp_servers.openaiDeveloperDocs]`. Do not delete the marker to repair: first inspect `codex mcp get openaiDeveloperDocs`, then add manually only if absent and you explicitly want it restored; preserve intentional removals and preserve custom or disabled entries. Start a new session to verify changes.

Sources: [Docs MCP](https://developers.openai.com/learn/docs-mcp), [Codex MCP configuration](https://developers.openai.com/codex/mcp/).

If `done` is malformed, stop the service before repair. Verify the transaction is a real private directory with safe ownership and no symlinks, and preserve config.toml and any disable/removal decision. Remove only the `.remote-dev-initial-config.toml` staging link inside the transaction if present; do not delete config.toml. Atomically replace only `done`, using a private temporary in that directory, with the bytes `done` followed by a newline, mode 0600 and the correct owner. This records completion without installing or reactivating the MCP. Unsafe paths/ownership require manual administrator repair; do not run provisioning against them.

## Exact-candidate TrueNAS acceptance (pending)

Use a separate test App and private ZFS-backed state/workspace paths, not production. After final CI/review, an owner may request `/publish-candidate <full-PR-head-SHA>` under the existing release procedure. Record the candidate workflow, immutable digest, source SHA and `remote-dev-version` output; all enabled services must use that same candidate image. Keep the previous test image digest for rollback. This guide does not authorize publication or deployment.

All rows below remain pending until exercised on that exact candidate. Use synthetic state and never attach complete configuration, credentials or private instructions to evidence.

| Scenario | Procedure and expected evidence |
|---|---|
| Empty first startup | Confirm the Codex state directory is truly empty before starting. Start the test App; verify `codex mcp get openaiDeveloperDocs` reports the official URL and enabled state, and Context7 is absent unless explicitly configured. Confirm initialization precedes vendor state creation. |
| Existing state upgrade | In a separate fixture, retain existing custom MCP/configuration, instructions and synthetic state. Upgrade to the candidate; compare private local hashes/bytes without publishing them. Existing files and disabled entries must remain unchanged; no unsolicited Docs MCP registration. |
| Recreation and image replacement | Recreate the test containers against the same state paths, then replace the test image while retaining those paths. Check mount identity, recorded initialization decision, MCP state and user content persist. Record source/digest on each side; a mounted path alone is insufficient evidence. |
| Disable and remove | Set `enabled=false`, recreate and verify disabled. Separately remove the entry through the native command, recreate and verify absent. Repeat after image replacement. Neither action may reinstall the server. |
| Live documentation | With network available, use `/mcp`, then request a narrowly scoped official-documentation search and page read with citations. Record successful tool names and public source URLs. Config inventory alone is not connectivity evidence. |
| Network outage | In the disposable test deployment, deny access to the Docs MCP endpoint without changing runtime security or production. Exercise Start, Resume, tmux reconnect, health and session exit. Record delays, warnings and availability; the initialization/tool timeouts do not establish a total session-latency guarantee. Restore networking afterwards. |
| Selective use | Ask an unfamiliar Codex configuration question and observe relevant documentation calls. Perform an unrelated coding task and observe no documentation query without a reason. Distinguish session handshake/catalog traffic from tool calls. |
| Role/security regression | Verify separate role mounts, unchanged mandatory ttyd authentication/origin checks and optional Context7 behavior. Launcher and Antigravity must receive no Codex state or new documentation instruction fragment. |

Attach the completed scenario matrix with SHA/digest and sanitized observations to #311/#312. Leave failures and untested rows explicit; do not mark persistence or offline acceptance complete from CI alone. Restore the previous test digest if acceptance fails, preserving the test state for diagnosis.
