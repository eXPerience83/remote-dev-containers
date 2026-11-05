# Security Policy

## Supported versions

The supported release scope for `v0.2.0` is a single-user, private-network AMD64 environment. `edge` remains experimental; a version is considered stable only after an exact-tag publisher builds, scans and promotes the reviewed digest. Security fixes are applied to `main` and relevant current published images; historical immutable digests are not silently updated.

## Reporting a vulnerability

Report suspected vulnerabilities through GitHub Private Vulnerability Reporting:

https://github.com/eXPerience83/remote-dev-containers/security/advisories/new

Do not open a public issue, pull request or discussion containing exploit details, credentials, tokens, private hostnames or infrastructure paths.

Include, where possible:

- the affected image tag or digest and source commit;
- the deployment configuration relevant to the issue;
- clear reproduction steps;
- the expected and observed behavior;
- the potential impact and any known mitigation;
- logs or screenshots with secrets and personal infrastructure details removed.

For general hardening guidance and the current threat model, see `docs/security.md`.
