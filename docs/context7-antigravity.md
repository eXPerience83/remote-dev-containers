# Context7 hosted MCP for Antigravity CLI

> **Verified status (2026-11-14):** PR #324 was **merged** as `258d79a` and shipped through experimental `edge`. **Real Context7 tool calls have passed in both agents on TrueNAS Edge**, and AGY's native OAuth flow displayed `Authentication successful!`. Persistence after container recreation, private backups/rollback and #53 review remain pending; there is no later stable publication. Acceptance evidence and remaining TrueNAS checks are tracked in [issue #95](https://github.com/eXPerience83/remote-dev-containers/issues/95) and in the local [v0.3.0 acceptance guide](v0.3.0-acceptance.md), consolidated from PR #345.

This is a per-agent **MCP registration manager**, not an installation of a Context7 server inside the image. The provider's current global MCP file is `~/.gemini/config/mcp_config.json`, using `mcpServers.context7.serverUrl` and Streamable HTTP.

## Codex and Antigravity are independent

Codex keeps its existing API key in its own private state and may supply it to the Codex MCP through an environment-variable header mapping. Antigravity's current JSON remote-headers schema is not equivalent; **Remote Dev must not copy a key into a world-readable or persistent JSON field** or assume environment-variable substitution exists.

The Antigravity entry installed by Remote Dev is initially anonymous:

```json
{"mcpServers":{"context7":{"serverUrl":"https://mcp.context7.com/mcp"}}}
```

Context7 allows anonymous remote access at lower rate limits. **AGY also supports OAuth sign-in natively via `/mcp → context7 → Authenticate` without changing this server entry.** TrueNAS screenshots show a successful OAuth flow; a subsequent read-only inspection verified the **actual token file at `/root/.gemini/antigravity-cli/mcp_oauth_tokens.json`** (mode `0600`, owner `root:root`, directory mode `0700`, ZFS). Compose already mounts **`/mnt/Pool1/remote-dev/state/antigravity/vendor` → `/root/.gemini/antigravity-cli`**. The alternate path `~/.gemini/antigravity/mcp_oauth_tokens.json` documented elsewhere is **absent in this runtime**. No additional mount is needed on current evidence; **survival after container recreation remains untested**. Do not treat an HTTP `/ping` success alone as proof that tools are usable from the CLI.

**External-service privacy notice:** Context7 is operated by Upstash, outside Remote Dev. The provider's [data privacy documentation](https://context7.com/docs/security/data-privacy) says MCP calls send agent-formulated queries and library names/IDs, plus connection/client metadata (including client identity/version, session identifier and IP-related rate-limit data); it documents query use for benchmarking and third-party LLM documentation reranking, and a 30-day API-log retention period. These are **provider statements**, not a Remote Dev guarantee that every generated query is free of secrets. Treat MCP queries as externally disclosed; do not send confidential project data, secrets or regulated personal information through this integration.

## Controls

From **7) MCP integrations... → 1) Context7...**, use the simplified menu or these CLI commands:

```sh
remote-dev-context7-antigravity menu-state
remote-dev-context7-antigravity status --menu
remote-dev-context7-antigravity plan
remote-dev-context7-antigravity reinstall --yes
remote-dev-context7-antigravity remove --yes
remote-dev-context7-antigravity test --yes
```

The passive commands do not modify state or make network calls. `reinstall` is explicit, takes the same directory lock as the Playwright MCP configurator, and replaces only the JSON `mcpServers.context7` entry. It validates all other JSON values and writes a private original-file backup before atomic replacement.

It **refuses to overwrite any customized Context7 entry**, including authentication (headers, OAuth, tokens, command/args or env) **and non-authentication options** such as `timeoutSeconds`, `disabled` or `disabledTools`. All such user-owned entries require manual review and are preserved unchanged, even with an outdated endpoint. Existing non-Context7 MCPs remain semantically unchanged. JSON formatting may be normalized for an eligible reinstall; the original bytes remain in the private backup.

**TrueNAS Edge real-agent PASS (2026-11-14):** `agy /mcp` and real Context7 `resolve-library-id` + `query-docs` calls returned public `/psf/requests` documentation. For independent acceptance after any future reinstall, open Antigravity CLI and run `/mcp`, confirm Context7 connects, then ask a simple public documentation question. `test --yes` tests only the hosted `/ping` endpoint and local JSON contract.

Agent-global scope only: a project's `.agents/mcp_config.json` may supply another Context7 definition. Treat workspace-specific MCP settings as user-owned.

## Shared Context7 menu (#347)

Both agents expose **1 Status/diagnosis**, **2 Test connection**, **3 Manage authentication**, **4 Install/repair**, **5 Remove registration**, and **0 Back**. Main menu option 7 is preserved as *MCP integrations*.

- **Status** and **plan** are passive and offline, without JSON changes. The OAuth token store is never inspected; a `serverUrl` registration **does not imply anonymous or authenticated OAuth**. The output says Antigravity owns authentication and refers to `/mcp`.
- **Test** checks the hosted HTTPS `/ping` and local contract, not account login or successful MCP tool calls.
- **Authentication**: start the Antigravity CLI, use `/mcp → context7 → Authenticate`, confirm `[Authed]` in the vendor interface, and run a real tool. Remote Dev neither copies Codex's key nor reads vendor tokens.
- **Install/repair**: absent registrations can be installed; a simple drifted endpoint can be replaced after preview and confirmation. A healthy registration **does not request REINSTALL or change files**. Invalid JSON or user-customized entries are blocked.
- **Remove** deletes only the provably managed global Context7 registration with a private backup. It neither touches other MCPs nor signs out vendor OAuth or revokes provider authorization; account actions are separate.

CLI: `menu-state` returns only `absent`, `healthy`, `repairable` or `blocked`; `remove --yes` removes only a verified owned registration. Existing `status`, `plan`, `reinstall` and `test` commands and aliases remain supported. Agent projects, sessions, backups and OAuth state are not changed.

Official references:
- https://antigravity.google/docs/mcp
- https://context7.com/docs/resources/all-clients
- https://context7.com/docs/resources/troubleshooting
