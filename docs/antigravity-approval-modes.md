# Antigravity approval modes

## Scope

Remote Dev exposes one approval-mode abstraction for Antigravity:

```text
autonomous | guarded
```

This changes only Antigravity's confirmation behavior inside the authority already available to the Antigravity role container. It does **not** create a filesystem sandbox, widen mounts/capabilities, or enable Antigravity's vendor terminal sandbox.

The supported isolation boundary remains the hardened outer role container plus the selected-project/Git boundary.

## Default and deployment configuration

The default is `autonomous`, matching the Remote Dev Codex UX.

Generic Compose may configure it with:

```dotenv
REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE=autonomous
# or: guarded
```

The TrueNAS reference YAML also defaults the Antigravity role to `autonomous`.

Mode resolution order is:

1. one launch `--approval-mode autonomous|guarded`;
2. `REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE`;
3. built-in default `autonomous`.

`run-antigravity --print-policy` reports the resolved mode and its source without running the vendor CLI or performing the full runtime-integrity check.

## Autonomous

For an autonomous managed launch, Remote Dev injects the reviewed Antigravity CLI 1.1.28 launch-scoped approval override:

```text
--dangerously-skip-permissions
```

Live TrueNAS validation for #159 established that this removes the normal per-tool and artifact-review stops for the launch, applies equally to Start and `--continue`, and leaves no autonomous approval state persisted afterward. A later managed guarded launch prompts again.

The wrapper owns this argument. Passing `--dangerously-skip-permissions` directly through `run-antigravity` is rejected so a caller cannot contradict the Remote Dev mode resolver.

Remote Dev does not additionally force `--mode=accept-edits`, `--mode=plan`, `--sandbox`, `toolPermission`, `artifactReviewPolicy` or `agentMode`.

Fine-grained vendor permission rules remain user-owned. In the validated 1.1.28 behavior, an explicit `permissions.deny` rule continued to block its matching command in autonomous mode.

## Guarded

Guarded mode omits the approval-bypass argument and uses normal vendor request/review behavior.

Remote Dev does not silently rewrite Antigravity's settings merely because guarded was selected. Before a guarded real launch, it performs a bounded offline compatibility check of only the reviewed top-level approval settings needed to guarantee that behavior.

Safe guarded states are the vendor defaults/absent values and the documented request/review values. Known persistent autonomous/incompatible values block the managed guarded launch instead of being silently ignored.

Fine-grained `permissions.allow`, `permissions.ask` and `permissions.deny` remain user-owned and are not rewritten by this compatibility check.

## Diagnostics

`remote-dev-doctor` remains read-only. For the Antigravity role it reports the effective Remote Dev approval mode plus sanitized guarded compatibility.

The dedicated offline helper is:

```bash
remote-dev-antigravity-policy status
```

It reads only the canonical Antigravity-private settings path and reports no OAuth/session data, project content or fine-grained rule contents.

A healthy result resembles:

```text
Antigravity guarded compatibility: OK (...)
```

A known conflicting persistent approval value is reported as `CONFLICT`. Malformed, unsafe or unknown relevant semantics are reported as `BLOCKED` and are not guessed or repaired automatically.

## Explicit guarded repair

A known repairable conflict can be reset explicitly with:

```bash
remote-dev-antigravity-policy repair-guarded --yes
```

This operation is never run automatically by Start, Continue, status or Doctor.

The repair is intentionally narrow:

- it accepts only the canonical regular root-owned private `settings.json`;
- it refuses symlinks, unsafe permissions, malformed JSON and unknown approval semantics;
- it removes only reviewed conflicting top-level `toolPermission` / `artifactReviewPolicy` overrides;
- it preserves unrelated/unknown settings and the complete fine-grained `permissions` object;
- it writes atomically in the same private settings directory with mode `0600`.

Removing those conflicting top-level overrides returns them to the vendor defaults instead of making Remote Dev the permanent owner of Antigravity's settings file.

## Menu behavior

The Antigravity menu shows the configured/effective approval policy and offers:

```text
Approval mode for next launch...
```

The one-launch selection is consumed by the next Start or Continue action and then resets to the configured deployment mode, matching the Codex menu contract.

Start and Continue use the same mode resolver; `Continue latest Antigravity conversation` still uses the vendor-supported `--continue` path.

## Sandbox distinction

Approval mode and the vendor terminal sandbox are separate controls.

The tested hardened TrueNAS baseline cannot use Antigravity's nested terminal sandbox without weakening the supported outer-container profile. #215 records that result. #159 therefore does not add `--sandbox`, persist sandbox bypass, or relax the container to make it work.

See also:

- `docs/antigravity-sandbox-baseline.md`;
- `docs/antigravity-runtime-admission.md`;
- `docs/security.md`.
