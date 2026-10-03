# Global agent guidance

Remote Dev keeps four responsibilities separate:

| Layer | Responsibility |
|---|---|
| Remote Dev environment | Mechanical defaults/enforcement: image tools on PATH, role-private state, inherited executable `$TMPDIR`, specific caches, read-only root and hardened `/tmp`. |
| Remote Dev global agent guidance | Brief cross-project behavior reminders through each provider's native global instructions. |
| Repository/directory instructions | More specific project commands, versions, environments and constraints; legitimate project conventions can refine the global guidance. |
| MCP/plugins | External capabilities and services, not environment policy. |

Guidance is neither a policy engine nor a security boundary. Container hardening remains independent of model obedience. It does not select/detect projects, activate `.venv`, source `.env`, install dependencies or change PATH. See the [tool contract](tool-matrix.md#project-toolchain-resolution).

## Source and lifecycle

The only authored rule is [`config/agent-rules/development-environment.md`](../config/agent-rules/development-environment.md), installed root-owned, mode `0444`, at `/usr/share/remote-dev/agent-rules/development-environment.md`. The immutable `/usr/local/bin/remote-dev-agent-guidance` helper derives both provider representations offline:

```text
remote-dev-agent-guidance reconcile codex
remote-dev-agent-guidance reconcile antigravity
remote-dev-agent-guidance status codex
remote-dev-agent-guidance status antigravity
```

The helper is limited to the matching container role. Existing `run-codex` / `run-antigravity` wrappers reconcile before a real new/resumed agent session, after runtime/project preflight and before vendor execution. Startup, Login shell, navigation, Doctor, help/version and policy inspection do not reconcile. Direct vendor CLI invocations bypass these managed launch wrappers.

Deleting an owned block/file restores the default on the next managed session; there is no separate opt-out setting. Image upgrades refresh the native representation on the next session. User/project instructions remain free to refine the guidance.

## Codex

The adapter follows Codex `rust-v0.160.0` global discovery: `$CODEX_HOME/AGENTS.override.md`, then `$CODEX_HOME/AGENTS.md`, first non-empty contents after native Unicode whitespace trimming. Global instructions precede repository/directory instructions. See [official AGENTS documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md) and [the pinned discovery implementation](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/codex-home/src/instructions/mod.rs).

Remote Dev owns only this bounded span, initially prepended before user-global content:

```text
<!-- BEGIN REMOTE DEV MANAGED DEVELOPMENT ENVIRONMENT -->
...canonical rule...
<!-- END REMOTE DEV MANAGED DEVELOPMENT ENVIRONMENT -->
```

Override activity is determined **after logically removing one valid owned block**. Real unowned instructions keep the override active. A whitespace-only override without a block is untouched. If only our block and user whitespace remain, the adapter removes only that block, preserves all remaining bytes, and manages `AGENTS.md`. With no active global file it creates/manages `AGENTS.md`, never activates an empty override. A newly added real override becomes the target without cleaning up the inactive base file.

Outside the span, user bytes (including comments/newlines/whitespace) are preserved. Valid owned spans update idempotently; duplicate, partial or malformed markers are conflicts. Invalid UTF-8, oversize, symlink, special, unsafe ownership/mode or ambiguous state is preserved and warned about. Codex skips a directory override and falls back on recoverable read errors: when this fallback is unambiguous, Remote Dev may manage the safe default but still reports `unsafe`. Readable symlinks and lossy/oversized inputs are not classified as inactive. No repository AGENTS file is modified.

## Antigravity

The dedicated rule is `/root/.gemini/config/rules/remote-dev-development-environment.md`, inside the existing private `state/antigravity/config` mount. It begins with:

```yaml
---
trigger: always_on
description: "Remote Dev development environment guidance"
---
```

Its body is the same canonical text inside the same ownership markers. The complete file is Remote Dev-owned only when exact frontmatter and one complete bounded block prove ownership; additional/unrecognized content is a conflict. Unowned exact-path collisions are never overwritten, renamed or deleted. `GEMINI.md`, `AGENTS.md`, `settings.json`, other rules and project files remain untouched.

This adapter targets the [native modular rule contract](https://www.antigravity.google/docs/rules/), not a literal Antigravity version. It adds no download or execution of a vendor candidate. No new mounts, shared mutable guidance state, broad HOME/XDG persistence or launcher access are introduced.

## Diagnostics and failures

Status and Doctor read only the matching role's state and never print private instruction/config contents. States are `current`, `missing`, `stale`, `unowned-conflict`, `unsafe`, `unsupported`. Missing/stale state is reconciled on the next managed agent session. Conflicts/unsafe state produce warnings and a degraded diagnostic exit status; they never block the provider solely because guidance could not be installed. Inspect such state manually; Remote Dev does not repair unowned/unsafe objects.

The helper uses bounded UTF-8 reads, non-symlink regular-file and ancestor checks, expected ownership/safe permissions, exact markers, private in-directory temporary files, target-identity rechecks, atomic replacement and fsync. New state uses files `0600` and directories `0700`; safe existing file owners and modes are preserved. The fixed native private mount roots may retain the operator's host UID at `0700`, as required by bootstrap; that owner is accepted only at/below that root. Custom Codex homes do not gain this exception, and other owners remain unsafe. These checks do not isolate guidance from a process already controlling the service user/container root.

## Supplemental behavioral acceptance

Deterministic CI tests the adapters and lifecycle offline with synthetic state, without model calls or vendor accounts. On one exact candidate, optionally exercise both managed providers using an already installed/admitted Antigravity runtime:

1. A synthetic Python project has pytest only in its `.venv`: observe explicit project-environment use.
2. Request an ad-hoc executable Python environment: observe inherited `$TMPDIR` use.
3. Request container validation with no Docker/backend: observe a missing-capability explanation rather than global installs or weakening isolation.

Record candidate revision/digest, admitted runtime identity and observations without private prompt/credential contents. These model-dependent observations supplement deterministic tests and do not gate CI. A future provider adapter must revalidate its native composition surface, preserve user content and reuse this canonical text in its own private state; no additional provider is implemented here.
