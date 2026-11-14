# Context7 hosted MCP for Antigravity CLI

> **Verified status (2026-11-14):** PR #324 was **merged** as `258d79a` and shipped through experimental `edge`. **Real Context7 tool calls have passed in both agents on TrueNAS Edge**, and AGY's native OAuth flow displayed `Authentication successful!`. Persistence after container recreation, private backups/rollback and #53 review remain pending; there is no later stable publication. See the [v0.3.0 acceptance guide](v0.3.0-acceptance.md).

This is a per-agent **MCP registration manager**, not an installation of a Context7 server inside the image. The provider's current global MCP file is `~/.gemini/config/mcp_config.json`, using `mcpServers.context7.serverUrl` and Streamable HTTP.

## Codex and Antigravity are independent

Codex keeps its existing API key in its own private state and may supply it to the Codex MCP through an environment-variable header mapping. Antigravity's current JSON remote-headers schema is not equivalent; **Remote Dev must not copy a key into a world-readable or persistent JSON field** or assume environment-variable substitution exists.

The Antigravity entry installed by Remote Dev is initially anonymous:

```json
{"mcpServers":{"context7":{"serverUrl":"https://mcp.context7.com/mcp"}}}
```

Context7 allows anonymous remote access at lower rate limits. **AGY also supports OAuth sign-in natively via `/mcp → context7 → Authenticate` without changing this server entry.** TrueNAS screenshots show a successful OAuth flow; a subsequent read-only inspection verified the **actual token file at `/root/.gemini/antigravity-cli/mcp_oauth_tokens.json`** (mode `0600`, owner `root:root`, directory mode `0700`, ZFS). Compose already mounts **`/mnt/Pool1/remote-dev/state/antigravity/vendor` → `/root/.gemini/antigravity-cli`**. The alternate path `~/.gemini/antigravity/mcp_oauth_tokens.json` documented elsewhere is **absent in this runtime**. No additional mount is needed on current evidence; **survival after container recreation remains untested**. Do not treat an HTTP `/ping` success alone as proof that tools are usable from the CLI.

**External-service privacy notice:** Context7 is operated by Upstash, outside Remote Dev. Agent-generated documentation searches and library identifiers are sent to the hosted provider. Treat MCP queries as externally disclosed; do not send confidential project data, secrets or regulated personal information through this integration.

## Controls

From Antigravity's terminal menu, choose **7) Context7 MCP integration...**, then Preview, Install/reinstall, or Test; or use:

```sh
remote-dev-context7-antigravity status --menu
remote-dev-context7-antigravity plan
remote-dev-context7-antigravity reinstall --yes
remote-dev-context7-antigravity test --yes
```

The passive commands do not modify state or make network calls. `reinstall` is explicit, takes the same directory lock as the Playwright MCP configurator, and replaces only the JSON `mcpServers.context7` entry. It validates all other JSON values and writes a private original-file backup before atomic replacement.

It **refuses to overwrite any customized Context7 entry**, including authentication (headers, OAuth, tokens, command/args or env) **and non-authentication options** such as `timeoutSeconds`, `disabled` or `disabledTools`. All such user-owned entries require manual review and are preserved unchanged, even with an outdated endpoint. Existing non-Context7 MCPs remain semantically unchanged. JSON formatting may be normalized for an eligible reinstall; the original bytes remain in the private backup.

**TrueNAS Edge real-agent PASS (2026-11-14):** `agy /mcp` and real Context7 `resolve-library-id` + `query-docs` calls returned public `/psf/requests` documentation. For independent acceptance after any future reinstall, open Antigravity CLI and run `/mcp`, confirm Context7 connects, then ask a simple public documentation question. `test --yes` tests only the hosted `/ping` endpoint and local JSON contract.

Agent-global scope only: a project's `.agents/mcp_config.json` may supply another Context7 definition. Treat workspace-specific MCP settings as user-owned.

Official references:
- https://antigravity.google/docs/mcp
- https://context7.com/docs/resources/all-clients
- https://context7.com/docs/resources/troubleshooting
