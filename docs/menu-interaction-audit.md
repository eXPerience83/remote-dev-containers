# Complete terminal-menu interaction audit (Codex / Antigravity / Shell)

Scope: issue #357, follow-up to the **actual TrueNAS Edge screenshots** showing a `y/N` Context7 test in Codex and typed `TEST` in Antigravity. This document covers the **end-to-end screen, prompt, cancellation, dispatch and return path**, not just label parity. It does not certify the native agent's MCP execution: that is a separate question (#355/#356, currently draft).

## Main and every nested path

| Level / visible key | Codex | Antigravity | Expected confirmation / return |
| --- | --- | --- | --- |
| Main 1 Start | `run-codex` in validated project | `run-antigravity` with `REMOTE_DEV_PROJECT` | Interactive agent, then harden and pause; no cross-provider fallback |
| Main 2 Resume/Continue | `run-codex resume` | `run-antigravity --continue` | Same return/hardening contract; different native CLI semantics |
| Main 3 Projects → 1 Select → project picker | Shared collection validation | Same implementation; role-private workspace | Picker shows **0 Back**; old N+1 alias is accepted; selected project returns to main |
| Main 3 → 2 Create | Shared project-safe create helper | Same | Read project name; on success select it and return to main; failures stay in Projects |
| Main 3 → 3 Delete → project picker | Shared project boundary and deletion | Same | Confirm by typing **exact project name**; return to Projects, including after success |
| Main 3 → 0 Back | No mutation | Same | Return to main; old Projects 4 alias accepted invisibly |
| Main 4 Approval → 1 Configured | One-launch override cleared | Same | No persistent write; returns to main |
| Main 4 → 2 Autonomous | One-launch override | Same | No persistent write; returns to main |
| Main 4 → 3 Guarded | Codex asks approval | AGY permission engine remains active | No persistent write; returns to main |
| Main 4 → 4/5 Guarded presets | Not available | Change vendor-owned persistent `toolPermission` | **y/N explicit confirmation**, cancel no settings writer; normal pause & return |
| Main 4 → 0 Back | No mode change | Same | Codex historic 4 / AGY historic 6 aliases retained |
| Main 5 Manage → 1 | Optional Codex update from official OpenAI release | AGY install **only if absent** | Native, provider-specific release and security checks; `y/N` vendor confirmation; harden on invocation |
| Main 5 → 2 | Optional Codex runtime removal/fallback | AGY update **only if installed/damaged** | Native `y/N`; no dispatch when status unknown or operation unavailable |
| Main 5 → 3 | Codex device-code sign-in | AGY native sign-in guidance only | Provider-specific; AGY screen does **not** log in or mutate state |
| Main 5 → 0 Back | No mutation | Same | Return to main |
| Main 6 MCP → 1 Context7 | Codex private manager | AGY private manager | Shared numbered submenu; specific credential ownership |
| Context7 → 1 Status and recovery diagnosis | Offline `status` and `plan` | Same | No network, no OAuth/key reads beyond safe status; Enter to return |
| Context7 → 2 Test hosted connection | Codex config + HTTP check | AGY config + HTTP check | **Same menu prompt `[y/N]`**, consent disclosures. Cancel means zero backend calls; affirmative calls provider's `test --yes` after confirmation, then hardening and pause |
| Context7 → 3 Authentication | Codex private API key/device-login choice | Native `agy /mcp` OAuth instructions | Provider-specific by design; no copying OAuth into config |
| Context7 → 4 Install/repair | Absent: Codex onboarding; repairable: scoped `reinstall --menu-safe` | Absent: native registration install; repairable: scoped `reinstall` | Native install authentication/disclosures retained. **Repairable** requires typed `REINSTALL` in both menus before `--yes`; unavailable/blocked states never mutate |
| Codex Context7 → 3/4 → authentication wizard | Device login / enter existing key / keep key / anonymous | AGY uses native `/mcp` instead | Codex wizard now shows **0 Cancel**, accepts historical 5 without side effects |
| Codex device login → official CLI version selector | Reviewed pinned version / latest official, review pending | No Remote Dev AGY equivalent | CLI version picker now shows **0 Cancel**; historical 3 still cancels. This is not a launch or credential adoption |
| Context7 → 5 Remove | Removes managed registration **and local key** | Removes managed registration, **not vendor OAuth** | Typed **`REMOVE`** in both menus before backend `--yes`; blocked states cannot remove |
| Context7 → 0 Back; MCP → 0 Back | No mutation | Same | Returns one level at a time |
| Main 7 Sign in to GitHub CLI | `gh auth login` and Git credential setup | Same | Native browser login; credentials remain in role-private state; harden |
| Main 8 Run diagnostics | Provider-sensitive Doctor | Same | Read-only diagnostic; pause, no confirmation/no extra writes |
| Main 9 Open container shell | `bash --login` | Same | Explicit shell, harden and pause after it exits |
| Main 0 Exit tmux | Exit | Exit | No logout/removal of credentials |
| Emergency Shell 1/2/3/0 | Shell / GitHub / Doctor / Exit | Role-neutral recovery menu | **0 Exit** visible, old 4 accepted invisibly; no agent integrations exposed |

## Policy and regression requirements

1. **Same risk, same UX:** network-only test = `[y/N]`; persistent Context7 removal or repair = typed `REMOVE` / `REINSTALL`; exact-name project deletion remains stronger, and provider-native logins remain provider-specific. A direct CLI invocation still has its own independent confirmation; the menu may pass `--yes` **only after menu consent**.
2. **No unexpected execution:** prompt cancellation, empty/invalid responses and Back must not invoke test, remove, repair, preset write, or credential replacement; no hardening invocation is required when no child operation ran.
3. **No wrong provider:** similar labels must resolve to the exact role-owned manager; Codex credentials are never sent to AGY, and AGY OAuth tokens are never inspected by the Codex manager.
4. **No false success:** menu handler prints the called command's real status and a pause. `Context7 /ping` is only an HTTP check, **not proof of live MCP tools**, which is separately tracked under #355.
5. **Provider/state safeguards:** safe project collection checks, blocked/unknown installation states, guarded compatibility and legitimate login differences remain intact.
6. **Test inventory:** `scripts/test-menu-parity.py` checks all nested menu definitions, risk prompts, EOF and provider isolation; `scripts/test-remote-dev-menu.sh` and `scripts/test-antigravity-menu.sh` execute positive/cancelled flows, and the existing project/runtime/context7 unit fixtures test the underlying managers. CI must not access live network or secrets.

**Acceptance limit:** Passing fixtures and viewing screenshots do not prove the vendor login, real agent tool invocation, persistent OAuth after recreation or patched Chromium. Those are separate tracked work items. Stable/latest and TrueNAS deployment are not altered by this audit.
