# Decision log

## D001 — no codex-universal base

Rejected as the default because its multi-version toolchains make the image unusually large. It remains a reference and possible future `full` variant.

## D002 — shared lightweight base

Accepted. Codex and a possible future Antigravity image can share identical base layers on the Docker host.

## D003 — root runtime

Accepted for v0.1. Simplicity and predictable permissions take priority, with strict host-mount and network boundaries.

## D004 — AMD64 first

Accepted. AMD64 is the only stable target until native ARM64 builds and smoke tests are available.

## D005 — GitHub CLI is essential

Accepted. Authentication, cloning, pull requests and Actions diagnostics are expected parts of the environment.

## D006 — image rebuilds replace r14-style mutation

Accepted. The image contains required common tools. Runtime scripts diagnose and configure credentials but do not perform broad package upgrades.
