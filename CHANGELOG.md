# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project intends to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once versioned releases begin.

## [Unreleased]

### Added

- Shared remote-development base built on Ubuntu 26.04 LTS.
- Browser-accessible Codex CLI environment using ttyd and persistent tmux sessions.
- Git, Git LFS, OpenSSH client and GitHub CLI.
- Python 3.14, Node.js 24 LTS, npm 12, uv and mise.
- AMD64 build, configuration validation and runtime smoke tests.
- Secure-by-default web startup guard requiring authentication unless explicitly overridden.
- SBOM, provenance, third-party notice and vulnerability outputs for built images.
- Public experimental `edge` images with commit-addressed tags and published digests.
- Persistent credential permission hardening for Codex, GitHub CLI, Git and SSH state.
- Embedded image channel and source revision metadata exposed by runtime commands.
- Accepted one-App, one-image, isolated-service architecture contract.
- Canonical role-neutral runtime commands and fixed `launcher`, `codex` and `shell` roles.
- Validated autonomous and guarded Codex approval modes with one-launch overrides.
- Canonical `remote-dev` image/package names with time-bounded image-name compatibility aliases.
- Stateless launcher with fixed Codex navigation, optional Basic authentication, origin checking, CSP, method restrictions and a secret-free health endpoint.
- Generic and TrueNAS two-service stacks reusing the same image reference.
- Canonical `REMOTE_DEV_DATA_ROOT` layout with separate `workspaces`, per-role `state` and `secrets` boundaries.
- Static Compose regressions for exact role-scoped mount targets, mount-free launcher behavior, missing-path failure and removal of the earlier experimental data-root names.

### Changed

- Migrated the effective base image from Ubuntu 24.04 to Ubuntu 26.04 LTS.
- Changed the edge channel from private validation to public experimental development testing.
- Changed generic and TrueNAS Compose defaults to the canonical `remote-dev` package through `REMOTE_DEV_IMAGE`.
- Retained `CODEX_IMAGE` and the `codex-remote-dev` package as lower-priority image-name aliases during `v0.1.x`.
- Removed system Bubblewrap from the default image after the TrueNAS outer-isolation decision.
- Changed Codex startup to disable the unsupported inner sandbox explicitly and use autonomous approvals by default, with guarded mode available.
- Changed compatibility commands into thin wrappers around role-neutral implementations.
- Changed the normal TrueNAS portal from the Codex terminal to the launcher while retaining independent Codex authentication.
- Changed the stateless launcher to require no password by default on trusted private endpoints; optional file-backed authentication remains available for generic Compose.
- Replaced the Codex-specific persistent directory contract with one clean role-neutral administrative root. No data-path alias, migration script, automatic copy, deletion or compatibility symlink is provided.
- Changed all persistent bind mounts to long syntax with `create_host_path: false`, so missing or mistyped host paths fail instead of being created silently.
- Moved the TrueNAS reference paths under `/mnt/Pool1/remote-dev`, separating Codex workspace, agent state, GitHub state, Git state, SSH state and the optional password file.
- Deferred optional SMB/ACL workspace integration and Windows/Git validation to issue #71.

### Security

- Web authentication remains required by default for agent terminals; the stateless launcher may be unauthenticated only on a trusted private endpoint.
- Optional launcher authentication uses a file-backed secret and is tested not to expose the password value in rendered Compose configuration.
- The launcher receives no agent workspace, state, GitHub CLI state, Git configuration, SSH state, password or container-engine socket.
- The supported Compose configuration avoids privileged mode, host networking, added capabilities and broad host mounts.
- The supported TrueNAS security boundary is each outer agent container; approval prompts are not a sandbox.
- The parent Remote Dev data root is never mounted wholesale. Each service receives only the specific child paths required by its role.
- Missing persistent directories now fail deployment rather than creating ambiguous root-owned paths.
- Agent credentials, GitHub state, Git configuration, SSH state and workspaces remain private per service.
- Optional proprietary agents remain unbundled and require explicit vendor-controlled installation after dedicated legal and package inspection.
- Downloaded release assets and GitHub Actions remain pinned and verified; fixable critical vulnerabilities block publication.
