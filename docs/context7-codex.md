# Optional Context7 integration for Codex

Remote Dev can configure the built-in Codex service to use Context7 as an optional hosted MCP documentation service.

> **Release status:** this integration is being introduced through the current Remote Dev experimental `dev -> edge` path tracked by #31. Reviewed pre-merge candidates may be published to `dev`; `edge` contains only integrated `main`. It is not part of any previously published stable release; stable availability must not be claimed until a stable release containing this change has completed its release gates.

Context7 is operated by **Upstash** and is external to Remote Dev and OpenAI. Remote Dev does not bundle, redistribute, install or persist the Context7 CLI, npm package or MCP server runtime for this integration. The integration uses Codex's native Streamable HTTP MCP client against the reviewed hosted endpoint:

```text
https://mcp.context7.com/mcp
```

## Explicit lifecycle

Nothing is configured or contacted merely by building or starting Remote Dev. Use the Codex menu under **Context7 integration...** or the project-owned command:

```bash
remote-dev-context7 status
remote-dev-context7 install
remote-dev-context7 repair
remote-dev-context7 test
remote-dev-context7 update
remote-dev-context7 remove
```

`status` is passive and performs no Context7 network request. `install`, `repair`, `update` and `remove` may change Codex-private persistent files, so they require explicit confirmation. `test` requires explicit confirmation because it performs a live reachability check against Context7's documented `/ping` endpoint.

For reviewed non-interactive automation, lifecycle commands accept `--yes`. `install`/`repair` additionally support `--anonymous` or `--api-key-stdin`; the stdin form requires `--yes` so stdin cannot be confused with an interactive confirmation prompt.

`update` does **not** update the hosted Context7 service and does not download a Context7 runtime. It revalidates and reapplies the hosted-MCP contract shipped in the current Remote Dev image. If Context7 later changes its endpoint or authentication contract, Remote Dev must first ship and review that new contract; running `update` on that newer image can then reapply it.

## Managed Codex configuration

Remote Dev owns only one explicitly marked block inside the existing persistent `CODEX_HOME/config.toml`:

```toml
# BEGIN REMOTE DEV MANAGED CONTEXT7
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
env_http_headers = { "CONTEXT7_API_KEY" = "CONTEXT7_API_KEY" }
enabled = true
required = false
# END REMOTE DEV MANAGED CONTEXT7
```

Context7's current Codex client documentation requires an HTTP header named `CONTEXT7_API_KEY` for API-key authentication. Codex's `env_http_headers` setting maps that header to an environment-variable name, so the secret value remains outside the TOML file while Codex sends the header expected by the hosted MCP service.

All configuration outside those markers is preserved. Before writing, the manager parses the existing TOML and refuses to overwrite a pre-existing, unowned `mcp_servers.context7` entry. Missing, duplicated or malformed ownership markers also fail closed instead of guessing which content belongs to Remote Dev.

When the managed block changes, the previous complete config is saved privately as:

```text
$CODEX_HOME/config.toml.remote-dev-context7.bak
```

The replacement is written through a same-directory temporary file and atomically renamed into place. Config and backup files are restricted to the Codex service user.

## API-key handling

Context7 can be configured without an API key, subject to the hosted service's anonymous limits. If a key is supplied, Remote Dev stores it only in Codex-private persistent state:

```text
$CODEX_HOME/.remote-dev-context7/api-key
```

The state directory is mode `0700` and the key file is mode `0600`. Symlinked, non-regular, wrong-owner or overly permissive key state is rejected.

The key is **not** written into TOML, command arguments, diagnostics, menu status, issue/PR evidence or normal logs. Immediately before launching a Remote Dev-managed Context7 configuration, `run-codex` validates the owned key path and exports `CONTEXT7_API_KEY` only into the Codex process environment. Codex then resolves that environment variable through `env_http_headers` and sends its value in the `CONTEXT7_API_KEY` HTTP header. A managed anonymous configuration suppresses an unrelated inherited value of the same variable. When Context7 is not Remote Dev-managed, the wrapper leaves user-managed environment/configuration alone.

## Availability and network behavior

The managed MCP entry sets:

```toml
required = false
```

so Context7 availability is not a required Codex startup dependency. A Context7 outage can make its documentation tools unavailable, but it must not make the Remote Dev container unhealthy.

Network boundaries are intentionally different for each action:

- container startup with no managed Context7 integration: no Context7 setup/download request;
- `remote-dev-context7 status`: no Context7 network request;
- `install`, `repair`, `update`, `remove`: configuration/state operations only; no Context7 package download;
- `test`: explicit live check of the bundled Codex config plus `https://mcp.context7.com/ping`;
- a normal Codex session after Context7 has been enabled: Codex may contact the configured hosted MCP endpoint as part of normal MCP initialization and tool use.

The image build also creates a temporary anonymous managed config and requires the exact bundled Codex binary to parse and report that one server through the local-only `codex mcp get context7 --json` path. This avoids both network-capable MCP authentication discovery and reliance on `codex mcp add --url` as the trusted mutation primitive.

## Privacy, terms and documentation licenses

Enabling Context7 creates an external-service boundary. Based on the official Context7/Upstash documentation reviewed for issue #94:

- Remote Dev does not intentionally send the full original prompt, source files or conversation to Context7; Codex formulates MCP documentation requests and the query text it sends must nevertheless be treated as data disclosed to an external service;
- an HTTP MCP request can include the documentation query and library identifiers plus normal HTTP/MCP metadata produced by the configured Codex client, such as client identity/version and protocol/transport headers; authenticated mode additionally sends the `CONTEXT7_API_KEY` header;
- those MCP-generated queries can be processed for retrieval/reranking and anonymously stored for retrieval-quality benchmarking;
- Context7 documents 30-day API-log retention;
- users should not send sensitive, health, payment or other regulated data through the service;
- Context7 output can be incomplete or inaccurate and should be verified before production use;
- the underlying documentation returned by Context7 remains subject to its original copyright and license terms.

Use of the hosted service is governed by the current **Context7 Addendum**, **Upstash Terms of Service** and **Upstash Privacy Policy**. Remote Dev is not affiliated with or endorsed by Upstash, Context7 or OpenAI.

The legal/privacy review for this bounded hosted-MCP design is recorded in standing tracker #53. A new review is required if Remote Dev later redistributes Context7 code/packages, changes transport/authentication, or materially expands the data sent to the service.

## Removal and recovery

Because no Context7 runtime/package is installed locally, `remote-dev-context7 remove` is the uninstall equivalent for this integration. It deletes only the Remote Dev-marked block and the Remote Dev-owned API-key file. It does not remove another MCP server, `AGENTS.md`, Codex instructions, skills, sessions, authentication or an unowned Context7 entry.

If configuration ownership markers are ambiguous, removal refuses to guess. Inspect the config and restore from the private backup if appropriate before retrying.

Removing Context7 does not affect the immutable bundled Codex CLI or the separate optional Codex runtime managed by `remote-dev-codex-runtime`.
