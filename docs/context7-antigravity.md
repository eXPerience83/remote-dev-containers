# Context7 hosted MCP for Antigravity CLI

> **Verified status (2026-11-14):** PR #324 was **merged** as `258d79a` and shipped through experimental `edge`. Real Codex/Antigravity use on TrueNAS and role-local rollback **have not yet been accepted**; there is no later stable publication. CI success alone does not prove real `agy /mcp` tool calls. See the [v0.3.0 acceptance guide](v0.3.0-acceptance.md).

This is a per-agent **MCP registration manager**, not an installation of a Context7 server inside the image. The provider's current global MCP file is `~/.gemini/config/mcp_config.json`, using `mcpServers.context7.serverUrl` and Streamable HTTP.

## Codex and Antigravity are independent

Codex keeps its existing API key in its own private state and may supply it to the Codex MCP through an environment-variable header mapping. Antigravity's current JSON remote-headers schema is not equivalent; **Remote Dev must not copy a key into a world-readable or persistent JSON field** or assume environment-variable substitution exists.

The Antigravity entry installed by Remote Dev is initially anonymous:

```json
{"mcpServers":{"context7":{"serverUrl":"https://mcp.context7.com/mcp"}}}
```

Context7 allows anonymous remote access at lower rate limits. Do not treat an HTTP `/ping` success as proof that tools are usable from the Antigravity CLI.

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

For a real functional check after installing or reinstalling, open Antigravity CLI and run `/mcp`, confirm Context7 connects, then ask a simple public documentation question. `test --yes` tests only the hosted `/ping` endpoint and local JSON contract.

Agent-global scope only: a project's `.agents/mcp_config.json` may supply another Context7 definition. Treat workspace-specific MCP settings as user-owned.

Official references:
- https://antigravity.google/docs/mcp
- https://context7.com/docs/resources/all-clients
- https://context7.com/docs/resources/troubleshooting
