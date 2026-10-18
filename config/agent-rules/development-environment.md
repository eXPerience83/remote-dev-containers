# Remote Dev development environment

- Use Remote Dev tools already available on normal PATH. Do not reinstall an image tool because a project-local command is missing.
- Respect the repository's declared environment, toolchain and pinned versions for project correctness. Use its Python virtual environment explicitly when that is the project contract.
- Use inherited `$TMPDIR` for ad-hoc executable environments and temporary development state; do not invent executable paths under hardened `/tmp`.
- The image provides Ruff, pytest, pre-commit, Mike Farah yq, shfmt and actionlint for local preflight. Use repository-owned versions and Python environments for final project validation; the bundled Python CLI environments do not supply project dependencies or plugins.
- Keep project dependencies out of immutable/global Python and global npm. Use the project's dependency mechanisms and inherited package-manager cache variables.
- Distinguish an image/global tool, a project-local dependency or environment, an explicitly selected extra toolchain, and an absent external capability or backend before reporting a missing tool.
- Do not weaken container hardening to make a tool work.
