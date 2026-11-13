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
| Persistent config | Role-private \`CODEX_HOME/config.toml\` | Role-private \`/root/.gemini/config/mcp_config.json\` |
| Provider MCP shape | TOML \`[mcp_servers.context7]\` with official HTTPS \`url\`, \`env_http_headers\`, \`enabled=true\`, \`required=false\` | JSON \`mcpServers.context7.serverUrl\` using Streamable HTTP |
| Credential behavior | Keep existing \`.remote-dev-context7/api-key\` in Codex-private state, never print or copy | Initially anonymous; **never** copy Codex key into Antigravity JSON; refuse to overwrite entries with user-managed authentication |
| Passive commands | \`status --menu\`, \`plan\`, Doctor | \`status --menu\`, \`plan\`, Doctor |
| Write operation | Explicit \`remote-dev-context7 reinstall --yes\` / Codex menu | Explicit \`remote-dev-context7-antigravity reinstall --yes\` / Antigravity menu |
| Live check | Explicit Context7 endpoint test plus real Codex MCP tool call | Explicit endpoint test plus actual \`agy /mcp\` and tool call |
| Concurrency | Shared directory flock with Playwright; snapshot check, private original backup, atomic replacement | Shared directory flock with Playwright JSON config provider; dirfd validation, private original backup, atomic replacement |
| Customization | Explicit reinstall resets **Context7-only** user adjustments, warn before confirmation; fail closed if scope is ambiguous | Credential-bearing or user-authored opaque server setups are never silently rewritten; explicit remediation needs separately reviewed auth policy |

Two distinct operations must remain clearly labeled:
- **Legacy repair** matches a narrow reviewed old format. If ineligible, do not try blind text patching.
- **Reinstall** isolates the whole Context7 MCP entry by provider-native config boundaries, validates a full proposed document before writing, and only then atomically replaces the registration with the image-reviewed contract.

**Provider-specific ownership:** For Codex, refuse malformed or ambiguous TOML table boundaries, duplicate ownership markers, or changes to any parsed value outside Context7. Preserve raw unrelated TOML bytes, including mixed line endings. For Antigravity, reject malformed JSON, duplicate keys, symlinks/FIFOs and credential-bearing custom entries; preserve non-Context7 JSON *values* (JSON formatting may be normalized) and back up original bytes. A workspace-level \`.agents/mcp_config.json\` or plugin-supplied MCP definition is **not** a global entry owned by Remote Dev; document the limitation and test for conflicts before claiming a live success.

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

### Phase 2 — review and publication gates

- [ ] Entire Build AMD64 CI **green at PR head** (repository validation, smoke, notices, SBOM and vulnerability gate).
- [ ] Independent CodeRabbit full review or documented manual security review if CodeRabbit is rate-limited; resolve valid notes including out-of-diff.
- [ ] Complete Antigravity-specific out-of-cycle hosted-service/terms/privacy/authentication interpretation under #53 before release. Existing #53 Antigravity CLI terms review is not automatic approval for this extra provider integration.
- [ ] Keep PR #324 draft until code and safety gates; do not merge during development.
- [ ] Explicitly authorize SHA-pinned **candidate/dev** workflow after review. It must publish the tested immutable candidate digest, **not edge/stable/latest**, and provide exact provenance. Any previous \`candidate-pr-324-49d93b60a5da\` belongs to the superseded legacy-only design.

### Phase 3 — TrueNAS acceptance (no production mutation without authorization)

- [ ] Deploy an isolated SHA/digest-pinned candidate to an appropriate test stack or user-approved controlled stack update; keep the prior digest and an independently protected state backup/rollback.
- [ ] Record \`remote-dev-version --check\`, exact candidate source SHA, digest, roles and container security settings.
- [ ] On Codex: run \`plan\` first, snapshot private config/key hashes, explicitly reinstall **only when eligible**, verify non-Context7 values and unrelated raw bytes, endpoint connectivity, real Context7 MCP tool lookup, Playwright/Developer Docs regression, Doctor and idempotence.
- [ ] On Antigravity: inspect existing global and workspace MCP states, explicitly reinstall only the isolated global Context7 entry, preserve other MCPs/auth/session state, verify \`agy /mcp\` and an actual documentation call, Playwright regression, Doctor and idempotence.
- [ ] Prove neither role can access the other's credentials or mutable state; starting a container must never self-install Context7. No vendor CLI runtime changes or automated image updates.
- [ ] Exercise rollback to the prior digest with preserved prior user config; confirm no credential leakage or altered other-MCP state.
- [ ] Record a sanitized PASS/FAIL/SKIP acceptance matrix and decision in #95/PR #324. No secrets, private TOML/JSON dumps or full private paths.

### Phase 4 — promote and close

- [ ] Only after approved acceptance: complete PR review, merge with fresh green checks, verify \`main\`, publish **edge** with independent build/security gate, and optionally update the user's Edge stack after explicit acceptance.
- [ ] Keep \`stable\` / \`latest\` unchanged pending independent stable release gates.
- [ ] Close #95 only when the Antigravity provider contract and legal gate are accepted. Record residual limitations (anonymous use, workspace overrides) in docs.
- [ ] Update dated evidence, decision records and roadmap without claiming CodeRabbit acceptance or Antigravity vendor endorsement.

## Rollback and failure policy

Never delete another MCP entry to “fix” Context7. Preserve original config bytes and credentials before touching persistent state. If no clean scope exists, **FAIL CLOSED** and produce a meaningful but redacted diagnosis. A corrupt/absent optional Context7 integration must not break agent startup or silently trigger repair. A clean ping alone does not prove actual agent-side MCP usability.

## Verification sources

- Google Antigravity CLI MCP docs: https://antigravity.google/docs/mcp (global JSON \`~/.gemini/config/mcp_config.json\`, project \`.agents/mcp_config.json\`, \`serverUrl\`, Streamable HTTP and \`/mcp\`).
- Google Antigravity migration: https://antigravity.google/docs/cli/gcli-migration (modern \`serverUrl\`; legacy \`url\`/\`httpUrl\` not the migration target).
- Context7: https://context7.com/docs/resources/all-clients and https://context7.com/docs/resources/troubleshooting.
- #53 and #95 remain the authoritative project-specific legal/security review and implementation trackers.
