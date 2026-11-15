# Antigravity official CLI in a private remote terminal — evidence and policy

**Reviewed:** 2026-11-14 · **Code baseline:** [main `7598562309b93cc67a8dbcd86db062207c195e91`](https://github.com/eXPerience83/remote-dev-containers/tree/7598562309b93cc67a8dbcd86db062207c195e91) · **Owner decision:** retain optional/experimental Antigravity, documented in [#53](https://github.com/eXPerience83/remote-dev-containers/issues/53). This is a project interpretation, **not** Google approval or legal advice.

[Versión española](antigravity-remote-terminal-policy.es.md)

## Decision and exact scope

Keep the **official interactive `agy` TUI** available in the isolated Antigravity role, with explicit opt-in, private user-initiated installation, and unchanged security, vendor-account and non-affiliation boundaries. This does **not** certify the environment as an officially Google-approved third-party application; the broad Antigravity additional terms remain applicable.

The supported Remote Dev pattern is a **single-user, privately accessed remote terminal** in which the account holder interacts with Google's own CLI. It must not be broadened by inference to using consumer Antigravity OAuth as a model backend for Codex, Claude, OpenClaw or other third-party agents, multiplexing accounts for third parties, automating consumer account rotation, or exposing a public shared model gateway.

## Source hierarchy — what the provider actually says

| Source | Direct evidence | Limitation |
| --- | --- | --- |
| [Antigravity Additional Terms, §6](https://antigravity.google/terms) | Third-party software/tools/services used to access the Antigravity service are restricted, with OpenClaw + Antigravity OAuth as an example; suspension or termination is possible. | **Not only a redistribution clause.** Does not separately classify a web terminal transporting the official interactive CLI. |
| [Antigravity FAQ: third-party login and headless](https://antigravity.google/docs/faq) | Third-party coding-agent/application wrapping of `agy` is unsupported on consumer plans; direct `agy -p` scripting/CI is differentiated. | No categorical exception is given for Remote Dev's menus; do not equate all terminal multiplexers with an external AI agent either. |
| [CLI settings: visual rendering](https://antigravity.google/docs/settings?tab=cli) | Google's official TUI documents remote SSH sessions, `tmux` and `screen` as expected terminal environments. | Not an explicit certification of our `ttyd` browser frontend. |
| [CLI authentication](https://antigravity.google/docs/install) | The official CLI supports remote authentication workflows. | Account session and model access must remain under Google's CLI and terms. |
| [Google AI Developers Forum, 12–13 Nov 2026](https://discuss.ai.google.dev/t/tos-violation-appeal-request/199917) | A user described `agy` interactive over SSH inside Linux Docker. A forum reply explicitly said this **interactive SSH/container pattern is supported**. | The user had received a ToS enforcement notice; the reply did not resolve their appeal. Forum replies are not a contractual waiver or guarantee against false positives. |
| [Google AI Developers Forum, PackStart, 28 Oct 2026](https://discuss.ai.google.dev/t/request-for-approval-free-desktop-app-that-brings-non-technical-users-to-gemini-with-their-own-google-plan/196378) | A separate desktop AI assistant launched `agy` as the engine for its **own** assistant. The reply rejected third-party desktop-app **wrapping or launching** even with an official binary and no token extraction. | Its delegated-assistant architecture differs from direct interaction with the vendor TUI; that factual distinction is **not** an express contractual exemption for all terminal frontends. |

**Project interpretation, not a provider rule:** the direct interactive terminal path is materially different from another application's assistant delegating work to `agy`. However, the PackStart reply also used broad language about third-party applications **launching** the CLI, and §6 does not exempt a browser terminal or launcher by name. Docker/SSH/browser transport alone does not settle classification. The provider's broad §6 means there is **residual classification and account-enforcement risk**. A direct vendor statement covering our particular browser terminal would be stronger than reasoning by analogy. No such statement has been verified.

## Audited product data flow (not a model proxy)

```text
Browser ── terminal keystrokes / display / resize ──> ttyd WebSocket
                                                   │
                                                local PTY
                                                   │
                                           tmux terminal session
                                                   │
                                    official interactive agy binary
                                                   │
                                    provider-managed Google service
```

The terminal arrows are **bidirectional**: `ttyd` carries terminal input *and* output, and its terminal endpoint can technically observe session I/O. Authentication and origin enforcement are **deployment-dependent**: `ALLOW_INSECURE_WEB=1` permits launching without a `WEB_PASSWORD`, and `WEB_CHECK_ORIGIN=0` skips `--check-origin`. An endpoint with either protection disabled needs independent access/security controls (for example, a trusted private network and authenticated gateway); do not assume the `ttyd` service authenticates and checks origins unconditionally. `ttyd` does not implement an Antigravity backend client, issue AI prompts to Google itself, or substitute for the vendor's transport. The `agy` process establishes its **own** vendor network connections. This is a **source-code architecture review**, not a TrueNAS packet-capture assertion.

### Exact code evidence (pinned source)

1. [Web terminal startup](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/start-remote-dev-web.sh#L82-L127): starts `ttyd --writable`, **conditionally** enables web credentials and origin checking according to deployment settings, and launches `attach-remote-dev-tmux`, **not** an Antigravity API endpoint.
2. [tmux attachment](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/attach-remote-dev-tmux.sh#L24-L92): creates or attaches the role's local `tmux` session, containing the menu or `run-antigravity`.
3. [Interactive menu](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/remote-dev-menu.sh#L973-L1024): Start/Continue/Projects, explicit Install/Update and provider configuration — control of **local** process lifecycle.
4. [CLI launch](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/run-antigravity.sh#L185-L205) and [exec/wait](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/run-antigravity.sh#L418-L463): verifies the manifest/hash and invokes `"$binary" ... <&0` as the real vendor TUI, preserving terminal interaction. The project supplies optional launch flags, but **does not** act as an alternative language model.
5. [Official installer](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/lib/antigravity-runtime/installer.sh#L1-L106) and [user-triggered admission](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/lib/antigravity-runtime/commands.sh#L15-L105): user requests installation; **Remote Dev's installer manager actually downloads, validates and executes Google's installer on the user's behalf**. It is inaccurate to say Remote Dev merely displays a link. No proprietary bytes are pre-bundled in the public image.
6. [Private TrueNAS volumes](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/compose/truenas.yml#L162-L239): separate role and persistent `/root/.local/bin`, runtime and vendor directories, not an image layer.
7. [OAuth helper: pane capture](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/remote-dev-antigravity-oauth.py#L95-L131), [watch](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/remote-dev-antigravity-oauth.py#L283-L299) and [popup rendering](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/remote-dev-antigravity-oauth.py#L196-L216): reads the **authorization URL displayed by the official CLI** from the local terminal and temporarily presents it to the user. It does **not** exchange authorization codes, read/reuse stored vendor tokens or authenticate Codex as Antigravity. Do not overstate this as 'no OAuth-related handling at all'.
8. [Local session picker](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/scripts/remote-dev-antigravity-picker.py#L27-L85): sends the CLI's own `/resume` command into the pane; it does not compose a prompt for another coding agent.
9. [Browser asset scope](https://github.com/eXPerience83/remote-dev-containers/blob/7598562309b93cc67a8dbcd86db062207c195e91/web/ttyd-osc52/README.md): pinned ttyd client extended only for terminal clipboard OSC 52; no analytics, external endpoint or model proxy.

## Boundary to retain when changing the terminal client

A future ttyd upgrade or replacement (see [#97](https://github.com/eXPerience83/remote-dev-containers/issues/97) and [#174](https://github.com/eXPerience83/remote-dev-containers/issues/174)) remains a **terminal** only if it continues to transport local PTY input/output and resize/reconnect, without Google service API calls, OAuth/token relaying, delegated `agy -p` orchestration, external telemetry or a model-proxy service. Changing terminal transport alone is not equivalent to changing the agent or the provider access method.

A normal browser terminal may nonetheless see/display prompts in terminal I/O: protect endpoint access, and never claim terminal I/O is invisible to the local terminal host. Remote Dev installation and launch helpers are not completely passive; record their role accurately.

## Owner disposition (2026-11-14)

**Approved project support policy:** **retain Antigravity**, optional and experimental, for private human-directed use of the official interactive CLI. The owner's decision followed review of §6, FAQ, documented SSH/`tmux` usage, the specific Docker/SSH support reply, the contrary third-party-agent case, and the actual network/control architecture. The project accepts the residual ambiguity of a browser-based launcher and the possibility of suspension or termination of **Antigravity and/or Gemini CLI accounts** under [§6](https://antigravity.google/terms) if Google classifies a use as prohibited, **without claiming formal vendor permission**.

- Preserve explicit, user-requested official installation, runtime integrity and update gates (#96/#153), non-redistribution, private volumes, isolated OAuth and non-affiliation.
- Preserve that Codex and Antigravity are separate agents. Do **not** let Codex/other harnesses call Antigravity as their model backend or build consumer-OAuth proxy features.
- No newly imposed runtime disablement, forced reauthentication, switch to API-key/Claude, Docker rebuild or TrueNAS change follows this **documentation-only** policy decision.
- Re-review in [#53](https://github.com/eXPerience83/remote-dev-containers/issues/53) if the upstream terms/FAQ/installer/auth model materially changes, new terminal infrastructure alters the data flow, or Google clarifies the exact use. #53 stays open as standing maintenance. No blanket stable-release approval: [#95](https://github.com/eXPerience83/remote-dev-containers/issues/95) and [#320](https://github.com/eXPerience83/remote-dev-containers/issues/320) retain their technical gates.
- The `reviewed_on` field in `third_party/inventory.json` refers to human review of **distributed image components**. Do not advance it merely because the owner decided this **optional-provider use policy**.

## Provider clarification (optional; not a shipping requirement of this decision)

Ask Google specifically whether a **single-user, private `ttyd`/`tmux` terminal displaying the official interactive TUI of a separately user-installed `agy` process** is treated like SSH access or like the prohibited third-party agent wrapping. State that launch menus and a local OAuth-URL popup exist. Do not imply Google has answered this precise question.
