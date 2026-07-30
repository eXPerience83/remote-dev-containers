# Optional proprietary and vendor-hosted agents

Reviewed: 2026-07-30

Remote Dev may provide project-owned installer, launcher or configuration helpers for optional agents, but those helpers do not change the upstream product's license, terms, privacy policy or account requirements.

## Binding distribution policy

For Antigravity CLI, Claude Code and similar future integrations:

1. The public repository and GHCR images must not contain the vendor binary or package unless redistribution rights are explicitly confirmed from an authoritative vendor source and recorded in this directory.
2. A public download URL, public GitHub repository or technically accessible installer does not by itself grant redistribution rights.
3. Installation must be an explicit user action and must download directly from a vendor-controlled endpoint using a reviewed vendor-supported method.
4. The launcher, image build and first container start must never download optional software silently.
5. The pre-install prompt must identify the vendor, source URL, executable destination, separate terms/privacy policies and the fact that Remote Dev is not affiliated with or endorsed by the vendor.
6. Vendor credentials and OAuth state must remain inside that agent service's private mounts. Project diagnostics must not print, inspect, export or reuse token contents.
7. The project must not replace the official client with an unofficial API client when the integration is intended to run the official CLI.
8. Telemetry and data-use behavior must be described from current vendor documentation without claiming stronger privacy than the vendor provides.
9. Uninstall must delete only files owned by that optional integration and must not remove shared runtimes, another agent's state or user workspaces.
10. Installer URLs, flags, terms, privacy disclosures, account requirements and state paths must be re-reviewed when the vendor changes its distribution method.

## Antigravity CLI

Status: **planned optional integration; not bundled and not currently supported by the image**.

Authoritative sources reviewed:

- official CLI overview: <https://antigravity.google/docs/cli-overview>
- official installation and authentication documentation: <https://antigravity.google/docs/cli-install>
- vendor installer endpoint for macOS/Linux: <https://antigravity.google/cli/install.sh>
- official product terms: <https://antigravity.google/terms>
- Google privacy policy: <https://policies.google.com/privacy>
- official public repository: <https://github.com/google-antigravity/antigravity-cli>

Current vendor-documented installation and state behavior:

- the official Linux/macOS command executes the Google-hosted installer and installs `agy` at `~/.local/bin/agy`;
- the documented installer flags are `--skip-aliases` and `--skip-path`; a future wrapper should use both so it does not rewrite persistent shell profiles or remove aliases outside the integration's owned state;
- CLI settings are documented under `~/.gemini/antigravity-cli/settings.json`;
- local authentication may use the operating system keyring, while remote/SSH sessions use a browser authorization URL and one-time code flow;
- `/logout` is documented as the supported way to purge saved authentication profiles from the upstream client;
- the Antigravity terms state that interaction and related usage data are collected while the service runs and may be used to improve Google and Alphabet products, with a settings choice affecting that use;
- the terms place responsibility on the user for agent actions, connected data and production supervision, and prohibit third-party software from using Antigravity OAuth as an unofficial service client.

Distribution decision:

- the official public repository did not expose a root `LICENSE` file at the review date;
- the product is governed by separate Google terms and privacy disclosures;
- a public installer endpoint is not evidence of redistribution permission;
- therefore Remote Dev must not copy the Antigravity binary into the immutable image, publish it in GHCR or describe it as open source or Apache-2.0;
- the future wrapper in #27 must download directly from Google only after explicit confirmation and must persist the installed executable and account state only in the isolated Antigravity service described by #28;
- before implementing #27, inspect the current installer and installed package in a disposable environment to record exact owned paths, embedded notices, checksums/signatures, update/uninstall behavior and any changed flags or telemetry controls.

Required user-facing notice before installation:

> Antigravity CLI is a Google product obtained directly from Google and is not distributed, licensed or endorsed by Remote Dev. Separate Google terms and privacy policies apply. The agent may read project files, contact external services and request permission to execute commands. Google documents collection and use of service interactions; review the current settings and terms before continuing.

## Claude Code

Status: **future compatibility path only; not bundled, installed, advertised or supported**.

Authoritative sources to re-review if #30 is activated:

- official setup documentation: <https://docs.anthropic.com/en/docs/claude-code/getting-started>
- official legal/compliance documentation: <https://docs.anthropic.com/en/docs/claude-code/legal-and-compliance>
- Anthropic privacy information: <https://www.anthropic.com/legal/privacy>
- applicable consumer or commercial terms for the account type used.

The current official installation options and legal terms may change before implementation. Do not add a Claude service, installer or binary merely because the neutral role contract reserves a future role name. A dedicated review must confirm account/subscription requirements, supported installation method, redistribution rights, authentication/state paths, telemetry/data use, update behavior, architecture support and trademark wording.

## External hosted integrations

An MCP server, plugin or documentation service may be open-source while the hosted service it contacts is governed by separate terms. Future Context7 work in #33 must distinguish:

- project-owned integration manager code;
- any open-source package actually redistributed;
- software downloaded later at the user's request;
- external hosted service terms, privacy behavior and credentials.

The project Apache-2.0 license applies only to Remote Dev project code, not to those separately supplied products or services.
