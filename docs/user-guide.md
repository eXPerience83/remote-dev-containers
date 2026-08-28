# Remote Dev user guide

This guide covers normal day-to-day use **after Remote Dev is installed**. For the TrueNAS SCALE installation entry point, start from the [main README](../README.md#install-on-truenas-scale).

Remote Dev is still experimental. Codex is the reference agent. Antigravity remains an explicitly enabled experimental role, and its real TrueNAS project/session validation is tracked separately in [#131](https://github.com/eXPerience83/remote-dev-containers/issues/131).

## 1. Mental model

Each agent service owns a private workspace tree:

```text
Remote Dev role service
/workspace/                    <- project collection root
├── pollenlevels/              <- one project / exact path
├── remote-dev-containers/     <- another project / exact path
└── feature-worktree/          <- separate path even if it is the same Git repo
```

`/workspace` is the **collection root**, not the normal repository working directory. Before starting or resuming an agent, Remote Dev selects one validated direct child such as `/workspace/pollenlevels`.

Project selection changes the agent's default working directory; it is **not** filesystem isolation between sibling projects. The complete role-private `/workspace` mount remains available to processes in that agent container. Codex and Antigravity use different role-private workspace and state mounts, so do not assume that a project visible in one role exists in the other.

Agent authentication, configuration and session history live in the role-private persistent state, not inside the project checkout. Deleting or renaming a project therefore does not automatically delete the agent's historical session records.

## 2. Select, create or delete a project

The normal Codex flow is:

1. Open the Remote Dev launcher and then the Codex terminal.
2. Open **Projects...** from the Codex menu.
3. Select an existing project or create a new one.
4. After a successful selection or creation, Remote Dev returns to the Codex menu; verify the `Project:` line.
5. Choose **Start Codex** or **Resume a Codex session (current project)**.

Antigravity uses the same **Projects...** navigation contract: after a successful Select/Create action, Remote Dev returns to the Antigravity menu with that project active so you can choose **Start Antigravity** or **Continue latest Antigravity conversation (current project)**.

Cancelled, invalid or failed Select/Create actions stay in **Projects...** so you can retry or go Back deliberately. Delete also stays in **Projects...** after the operation so you can inspect or continue managing the remaining projects.

Project discovery is intentionally non-recursive:

- zero valid projects: Start/Resume is blocked until a project exists;
- exactly one valid project: it is selected automatically;
- multiple valid projects: choose one explicitly;
- the active selection belongs only to the current menu/tmux lifetime and is not written to a new global state file.

**Create project** creates one empty direct child of `/workspace`. It does not run `git init`, clone a repository or contact a remote service.

**Delete project** is destructive. Remote Dev shows the path and requires the exact project name before recursively deleting that directory. Commit, push or back up anything that must be retained first. Deleting a project does not delete Codex authentication or saved session history from `CODEX_HOME`.

Project names are limited to 1–128 ASCII characters: letters/digits plus `.`, `_` and `-`, beginning with a letter or digit. Traversal, slashes, leading-dot names and symlink project entries are rejected.

## 3. Codex sessions and Resume

The behavior below was validated on real TrueNAS with Codex `0.147.0`. The Resume picker is **Codex-native UI**, so newer optional runtimes can change labels or keys. When the TUI differs, its on-screen footer is the immediate source of truth.

Remote Dev launches **Resume a Codex session (current project)** with the selected project as Codex's explicit working directory. In the tested Codex picker:

- `[Cwd]` is the normal filter and shows sessions whose recorded cwd exactly matches the selected project path;
- multiple meaningful sessions for the same exact project path are retained and can appear together;
- switching Remote Dev projects changes the normal `[Cwd]` result set without deleting history;
- a brand-new session can have no useful preview until it contains a meaningful user message;
- `All` deliberately removes the cwd filter and can show sessions created from other paths;
- selecting a historical thread through `All` does not move its history into the project directory; Remote Dev still launches the resumed Codex process with the currently selected project as its working directory;
- exact paths matter, so two clones or worktrees of the same Git repository are separate normal `[Cwd]` scopes;
- renaming or deleting a project can leave historical sessions associated with the old path, normally discoverable through `All` rather than the new `[Cwd]` path.

Example:

```text
/workspace/pollenlevels
/workspace/remote-dev-containers
```

If `pollenlevels` is selected, `[Cwd]` normally shows only sessions recorded with cwd `/workspace/pollenlevels`. Switch the Remote Dev project to `remote-dev-containers` and `[Cwd]` shows that exact path's sessions instead. `All` can expose both sets.

### Resume picker controls

Tested native Codex `0.147.0` controls:

| Key | Tested behavior |
| --- | --- |
| `Tab` | Move focus between toolbar controls such as filter/sort. |
| Left / Right | Change the focused toolbar option, including `Cwd` / `All`. |
| Up / Down | Move through sessions. |
| `Enter` | Resume the selected session. |
| `Esc` | Leave the picker/start a new session according to the native screen. |
| `Ctrl+C` | Quit the picker. |

These are upstream Codex controls, not a Remote Dev keyboard protocol.

### Useful native Codex commands in 0.150.0

The bundled Codex `0.150.0` adds two useful TUI improvements. They are upstream Codex behavior rather than Remote Dev-specific commands, so a newer optional Codex runtime can evolve the exact UI.

- `/copy` opens a target picker for the latest assistant response. You can copy the full response, an individual fenced code block, or an individual blockquote. Code blocks are labelled by language, previews are shown, and copying an individual target preserves its source whitespace and nested quote Markdown. This is often more convenient than terminal/browser text selection when you only need one code block.
- Unnamed conversations now receive descriptive titles automatically. `/rename` opens an editable rename prompt and asynchronously suggests a title based on the recent substantive conversation; the suggestion is prefilled without overwriting text you have already started typing. A manual rename remains authoritative rather than being replaced later by the automatic title generator.

## 4. Browser terminal, tmux and the agent are different layers

```text
browser / ttyd  ->  tmux  ->  Codex TUI or shell
```

A browser disconnect is not necessarily a terminated development session. Remote Dev uses tmux so reconnecting to the same role endpoint can attach to the existing tmux-backed menu/session.

Inside the Remote Dev menu:

- leaving Codex returns control to the menu when the interactive action finishes;
- **Open a login shell** starts a general shell rather than an agent launch;
- **Exit this tmux session** terminates that tmux session instead of merely closing the browser tab.

The project selection is menu/tmux process state. A normal browser disconnect/reconnect to the same live tmux session can retain it. A full container/tmux recreation may start a new menu process and therefore require selecting the project again; that does not imply the project directories or agent history were lost.

### Current clipboard and mobile workarounds

Remote Dev now builds and serves a reproducible project-owned client derived from the exact ttyd 1.7.7 frontend. This is a compatibility and extension foundation only: the clipboard behavior tracked by #91 and mobile controls tracked by #90 have not landed. Until then, the provisional behavior recorded in [#87](https://github.com/eXPerience83/remote-dev-containers/issues/87) applies:

- plain `Ctrl+V` can be consumed by the active TUI; `Ctrl+Shift+V` worked as paste in the tested desktop environment;
- with tmux/TUI mouse handling, hold `Shift` while dragging to make normal browser/xterm text selections on the tested desktop path;
- copy shortcuts remain browser/OS/keyboard-layout dependent; Firefox can reserve `Ctrl+Shift+C` for Developer Tools;
- one Spanish-layout test copied with `Ctrl+AltGr+C`, but that is an observation, **not** the Remote Dev shortcut contract;
- Android users can temporarily need a keyboard that exposes terminal keys such as `Esc` and `Ctrl`.

Do not disable tmux mouse globally or add host/GUI clipboard bridges inside the container as a workaround.

## 5. Verify project instructions (`AGENTS.md`)

Remote Dev does not parse or own repository `AGENTS.md`. It starts Codex in the selected project so Codex can perform its normal upstream instruction discovery.

On the tested Codex `0.147.0`, the most useful verification is the native `/status` screen:

1. Select the intended Remote Dev project.
2. Start Codex.
3. Run `/status`.
4. Verify `Directory: /workspace/<project>`.
5. Verify the expected `Agents.md:` entry, for example `Agents.md: AGENTS.md` for a root-level file.

Do not copy private `AGENTS.md` contents into diagnostics merely to prove loading. The `/status` directory and instruction-source rows are better evidence than asking the model to self-report how the instructions arrived.

## 6. Project-local tools and virtual environments

Remote Dev supplies the general development substrate: for example Python, Node.js, `uv`, `mise`, Git and GitHub CLI. It intentionally does **not** globally bundle every repository-specific linter, test runner or package.

The project owns its dependency lock and environment. A Python `.venv` created below `/workspace/<project>` lives in that persistent project workspace. Whether `.venv` is ignored by Git is repository-specific and should be defined by that repository.

`uv sync` performs an exact synchronization by default. If a repository keeps tools in separate dependency groups, syncing only one group can remove packages that belong only to another group. That is project-environment behavior, not evidence that Remote Dev lost packages during container recreation.

A real validated example is `pollenlevels`, where Ruff is pinned only in the `lint` dependency group and the project has `default-groups = []`. The repository-owned sequence is therefore:

```bash
uv lock --check
uv sync --locked --only-group lint
uv run --locked --no-sync ruff check .
uv run --locked --no-sync ruff format --check .
```

`--no-sync` deliberately refuses to repair/install missing project dependencies. If a task explicitly forbids installs or network access, the agent should report a missing project tool rather than silently running `uv sync`.

Always follow the selected repository's own `AGENTS.md`, lockfile and CI commands instead of copying the `pollenlevels` example blindly.

## 7. What persists

Remote Dev separates persistent state by purpose:

- project directories persist through the role-private workspace bind mount;
- Codex authentication, configuration and session history persist through the Codex-private agent-state mount;
- GitHub CLI, Git and SSH state have separate role-private persistent mounts;
- an admitted optional Codex runtime has its own Codex-private runtime state;
- normal temporary files and uv/npm/pip caches persist below the role-private `/workspace/.remote-dev-tmp` tree;
- the active project selection itself is only current menu/tmux process state.

The container root filesystem is read-only. `/tmp` and `/run` remain private bounded tmpfs filesystems; `/tmp` is also `noexec`. Normal Codex and Antigravity sessions set `TMPDIR`, `TMP`, `TEMP`, and the uv/npm/pip cache variables to fixed children of `/workspace/.remote-dev-tmp`, keeping potentially large development workloads on the disk-backed private workspace. This hidden directory is not a project and is untrusted scratch, never trusted updater, admission, publication or credential staging. To clear it, stop that role service, delete `.remote-dev-tmp` from its host workspace and restart; startup recreates the fixed directories safely. Do not store credentials, configuration or project work in scratch or either transient tmpfs.

Recreating the container with the same reviewed mounts should therefore preserve the project directories and agent state while starting a fresh process. If a project is deleted, Codex history can still contain old-path sessions because that history is not stored in the deleted checkout.

## 8. Antigravity: current documented boundary

Antigravity remains experimental. The common behavior safe to rely on from the current Remote Dev implementation is the filesystem-selection contract plus the vendor-documented conversation entry points:

- the Antigravity role has its own private `/workspace` and state;
- select a concrete Remote Dev project before Start/Continue;
- Remote Dev launches every Antigravity action from the selected project cwd;
- **Start Antigravity** opens the normal TUI; use `/resume` there to browse/resume older conversations with Google's native picker;
- **Continue latest Antigravity conversation** passes the vendor-supported `--continue` flag and asks Antigravity to load the most recent conversation associated with that workspace;
- Remote Dev does not expose a separate conversation-browser action or parse Antigravity conversation storage/cache to build a competing picker;
- the menu conversation-entry paths no longer rely on rendered prompt text to decide when to inject `/resume`, because vendor TUI wording can change independently of the CLI contract.

Google documents that `--continue` can fall back to a fresh session when the workspace cache has no valid previous conversation. The in-TUI `/resume` picker remains the correct path when you need to choose among multiple or older conversations.

Do **not** infer Codex session filtering, preview visibility, thread/path reassociation or persistence semantics for Antigravity. Real TrueNAS project/session validation remains tracked in [#131](https://github.com/eXPerience83/remote-dev-containers/issues/131), with the wider experimental lifecycle tracked by #29/#106.

## 9. Quick troubleshooting

### `No sessions yet` after changing project

Check the Codex picker filter. `[Cwd]` is exact-path scoped; the selected project's path can legitimately have no sessions even though another project does.

### A session appears under `All` but not `[Cwd]`

Its recorded cwd differs from the current project's exact path. This is expected for other projects, worktrees, renamed paths and historical directories.

### Two clones of the same repository show different sessions

Codex's tested normal filter uses the exact cwd path, not Git remote identity. Different clone/worktree paths are different `[Cwd]` scopes.

### The project was renamed or deleted

The project checkout and Codex session history are separate state. Old-path history can remain visible under `All`; create/select the intended current project rather than assuming history was moved.

### A shell opens at `/workspace`

That is expected for the general shell mode. Agent Start/Resume selects a concrete `/workspace/<project>`; the shell is intentionally an operator shell at the collection root.

### The browser disconnected

Reconnect to the same role endpoint before assuming the tmux session ended. Closing a tab/network loss differs from choosing **Exit this tmux session** or recreating the container/tmux process.

### Copy/paste or Android keys are awkward

Use the provisional guidance above and [#87](https://github.com/eXPerience83/remote-dev-containers/issues/87). #90 and #91 own the future supported mobile-key and selection-copy behavior.

## Related documentation

- [README](../README.md) — installation, architecture summary and warnings.
- [Codex runtime updates](codex-runtime-updates.md) — optional official-runtime admission and fallback.
- [Context7 for Codex](context7-codex.md) — optional hosted MCP integration.
- [Security](security.md) — supported outer-container isolation boundary.
- [Release channels](releases.md) — `dev`, `edge`, `stable` and rollback.
- [Tool matrix](tool-matrix.md) — tools included in the image versus intentionally project-owned tooling.
