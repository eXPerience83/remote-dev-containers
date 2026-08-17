# Optional Context7 integration for Codex

Remote Dev can configure the built-in Codex service to use Context7 as an optional hosted MCP documentation service.

> **Release status:** this integration is being introduced through the current Remote Dev experimental `dev -> edge` path tracked by #31. Reviewed pre-merge candidates may be published to `dev`; `edge` contains only integrated `main`. It is not part of any previously published stable release; stable availability must not be claimed until a stable release containing this change has completed its release gates.

Context7 is operated by **Upstash** and is external to Remote Dev and OpenAI. Remote Dev does not bundle or persist a Context7 CLI, npm package or MCP server runtime. The normal integration uses Codex's native Streamable HTTP MCP client against the reviewed hosted endpoint:

```text
https://mcp.context7.com/mcp
```

When the user explicitly chooses device-code sign-in, Remote Dev transiently downloads and runs one pinned published `ctx7` CLI package only for that authentication operation. The package, its npm cache and its temporary Context7 login state are removed immediately afterward; they are not part of the image or persistent Codex state.

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

A plain interactive `install` or `repair` now asks how authentication should be handled:

1. **Sign in to Context7 with a device code (recommended)** — runs the isolated transient official CLI flow described below.
2. **Enter an existing Context7 API key** — keeps the existing masked manual-key workflow.
3. **Keep the current API key** — or remain anonymous when no managed key exists.
4. **Use anonymous access** — removes only the Remote Dev-managed API-key file.

For reviewed non-interactive automation, the existing lifecycle contract is unchanged: commands accept `--yes`, and `install`/`repair` support `--anonymous` or `--api-key-stdin`; the stdin form requires `--yes` so stdin cannot be confused with an interactive confirmation prompt.

`update` does **not** update the hosted Context7 service and does not download a Context7 runtime. It revalidates and reapplies the hosted-MCP contract shipped in the current Remote Dev image. If Context7 later changes its endpoint or authentication contract, Remote Dev must first ship and review that new contract; running `update` on that newer image can then reapply it.

## Device-code onboarding

The recommended sign-in path deliberately reuses Context7's own published device-login implementation instead of duplicating its OAuth protocol inside Remote Dev.

Remote Dev invokes the exact reviewed `ctx7` package version with:

```text
ctx7 login --no-browser
```

The official CLI displays a one-time code and verification URL that can be approved in any browser. During this one explicit operation Remote Dev:

- runs the transient CLI from a private directory below `/run` rather than the real project or `CODEX_HOME`;
- when the service runs as root, drops the transient vendor package to the fixed unprivileged `nobody` identity with `no-new-privs`;
- uses a fresh HOME, XDG config/state/cache and npm cache;
- disables npm lifecycle scripts and Context7 CLI telemetry for the transient invocation;
- ignores user/global npm configuration and fixes the npm source to the public npm registry;
- does not pass Codex, GitHub, OpenAI or existing Context7 credentials into the transient process;
- validates that the resulting private Context7 credential is the expected long-lived bearer `ctx7sk-...` API-key form;
- passes that key to the existing Remote Dev manager only over child-process stdin;
- removes the complete transient CLI/login/cache directory on success, cancellation or failure.

Remote Dev intentionally does **not** run `ctx7 setup`. That upstream command can write agent MCP configuration, rules and skills; Remote Dev keeps those mutation boundaries under its existing project-owned manager instead. The real `CODEX_HOME`, workspace and project instruction paths are not supplied to the vendor CLI as its HOME, working directory or configuration target, and the existing private Codex credential/configuration paths retain their restrictive permissions.

This unprivileged execution is **not a filesystem sandbox**. The transient vendor process still runs inside the Codex container, so any file elsewhere in that container that is readable by UID/GID 65534 is technically readable by that process. Remote Dev does not direct the CLI to inspect project files, but it does not claim that `nobody` makes world-readable workspace content inaccessible. Use the existing manual API-key path instead if you do not want transient Context7 vendor code executing inside the Codex service.

Before downloading the transient package, Remote Dev performs only the read-only `status --menu` check through the existing manager. That preflight rejects unmanaged, unsafe, damaged or unexpected managed state without running `install` or `repair`. A currently working managed API key is not replaced until the new device login has completed successfully, its local credential shape has been validated and transient state has been cleaned up. Failed, denied, expired or cancelled sign-in performs no manager mutation and leaves the previous working key intact.

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

Context7 can be configured without an API key, subject to the hosted service's anonymous limits. Whether entered manually or adopted from device login, a managed key is stored only in Codex-private persistent state:

```text
$CODEX_HOME/.remote-dev-context7/api-key
```

The state directory is mode `0700` and the key file is mode `0600`. Symlinked, non-regular, wrong-owner or overly permissive key state is rejected.

The key is **not** written into TOML, command arguments, diagnostics, menu status, issue/PR evidence or normal logs. Immediately before launching a Remote Dev-managed Context7 configuration, `run-codex` validates the owned key path and exports `CONTEXT7_API_KEY` only into the Codex process environment. Codex then resolves that environment variable through `env_http_headers` and sends its value in the `CONTEXT7_API_KEY` HTTP header. A managed anonymous configuration suppresses an unrelated inherited value of the same variable. When Context7 is not Remote Dev-managed, the wrapper leaves user-managed environment/configuration alone.

Device login creates an account-side Context7 API key. `remote-dev-context7 remove` removes the local Remote Dev-managed copy but does **not** claim to revoke that account-side key. Rotate or revoke it through Context7's account/dashboard controls when required.

## Availability and network behavior

The managed MCP entry sets:

```toml
required = false
```

so Context7 availability is not a required Codex startup dependency. A Context7 outage can make its documentation tools unavailable, but it must not make the Remote Dev container unhealthy.

Network boundaries are intentionally different for each action:

- container startup with no managed Context7 integration: no Context7 setup/download request;
- `remote-dev-context7 status`: no Context7 network request;
- manual-key/anonymous `install` or `repair`: local configuration/state only;
- device-code sign-in selected from `install`/`repair`: explicit npm download of the pinned transient `ctx7` package plus Context7 device authorization, followed by complete local cleanup;
- `update` and `remove`: local configuration/state only;
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

The official `ctx7 login` flow may display account identity information such as an email/name or teamspace in the local terminal after authorization. Remote Dev does not store that output, but screenshots or copied validation evidence must redact account identifiers as well as device codes and credentials.

Use of the hosted service and the device-login flow is governed by the current **Context7 Addendum**, **Upstash Terms of Service** and **Upstash Privacy Policy**. Remote Dev is not affiliated with or endorsed by Upstash, Context7 or OpenAI.

The legal/privacy review for the original bounded hosted-MCP design is recorded in standing tracker #53. The out-of-cycle #123 review for this exact transient `ctx7` device-authentication design was recorded on 2026-08-16. A different CLI version/source, `ctx7 setup`, native MCP OAuth, retained vendor-package state or broader vendor filesystem/credential access requires re-review.

## Removal and recovery

Because no Context7 runtime/package is retained locally, `remote-dev-context7 remove` remains the uninstall equivalent for this integration. It deletes only the Remote Dev-marked block and the Remote Dev-owned API-key file. It does not remove another MCP server, `AGENTS.md`, Codex instructions, skills, sessions, authentication or an unowned Context7 entry.

If configuration ownership markers are ambiguous, removal refuses to guess. Inspect the config and restore from the private backup if appropriate before retrying.

Removing Context7 does not affect the immutable bundled Codex CLI or the separate optional Codex runtime managed by `remote-dev-codex-runtime`. Device-created account-side API keys must be rotated/revoked through Context7 itself when desired.
