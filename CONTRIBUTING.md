# Contributing

Thank you for helping improve Remote Dev Containers.

> [!IMPORTANT]
> This project is in active experimental development. There is no stable release yet, and compatibility, persistence paths and image contents may change before `v0.1.0`.

## Before opening a change

- Search existing pull requests and issues to avoid duplicate work.
- Keep changes focused. Large tool additions should start as an issue or design discussion.
- Never commit credentials, tokens, SSH keys, private infrastructure details or real host paths.
- Do not weaken the default security posture: no privileged mode, host networking, Docker socket mounts or unauthenticated public ttyd exposure.

## Development workflow

1. Create a branch from `main`.
2. Make the smallest coherent change.
3. Update documentation and `CHANGELOG.md` when behavior changes.
4. Run the relevant validation:

   ```bash
   make validate
   ./scripts/build-local.sh
   ```

5. Open a pull request using the repository template.
6. Address CI and CodeRabbit findings that are valid for the current implementation.

## Review expectations

Pull requests should explain:

- what changed and why;
- user, deployment or security impact;
- how the change was validated;
- whether image tags, persistent paths or rollback behavior changed.

CodeRabbit comments are advisory. CI, source review and manual testing remain authoritative.

## Image and release changes

- `edge` is a moving experimental channel.
- `sha-<commit>` tags identify the source commit but remain mutable registry tags.
- Use an image digest (`@sha256:<digest>`) for an immutable deployment reference.
- Stable publication is reserved for an exact `vMAJOR.MINOR.PATCH` tag after the promotion checklist in `docs/releases.md` is complete.

## Reporting security problems

Do not publish exploitable credentials or sensitive deployment details in a public issue. Use GitHub private vulnerability reporting when available; otherwise contact the maintainer privately before disclosing details.
