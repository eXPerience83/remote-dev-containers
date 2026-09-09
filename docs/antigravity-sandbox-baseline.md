# Antigravity terminal-sandbox baseline

This page records the supported Remote Dev position for Antigravity's vendor terminal sandbox on the current hardened TrueNAS/Docker deployment.

## Supported boundary

Remote Dev does **not** force or manage Antigravity's vendor terminal sandbox in the supported TrueNAS path. The supported service-isolation boundary is the hardened outer Antigravity role container plus the selected-project/Git boundary.

This is separate from Antigravity's approval policy. Approval prompts and autonomous operation control whether Antigravity asks before tool use; they are not a filesystem or kernel sandbox. Issue #159 owns approval/autonomy behavior.

## TrueNAS evidence — 2026-09-09

A controlled disposable test was run with Antigravity CLI **1.1.27** inside the existing hardened Antigravity service. The test did **not** change Compose, capabilities, seccomp, sysctls, mounts or persistent permission settings.

The outer container reported:

```text
NoNewPrivs: 1
Seccomp: 2
Seccomp_filters: 2
```

The kernel exposed user namespaces as enabled:

```text
kernel.unprivileged_userns_clone = 1
user.max_user_namespaces = 62105
```

but an effective in-container namespace probe failed:

```text
unshare -Ur true
unshare: unshare failed: Operation not permitted
```

Antigravity 1.1.27 exposes `--sandbox` as a launch-scoped terminal-sandbox option. The exact disposable launch was:

```text
REMOTE_DEV_PROJECT=agy-sandbox-test run-antigravity --sandbox
```

The Antigravity UI started successfully. On the first terminal tool invocation, however, Antigravity requested explicit **sandbox bypass** and warned that the command would execute outside the sandbox with full network and disk access. The bypass was rejected.

A follow-up request to execute only `pwd` inside the sandbox failed with:

```text
Encountered error in tool execution: fork/exec /root/.local/bin/agy: operation not permitted
```

No bypass permission was persisted, and the disposable Git project was removed after testing.

## Decision

For the current supported TrueNAS/Docker baseline:

- normal Remote Dev launches do not add `--sandbox`;
- Remote Dev does not require or manage `enableTerminalSandbox`;
- autonomous approval mode must not depend on `proceed-in-sandbox` or sandbox bypass;
- Remote Dev will not add `privileged`, `SYS_ADMIN`, unconfined profiles, host namespaces or similar weakening merely to make the nested vendor sandbox work;
- the hardened outer role container remains the supported service-isolation boundary;
- the completed #213 project/Git boundary remains a separate same-role project-safety boundary and is not sibling filesystem isolation.

This evidence is version-specific: it establishes the result for Antigravity CLI 1.1.27 under the tested hardened deployment. It does not claim that every future vendor version or every other container profile behaves identically.

## Future reconsideration

Nested Antigravity sandboxing is not part of the current roadmap/baseline. Any future reconsideration must be a focused security decision that re-tests the exact admitted vendor version on TrueNAS under the unchanged outer hardening profile and proves that no weakening of the outer boundary is required.

See also:

- `docs/security.md`
- `docs/architecture.md`
- issue #215 — documentation ownership/reconciliation
- issue #159 — Antigravity approval/autonomous mode
- issue #213 / PR #214 — project-collection Git boundary
- issue #36 — Codex no-Bubblewrap decision
