# Decision log

## D001 — no codex-universal base

Rejected as the default because its multi-version toolchains make the image unusually large. It remains a reference and possible future `full` variant.

## D002 — shared lightweight base

Superseded by D008. The original decision proposed separate Codex and possible Antigravity child images sharing base layers. The accepted target now uses one final image digest for all fixed service roles.

## D003 — root runtime

Accepted for v0.1. Simplicity and predictable permissions take priority, with strict host-mount and network boundaries.

## D004 — AMD64 first

Accepted. AMD64 is the only stable target until native ARM64 builds and smoke tests are available.

## D005 — GitHub CLI is essential

Accepted. Authentication, cloning, pull requests and Actions diagnostics are expected parts of the environment.

## D006 — image rebuilds replace r14-style mutation

Accepted. The image contains required common tools. Runtime scripts diagnose and configure credentials but do not perform broad package upgrades.

## D007 — latest Ubuntu LTS base

Accepted. The project targets Ubuntu 26.04 LTS and will track later Ubuntu LTS releases through tested migration pull requests. Floating tags such as `latest` are not used in reproducible builds. The effective pin in `versions.env` and the Dockerfile default must remain synchronized and are checked before every build.

## D008 — one final image and one user-installed stack

Accepted. A user deploys one Remote Dev App or Compose stack. The launcher and each enabled agent service reference the same final image digest with a fixed role. Docker reuses the immutable layers instead of building or storing an independent toolchain image per agent.

This rejects both a single container holding every agent's private state and several manually maintained TrueNAS Apps, one per agent.

## D009 — one isolated service per agent

Accepted. Codex, Antigravity and any future Claude integration run in separate services. Each agent service has its own workspace/worktree, authentication configuration, history, GitHub CLI state, Git configuration, SSH keys and integration credentials.

Separate authentication configuration does not imply that browser-password values must differ; current password strength/reuse policy is deferred. The parent data directory and broad home/tool directories are never mounted wholesale. Sharing a writable checkout between agents is not the default.

## D010 — the launcher is not a container control plane

Accepted. The launcher exposes the primary user entry point and routes only to fixed services declared by the stack. It receives neither the container-engine socket nor agent credentials and does not create privileged child containers dynamically.

## D011 — optional proprietary agents use explicit vendor-sourced installation

Accepted. Optional proprietary agents are installed or updated only by an explicit reviewed action from an official vendor-controlled source unless redistribution rights are confirmed and documented.

A missing optional agent is reported as unavailable and is never downloaded silently during normal startup. Claude Code remains a future path until a dedicated implementation and validation decision is made.

## D012 — outer containers are the supported TrueNAS isolation boundary

Accepted. The project does not weaken TrueNAS/Docker with privileged mode, `SYS_ADMIN`, unconfined profiles, host-root mounts or a container-engine socket to force a nested sandbox.

The default image omits system Bubblewrap and the supported Codex launcher explicitly disables the unsupported nested sandbox. Approval prompts do not replace the outer-container boundary.

## D013 — one configuration-backed browser password contract

Accepted. Protected browser-terminal endpoints use one runtime variable, `WEB_PASSWORD`, populated from a separate deployment configuration entry for each service so roles can be changed independently.

The former browser-password file/mount/secret mechanism is retired. A privileged TrueNAS/Docker administrator can inspect deployment configuration and is inside the product trust boundary; moving the same application password to another host file does not create administrator secrecy.

For the current pre-stable contract, a protected endpoint requires only a non-empty single-line password. Remote Dev does **not** enforce a minimum length, character-composition rule or cross-service uniqueness, and an operator may intentionally reuse the same value for Codex, Antigravity and optional launcher authentication. Any stronger password/access rule requires a future explicit browser-security decision rather than being inferred from separate configuration entries.

The launcher receives no agent password even when optional launcher Basic authentication is enabled.

## D014 — Antigravity remains an experimental official-CLI integration

Accepted after the #96 technical admission work and the dated human #53 policy/terms reconciliation.

Remote Dev may expose Antigravity as an optional **experimental** integration because it launches Google's official `agy` CLI inside the isolated Antigravity role rather than implementing an alternative Antigravity service protocol/client or reusing Google/Antigravity OAuth for another coding agent or service.

The support boundary is deliberately conservative:

- use only the reviewed official Google installer/runtime path;
- keep install/update explicit and user initiated;
- keep vendor automatic update disabled for supported sessions;
- do not redistribute Google proprietary installer/CLI bytes in the repository or image;
- keep credentials/runtime/state private to the Antigravity role;
- preserve the review-pending admission/integrity safeguards;
- retain non-affiliation and applicable vendor terms/privacy wording;
- never describe the project decision or review evidence as Google approval, certification, signing or endorsement.

A material change to vendor terms, FAQ, privacy/auth model, installer origin/behavior or official CLI guidance triggers a new out-of-cycle review under #53.

## D015 — release maturity and build identity are separate

Accepted. Human-facing channels are permanently ordered `dev -> edge -> stable = latest`.

An edge build may have a dated identity such as `edge-YYYY.MM.DD-<short-sha>`, but the separate channel remains `edge`; the full source SHA and OCI digest are stronger provenance. Stable publication continues to use exact SemVer and `latest` is only an alias of the same stable digest, never of `dev` or `edge`.

The repository's local development baseline may advance independently between stable releases. It is `0.1.1-dev` after the current documentation/state synchronization and does not create a stable release or replace edge's dated identity.
