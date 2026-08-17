# Optional Context7 integration for Codex

Remote Dev can configure the built-in Codex service to use Context7 as an optional hosted MCP documentation service.

> **Release status:** this integration is being introduced through the current Remote Dev experimental `dev -> edge` path tracked by #31. Reviewed pre-merge candidates may be published to `dev`; `edge` contains only integrated `main`. Stable availability must not be claimed until a stable release containing this change has completed its release gates.

Context7 is operated by **Upstash** and is external to Remote Dev and OpenAI. The normal integration uses Codex's native Streamable HTTP MCP client against:

```text
https://mcp.context7.com/mcp
```

Remote Dev does **not** bundle or persist the Context7 CLI or an MCP server runtime. Device-code sign-in downloads an exact official `ctx7` npm package transiently, runs it only for authentication, and removes the package, npm cache and temporary vendor state afterward. Only the API key adopted into Remote Dev's existing private Context7 state persists.

## Explicit lifecycle

Use **Context7 integration...** in the Codex menu or:

```bash
remote-dev-context7 status
remote-dev-context7 install
remote-dev-context7 repair
remote-dev-context7 test
remote-dev-context7 update
remote-dev-context7 remove
```

`status` is passive. `install`, `repair`, `update` and `remove` can mutate Codex-private persistent state and require explicit confirmation. `test` also requires confirmation because it performs a live check against Context7's documented `/ping` endpoint.

A plain interactive `install` or `repair` asks how authentication should be handled:

1. **Sign in to Context7 with a device code (recommended)**.
2. **Enter an existing Context7 API key** using the existing masked manual-key path.
3. **Keep the current managed API key**, or stay anonymous when none exists.
4. **Use anonymous access**, removing only the Remote Dev-managed API-key file.
5. **Cancel**.

The existing non-interactive manager contract remains available with `--yes`, `--anonymous` and `--api-key-stdin`. Device-login automation can additionally choose `--cli-channel reviewed` or `--cli-channel latest`; the interactive menu uses `auto`.

`remote-dev-context7 update` revalidates/reapplies the hosted MCP configuration shipped by the image. It is separate from the transient `ctx7` CLI version used only for device authentication.

## Reviewed and latest official Context7 CLI

Remote Dev keeps one exact **reviewed** `ctx7` version in the image source. The repository's upstream-maintenance automation is responsible for proposing newer reviewed pins; it must not silently change stable state.

For an interactive device login Remote Dev first resolves the current `latest` metadata from the fixed public npm registry. It validates the package identity, exact stable semantic version, reviewed MIT license contract and npm integrity metadata before any vendor package is executed.

- If `latest` equals the Remote Dev-reviewed version, that exact version is used.
- If npm has a newer version, Remote Dev shows both versions and lets the user choose:
  - the reviewed version (recommended); or
  - the exact current latest official version, labelled **`official source; Remote Dev review pending`**.
- A newer version is **not blocked merely because Remote Dev review is pending**. It must still pass the origin/metadata/integrity and post-login credential/cleanup gates.
- `latest` is resolved first and Remote Dev then executes `ctx7@X.Y.Z`; it never asks npm to execute a mutable `ctx7@latest` specifier.
- An incompatible source, package identity, version format, license contract, integrity record or credential model fails closed.

This matches the optional-runtime principle used for Codex and Antigravity: review evidence describes known-good versions but is not an availability allowlist.

## Device-code onboarding

Remote Dev invokes only:

```text
ctx7 login --no-browser
```

It intentionally never runs `ctx7 setup`, which can modify agent MCP configuration, rules and skills outside Remote Dev's existing ownership model.

During device login Remote Dev:

- creates a fresh private `/run/remote-dev-context7-login-*` subtree;
- uses fresh HOME, XDG config/state/cache/runtime, temp, npm cache and npm user/global config paths;
- pins the public npm registry, disables npm lifecycle scripts, audit/fund/update noise and Context7 telemetry;
- passes the image-pinned Node version explicitly to the bundled mise/npm shim with offline mise resolution;
- does not pass existing Codex, OpenAI, GitHub or Context7 credentials, the real `CODEX_HOME`, or project paths as vendor HOME/config/working-directory targets;
- when running as root, executes npm/Context7 as UID/GID 65534 with cleared groups and `no-new-privs`;
- starts the vendor process in its own process group with `umask 077`;
- gives the vendor CLI `/dev/null` as stdin. Remote Dev retains terminal input and displays **`type q and press Enter`** as the supported cancellation path while browser authorization is pending. `Ctrl+C` remains only a fallback because browser/ttyd/tmux signal propagation is not relied upon;
- terminates/reaps the entire process group on cancellation or timeout, with bounded TERM/KILL cleanup;
- validates every credential-path component without following symlinks, with expected ownership/private modes and bounded file size;
- accepts only the long-lived bearer `ctx7sk-...` API-key form already used by the reviewed flow; refresh/expiry credential state is rejected;
- removes the complete transient CLI/login/cache tree before handing the resulting API key to the existing manager over child-process stdin.

This UID/GID drop is **not a filesystem sandbox**. Files elsewhere in the Codex container that are readable by UID/GID 65534 remain technically readable by the transient process. Use the manual API-key path if you do not want transient Context7 vendor code executing inside the Codex service.

Before any transient npm/vendor work, Remote Dev performs only the existing manager's read-only `status --menu` preflight. A failed, denied, expired or cancelled device login performs no manager mutation, so a previously working managed API key remains unchanged.

## Managed Codex configuration

Remote Dev owns only this marked block in persistent `CODEX_HOME/config.toml`:

```toml
# BEGIN REMOTE DEV MANAGED CONTEXT7
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
env_http_headers = { "CONTEXT7_API_KEY" = "CONTEXT7_API_KEY" }
enabled = true
required = false
# END REMOTE DEV MANAGED CONTEXT7
```

Everything outside those markers is preserved. An existing unowned `mcp_servers.context7` entry, ambiguous markers or unsafe state fail closed. Before replacing a managed block, the complete previous config is saved privately as:

```text
$CODEX_HOME/config.toml.remote-dev-context7.bak
```

## API-key handling

A managed key, whether entered manually or obtained by device login, is stored only at:

```text
$CODEX_HOME/.remote-dev-context7/api-key
```

The state directory is `0700` and the key file `0600`. Symlinked, non-regular, wrong-owner or overly permissive state is rejected.

The key is not written into TOML, command arguments, diagnostics, menu status or normal logs. `run-codex` injects `CONTEXT7_API_KEY` only into the Codex child when the Remote Dev-managed integration is healthy. Anonymous managed mode suppresses an unrelated inherited variable of the same name. Unmanaged Context7 configuration is left alone.

Device login creates an account-side Context7 API key. `remote-dev-context7 remove` removes the local managed copy and config block; it does **not** revoke the account-side key.

## Availability and network behavior

The managed MCP entry uses `required = false`, so a Context7 outage cannot make the Remote Dev container unhealthy.

Network boundaries:

- startup and `status`: no Context7 setup/download request;
- manual-key/anonymous `install` or `repair`: local state only;
- device login: explicit public-npm metadata lookup and exact transient package download, then Context7 device authorization;
- `update`/`remove`: local state only;
- `test`: explicit live config + `https://mcp.context7.com/ping` check;
- normal enabled Codex sessions: Codex may contact the hosted MCP endpoint for initialization and tool use.

## Privacy, terms and evidence

Context7 is an external service. MCP-generated documentation queries must be treated as data disclosed to Context7/Upstash; do not send sensitive, health, payment or other regulated data through the integration. Context7 output can be incomplete or inaccurate and underlying documentation retains its original licenses.

The official device flow sends the container hostname on a best-effort basis with the authorization request so the browser page can identify the device. After approval, the CLI uses the freshly issued key for `whoami` and may display account identity/teamspace locally. Remote Dev does not persist that CLI output.

**Never put device codes, unique authorization URLs, API keys, account identifiers, email addresses or teamspace names into issue/PR validation evidence.**

Use of the hosted service/device flow remains subject to the current Context7 Addendum, Upstash Terms of Service and Upstash Privacy Policy. The standing legal/privacy record is tracked in #53. The 2026-08-17 re-review accepts `ctx7@0.5.8` as the reviewed login version and records the explicit reviewed-vs-latest-official admission model. A material change in source/origin, license, authentication/credential lifecycle, retained state, disclosure or filesystem/credential access still requires #53 review.

## Removal and recovery

Because no Context7 CLI/runtime is retained, `remote-dev-context7 remove` is the local uninstall equivalent. It removes only Remote Dev-owned Context7 config/key state and does not touch other MCP servers, Codex sessions, projects, skills or unmanaged configuration.

Removing Context7 does not affect the immutable bundled Codex CLI or the optional Codex runtime managed by `remote-dev-codex-runtime`.
