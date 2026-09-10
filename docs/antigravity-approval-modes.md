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

Live TrueNAS validation for #159 established that this removes the normal tool and artifact-review stops for that launch, works the same for Start and `--continue`, and leaves no autonomous approval state persisted afterward. A later launch without the bypass returns to normal vendor prompting.

The wrapper owns this bypass argument. Passing `--dangerously-skip-permissions` directly through `run-antigravity` is rejected so callers cannot silently contradict the Remote Dev mode resolver.

Remote Dev does not additionally enable `--sandbox`, persist approval defaults, or rewrite `settings.json`.

Fine-grained vendor permission rules remain user-owned. In the validated 1.1.28 behavior, an explicit `permissions.deny` rule still blocked its matching command even during an autonomous launch.

## Guarded

Guarded means Remote Dev does **not** add the global approval bypass. Antigravity's own permission and review configuration remains active.

The relevant persistent CLI file is:

```text
~/.gemini/antigravity-cli/settings.json
```

Before a real guarded launch, Remote Dev reads that file offline and checks only the small set of top-level values that can remove the expected protected behavior:

- `toolPermission` may be absent/default, `request-review`, or the more restrictive `strict`;
- `artifactReviewPolicy` may be absent/default or `asks-for-review`;
- `agentMode` may be absent/default, `default`, or `plan`.

Known globally permissive states such as `toolPermission=always-proceed`, `toolPermission=proceed-in-sandbox`, `artifactReviewPolicy=agent-decides`, `artifactReviewPolicy=always-proceed`, or `agentMode=accept-edits` are incompatible with the managed guarded promise and block the launch instead of being silently ignored.

Unknown or malformed values in those reviewed fields also fail closed because Remote Dev cannot guarantee what they mean.

### Advanced fine-grained rules

`permissions.allow`, `permissions.ask`, and `permissions.deny` remain entirely user-managed. Their presence is **not** treated as a guarded conflict and Remote Dev does not inspect or rewrite their contents.

That means an advanced user may intentionally allow specific safe operations while continuing to require confirmation for other operations. Guarded means the vendor permission engine is active and Remote Dev has not globally bypassed it; it does not mean Remote Dev erases explicit user permission exceptions.

This mirrors the Codex guarded contract, where explicit user policy allows may also avoid individual prompts.

## Diagnostics

`remote-dev-doctor` remains read-only. For the Antigravity role it reports the effective Remote Dev approval mode plus sanitized guarded compatibility.

The dedicated offline helper is:

```bash
remote-dev-antigravity-policy status
```

It reads only the canonical Antigravity CLI `settings.json` and reports the reviewed top-level mode values plus whether fine-grained rules are present. It does not print OAuth/session data, project content, or the contents of `permissions.allow/ask/deny`.

A healthy result resembles:

```text
Antigravity guarded compatibility: OK (...)
Antigravity guarded policy source: settings.json (read-only)
Antigravity fine-grained permissions: user-managed and preserved
```

An incompatible, malformed, unsafe, or unknown relevant state is reported as `BLOCKED`. Remote Dev does not repair or rewrite the file automatically or from Doctor.

Use Antigravity's own `/settings` or `/permissions` interfaces, or edit the vendor file deliberately, if you want to change that policy.

## Menu behavior

The Antigravity menu shows the configured/effective Remote Dev approval mode and offers:

```text
Approval mode for next launch...
```

The one-launch selection is consumed by the next Start or Continue action and then resets to the configured deployment mode, matching the Codex menu contract.

Start and Continue use the same resolver; `Continue latest Antigravity conversation` still uses the vendor-supported `--continue` path.

## Sandbox distinction

Approval mode and the vendor terminal sandbox are separate controls.

The tested hardened TrueNAS baseline cannot use Antigravity's nested terminal sandbox without weakening the supported outer-container profile. #215 records that result. #159 therefore does not add `--sandbox`, persist sandbox bypass, or relax the container to make it work.

See also:

- `docs/antigravity-sandbox-baseline.md`;
- `docs/antigravity-runtime-admission.md`;
- `docs/security.md`.
