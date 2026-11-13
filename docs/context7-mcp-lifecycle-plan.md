# Context7 MCP diagnostics and isolated reinstalls — delivery plan

**Status:** IN PROGRESS (PR #324, draft; not a release approval).
**Updated:** 2026-11-13. **Owners:** Remote Dev maintainers.
**Trackers:** #95 (Antigravity), #53 (vendor/legal review), PR #323 (Codex legacy diagnostics), PR #324 (this implementation).
**Decision record:** [D016](decisions.md#d016--context7-is-a-role-local-hosted-mcp-registration-with-explicit-reinstall).

## Goal and non-goals

An updated Remote Dev **image** must detect a missing, malformed, stale or customized Context7 MCP registration and offer a safe **reinstall of that MCP registration alone** in both Codex and Antigravity. Do not special-case a particular TrueNAS user's broken state. Context7 is a *hosted* Upstash MCP: there is no persistent Context7 daemon, npm package or Docker image to remove or reinstall. An image update delivers the newer manager; user-authorized reinstall rewrites only the provider's registered MCP entry.

Never reinstall the agent, remove the whole MCP config, change other MCPs (Playwright/OpenAI Developer Docs), modify credentials automatically, share secrets between services, pull arbitrary packages or make a network call from passive diagnosis. Do not change the experimental support status of Antigravity.

## Architecture and decisions

| Boundary | Codex | Antigravity CLI |
|---|---|---|
| Persistent config | Role-private `CODEX_HOME/config.toml` | Role-private `/root/.gemini/config/mcp_config.json` |
| Provider MCP shape | TOML `[mcp_servers.context7]` with official HTTPS `url`, `env_http_headers`, `enabled=true`, `required=false` | JSON `mcpServers.context7.serverUrl` using Streamable HTTP |
| Credential behavior | Keep existing `.remote-dev-context7/api-key` in Codex-private state, never print or copy | Initially anonymous; **never** copy Codex key into Antigravity JSON; refuse to overwrite entries with user-managed authentication |
| Passive commands | `status --menu`, `plan`, Doctor | `status --menu`, `plan`, Doctor |
| Write operation | Explicit `remote-dev-context7 reinstall --yes` / Codex menu | Explicit `remote-dev-context7-antigravity reinstall --yes` / Antigravity menu |
| Live check | Explicit Context7 endpoint test plus real Codex MCP tool call | Explicit endpoint test plus actual `agy /mcp` and tool call |
| Concurrency | Shared directory flock with Playwright; snapshot check, private original backup, atomic replacement | Shared directory flock with Playwright JSON config provider; dirfd validation, private original backup, atomic replacement |
| Customization | Explicit reinstall resets **Context7-only** user adjustments, warn before confirmation; fail closed if scope is ambiguous | Any extra Context7 option, with or without credentials (e.g. `disabledTools`, `timeoutSeconds`), is considered user-owned; reinstall refuses to overwrite and requires manual review |

Two distinct operations must remain clearly labeled:
- **Legacy repair** matches a narrow reviewed old format. If ineligible, do not try blind text patching.
- **Reinstall** isolates the whole Context7 MCP entry by provider-native config boundaries, validates a full proposed document before writing, and only then atomically replaces the registration with the image-reviewed contract.

**Provider-specific ownership:** For Codex, refuse malformed or ambiguous TOML table boundaries, duplicate ownership markers, or changes to any parsed value outside Context7. Preserve raw unrelated TOML bytes, including mixed line endings. For Antigravity, reject malformed JSON, duplicate keys, symlinks/FIFOs and credential-bearing custom entries; preserve non-Context7 JSON *values* (JSON formatting may be normalized) and back up original bytes. A workspace-level `.agents/mcp_config.json` or plugin-supplied MCP definition is **not** a global entry owned by Remote Dev; document the limitation and test for conflicts before claiming a live success.

## Product experience / state matrix

| Detected state | Passive diagnosis | Menu recommendation | Automatic changes |
|---|---|---|---|
| No Context7 entry | Not installed (optional) | Install/reinstall Context7 | None |
| Matches reviewed image contract | Healthy | Test connection, no action | None |
| Context7 drift/legacy format with unambiguous scope | Needs attention | Preview **reinstall** → show what resets → explicit confirmation → re-test | None |
| User-authenticated/custom entry | User-owned/custom or needs review | Preserve credentials; do not override silently | None |
| Invalid file, ambiguous ownership, duplicate data, unsafe private state | Unsafe/blocked with safe reason | Manual review; no mutation | None |
| Hosted service unreachable or rate limited | Connection test fails, local config may still be valid | Report network/auth separately; do not reinstall based solely on a ping failure | None |

Status/plan/doctor must be offline, bounded, read-only and redact user config/key/token values. The actual reinstall must be opt-in, idempotent, retain a private original backup without destroying any prior known-good copy, preserve other MCPs, and never change runtime/vendor/auth state.

## Execution milestones and definition of done

### Phase 1 — scoped implementation and offline contracts

- [x] Establish separate Codex TOML and Antigravity JSON adapters; no cross-role credential reuse.
- [x] Expose a read-only preview and explicit reinstall control in both provider menus.
- [x] Use the same per-provider config lock as the Playwright MCP writer.
- [x] Preserve non-Context7 provider configuration, back up original bytes, and reject invalid/ambiguous input.
- [x] Add regressions for nested TOML headers, displaced ownership comments, mixed LF/CRLF, authentication/symlink/FIFO rejection, idempotence and original backups.
- [ ] Audit Codex table scope against *real* malformed legacy input and adversarial TOML; the old exact-shape test is insufficient.
- [ ] Cover Antigravity global-vs-workspace duplicate name / plugin conflict and avoid falsely declaring end-to-end success.
- [ ] Prove full no-op behavior of both passive menu/Doctor paths (including malformed credential files and clean empty state).
- [ ] Review existing backup collision/overwrite behavior; preserve the ability to roll back multiple reinstall attempts safely.
- [ ] Ensure all Dockerfile image inventory, interpreter, permissions, static/unit/menu tests and smoke assertions pass on **the same SHA**.

### Phase 2 — review, merge and Edge publication (owner-approved order)

- [ ] Entire Build AMD64 CI **green at final PR head** (repository validation, smoke, notices, SBOM and vulnerability gate).
- [ ] Review all CodeRabbit findings, including out-of-diff, and resolve valid issues. A new review may identify more problems.
- [ ] Owner has explicitly authorized the integration-first path on 2026-11-13: **no dev candidate**; merge reviewed #324 to `main`, then separately rebase/re-generate and merge the upstream-update PR after its CI and review.
- [ ] Publish Edge from integrated `main` with the normal independent build/security gate; verify immutable digest and image provenance before the owner downloads and updates their TrueNAS installation.
- [ ] Keep `stable` and `latest` unchanged. Document the third-party hosted-service/privacy engineering evidence in #53; any unresolved independent legal assessment must remain explicitly labeled and cannot be claimed as approved.

### Phase 3 — TrueNAS acceptance after Edge publication

- [ ] Capture the previous Edge image digest plus independent encrypted/private backups before updating the user-approved TrueNAS stack.
- [ ] Record `remote-dev-version --check`, exact Edge source SHA and digest and both agent roles.
- [ ] Codex: preview scope, record private preimage hashes, explicitly reinstall Context7 only if safe, verify unrelated MCPs, API key, real Context7 tool call, Playwright and OpenAI Developer Docs, Doctor, idempotence and rollback.
- [ ] Antigravity: inspect global and workspace MCP conflicts, explicitly reinstall only eligible global Context7 entry (anonymous), verify a real `agy /mcp` tool call, Playwright, Doctor, idempotence and role isolation.
- [ ] Record PASS/FAIL/SKIP evidence in #95 and PR #324. A failing test is not a successful acceptance: fix in a subsequent PR and republish Edge after fresh CI.
- [ ] Never auto-install on startup or copy credentials between roles; preserve the rollback image and state.

### Phase 4 — close

- [ ] Mark the Context7 feature functionally accepted **only after** both agents' real-tool tests and recovery/rollback checks pass. Keep #95 open if Antigravity remains experimental or fails.
- [ ] Record third-party privacy and legal sign-off separately in #53; do not invent approval.
- [ ] Stable/latest still require a separate stable release process.

## Rollback and failure policy

Never delete another MCP entry to “fix” Context7. Preserve original config bytes and credentials before touching persistent state. If no clean scope exists, **FAIL CLOSED** and produce a meaningful but redacted diagnosis. A corrupt/absent optional Context7 integration must not break agent startup or silently trigger repair. A clean ping alone does not prove actual agent-side MCP usability.

## Verification sources

- Google Antigravity CLI MCP docs: https://antigravity.google/docs/mcp (global JSON `~/.gemini/config/mcp_config.json`, project `.agents/mcp_config.json`, `serverUrl`, Streamable HTTP and `/mcp`).
- Google Antigravity migration: https://antigravity.google/docs/cli/gcli-migration (modern `serverUrl`; legacy `url`/`httpUrl` not the migration target).
- Context7: https://context7.com/docs/resources/all-clients and https://context7.com/docs/resources/troubleshooting.
- #53 and #95 remain the authoritative project-specific legal/security review and implementation trackers.
