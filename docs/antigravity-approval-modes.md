# Antigravity approval modes

## Scope

Remote Dev exposes the same high-level approval choice for Antigravity that it exposes for Codex:

```text
autonomous | guarded
```

This changes only confirmation behavior inside the authority already available to the Antigravity role container. It does **not** create a filesystem sandbox, widen mounts/capabilities, or enable Antigravity's vendor terminal sandbox.

The supported isolation boundary remains the hardened outer role container plus the selected-project/Git boundary.

## Default and deployment configuration

The default is `autonomous`, matching the Remote Dev Codex UX.

```dotenv
REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE=autonomous
# or: guarded
```

Mode resolution order is:

1. one-launch `--approval-mode autonomous|guarded`;
2. `REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE`;
3. built-in default `autonomous`.

`run-antigravity --print-policy` reports the resolved Remote Dev mode and a sanitized view of guarded compatibility without running the vendor CLI, contacting the network, or performing the full runtime-integrity check.

## Autonomous

For an autonomous managed launch, Remote Dev adds the Antigravity CLI launch-scoped approval bypass validated on 1.1.28:

```text
--dangerously-skip-permissions
```

Live TrueNAS validation for #159 established that this removes the normal tool and artifact-review stops for that launch, works the same for Start and `--continue`, and leaves no autonomous approval state persisted afterward. A later launch without the bypass returns to the vendor permission engine.

That behavioral evidence is exact-version evidence for Antigravity CLI 1.1.28. Under the separate #96 runtime-admission contract, a newer compatible official runtime may be runnable while its Remote Dev review is pending; that status does not extend the 1.1.28 behavioral claim. If a later vendor release changes approval semantics, the mapping must be revalidated rather than silently redefining these modes.

The wrapper owns this bypass argument. Passing `--dangerously-skip-permissions` directly through `run-antigravity` is rejected so callers cannot silently contradict the Remote Dev mode resolver.

Remote Dev does not additionally enable `--sandbox` or persist an autonomous approval preset into vendor settings.

Fine-grained vendor permission rules remain user-owned. In the validated 1.1.28 behavior, an explicit `permissions.deny` rule still blocked its matching command even during an autonomous launch.

## Guarded

Guarded means Remote Dev does **not** add the global approval bypass. Antigravity's own permission and review engine remains active.

The relevant persistent CLI file is:

```text
~/.gemini/antigravity-cli/settings.json
```

Remote Dev supports the two protected Antigravity tool-permission presets:

- `request-review` — recommended/default guarded preset;
- `strict` — more restrictive and prompts for all non-read tools.

These are **provider presets inside Guarded**, not additional Remote Dev launch modes. The high-level choice remains only `autonomous|guarded`.

Before a real guarded launch, Remote Dev reads `settings.json` offline and checks only the small set of top-level values that can remove the expected protected behavior:

- `toolPermission` may be absent (vendor default), `request-review`, or `strict`;
- `artifactReviewPolicy` may be absent (vendor default) or `asks-for-review`;
- `agentMode` may be absent (vendor default), `default`, or `plan`.

Known globally permissive states such as `toolPermission=always-proceed`, `toolPermission=proceed-in-sandbox`, `artifactReviewPolicy=agent-decides`, `artifactReviewPolicy=always-proceed`, or `agentMode=accept-edits` are incompatible with the managed guarded promise and block the launch instead of being silently ignored.

Unknown or malformed values in those reviewed fields also fail closed because Remote Dev cannot guarantee what they mean.

### Advanced fine-grained rules

`permissions.allow`, `permissions.ask`, and `permissions.deny` remain entirely user-managed. Their presence is **not** treated as a guarded conflict, and Remote Dev does not interpret or rewrite their contents.

An advanced user may therefore allow selected reads, commands, or other operations while still requiring confirmation or denying other operations. Guarded means the vendor permission engine is active and Remote Dev has not globally bypassed it; it does not mean Remote Dev erases explicit user permission exceptions.

This mirrors the Codex guarded contract, where explicit user policy allows may also avoid individual prompts.

## Configuring the Guarded preset

The Antigravity menu exposes an **Approval settings...** submenu. It keeps the one-launch Remote Dev mode selector and also allows the operator to select:

```text
Guarded preset: request-review (recommended)
Guarded preset: strict (more restrictive)
```

Selecting a Guarded preset is an explicit configuration action. It changes only `toolPermission`, setting it to the selected `request-review` or `strict` preset. Unrelated settings and the complete fine-grained `permissions` object are preserved.

The preset selector does not normalize other Antigravity approval fields. `artifactReviewPolicy` and `agentMode` must already be compatible with Guarded; if either is permissive, unknown, or malformed, the preset action refuses to write and asks the operator to adjust the vendor configuration first. Unknown or malformed existing `toolPermission` values are also refused rather than overwritten; known reviewed permissive `toolPermission` values may be replaced because selecting that field is the purpose of this action.

The same explicit action is available from the container shell:

```bash
remote-dev-antigravity-policy set-preset request-review
remote-dev-antigravity-policy set-preset strict
```

The write is private and same-directory atomic. Immediately before replacement, Remote Dev rechecks the settings snapshot it read; a detected change aborts the operation so the operator can retry. Normal Start, Continue, status, `--print-policy`, and Doctor never modify vendor policy.

## Diagnostics

`remote-dev-doctor` remains read-only. For the Antigravity role it reports the effective Remote Dev approval mode, the active Guarded preset, and sanitized guarded compatibility.

The dedicated offline helper is:

```bash
remote-dev-antigravity-policy status
```

It reads only the canonical Antigravity CLI `settings.json` and reports the reviewed top-level mode values plus whether fine-grained rules are present. It does not print OAuth/session data, project content, or the contents of `permissions.allow/ask/deny`.

A healthy result resembles:

```text
Antigravity guarded compatibility: OK (...)
Antigravity guarded preset: request-review
Antigravity guarded policy source: settings.json
Antigravity fine-grained permissions: user-managed and preserved
```

If `toolPermission` is absent, the preset is reported as `request-review (vendor default)`. An incompatible, malformed, unsafe, or unknown relevant state is reported as `BLOCKED` and a managed guarded launch is refused.

## Menu behavior

The Antigravity menu offers:

```text
Approval settings...
```

From that submenu the operator can select Autonomous or Guarded for the **next launch only**, and can explicitly configure the persistent Guarded `toolPermission` preset as described above.

The one-launch mode selection is consumed by the next Start or Continue action and then resets to the configured deployment mode, matching the Codex menu contract. Start and Continue use the same resolver; `Continue latest Antigravity conversation` still uses the vendor-supported `--continue` path.

## Sandbox distinction

Approval mode and the vendor terminal sandbox are separate controls.

The tested hardened TrueNAS baseline cannot use Antigravity's nested terminal sandbox without weakening the supported outer-container profile. #215 records that result. #159 therefore does not add `--sandbox`, persist sandbox bypass, or relax the container to make it work.

See also:

- `docs/antigravity-sandbox-baseline.md`;
- `docs/antigravity-runtime-admission.md`;
- `docs/security.md`.
