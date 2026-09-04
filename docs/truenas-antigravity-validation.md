# TrueNAS experimental deployment and Antigravity validation

This runbook describes the **current** TrueNAS Custom App deployment/revalidation path for the experimental Remote Dev stack. It preserves the conclusions of the completed #29/#69/#131/#106/#158/#167/#186 validation work without presenting those closed issues as still-pending gates.

Current topology:

```text
Remote Dev stack
├── launcher      7680 — navigation only
├── codex         7681 — independently authenticated terminal
└── antigravity   7682 — optional/experimental independently authenticated terminal
```

Antigravity remains experimental by the recorded #53 support/policy decision, **not** because its lifecycle/browser-auth/admission validation is still pending. Do not expose ports 7680, 7681 or 7682 directly to the public Internet.

The selected image, `compose/truenas.yml` and every host-side helper used for layout/ACL validation must come from the same immutable source revision.

## Current browser-password contract

Remote Dev has one supported browser-terminal password runtime mechanism:

```text
WEB_PASSWORD
```

- **Codex:** configure its own non-empty `WEB_PASSWORD`.
- **Antigravity:** configure a different value; generic Compose maps `ANTIGRAVITY_WEB_PASSWORD` to that service's `WEB_PASSWORD`.
- **Optional authenticated launcher:** the generic launcher-auth override maps its distinct `LAUNCHER_PASSWORD` to the launcher's own `WEB_PASSWORD`.

The launcher receives no agent password.

`WEB_PASSWORD_FILE`, `/run/secrets/web_password`, browser-password Compose secrets and the old persistent password-file tree are retired. Browser passwords are deployment configuration, not part of the persistent data layout.

A privileged TrueNAS administrator can inspect App/container configuration and is inside Remote Dev's trust boundary. Never publish real password values, lengths, hashes or credential-derived metadata in validation evidence.

## What this runbook validates

When a change affects deployment/runtime behavior, this runbook can revalidate:

- launcher navigation on port 7680;
- Codex on independently authenticated port 7681;
- optional experimental Antigravity on independently authenticated port 7682;
- independent browser credentials and cross-rejection;
- intended common image identity across enabled roles;
- canonical role-private persistent paths;
- deterministic host bootstrap/preflight;
- the TrueNAS Generic/POSIX private-state ACL contract;
- read-only-root/capability/tmpfs/PID/shm hardening;
- project-scoped Start/Resume and persistent session/state behavior;
- stop/start and container recreation;
- isolation among launcher, Codex and Antigravity;
- Antigravity explicit vendor-runtime/admission/integrity behavior when the relevant change requires it.

SMB sharing remains separate under #71 and must never expose `state`. Stronger browser/remote access remains separate under #181.

## Preserve the existing deployment first

Before changing a real App:

1. save a sanitized copy of the current Custom App YAML;
2. record the current configured image reference, image ID and embedded source revision;
3. record the known-good immutable repository digest used for rollback;
4. keep the currently populated persistent tree intact;
5. do not delete or migrate state merely to exercise an empty-root bootstrap test.

If an empty-root acceptance test is needed, create a disposable administrator-owned **Generic/POSIX** dataset instead of emptying a production root.

Never dump complete container environments or credential files.

## Select and pin one complete release unit

Normal integrated validation uses:

```bash
validation_image=ghcr.io/experience83/remote-dev:edge-amd64
expected_revision=""
```

For an exact pre-merge gate, first publish the exact reviewed PR head through the owner-authorized candidate workflow, then use:

```bash
validation_image=ghcr.io/experience83/remote-dev:dev-amd64
expected_revision="REPLACE_WITH_PUBLISHED_FULL_PR_HEAD"
```

Pull the selected reference and read the embedded source revision:

```bash
sudo docker pull "$validation_image"

release_revision="$(
  sudo docker image inspect "$validation_image" \
    --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
)"
case "$release_revision" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "Invalid embedded source revision: $release_revision" >&2; exit 1 ;;
esac
if test -n "$expected_revision" && test "$release_revision" != "$expected_revision"; then
  echo "Selected image does not contain the expected candidate revision" >&2
  exit 1
fi
printf 'release_revision=%s\n' "$release_revision"
```

Record the immutable repository digest:

```bash
pinned_image="$(
  sudo docker image inspect "$validation_image" \
    --format '{{range .RepoDigests}}{{println .}}{{end}}' \
  | sed -n '1p'
)"
case "$pinned_image" in
  ghcr.io/experience83/remote-dev@sha256:[0-9a-f]*) ;;
  *) echo "Invalid immutable image reference: $pinned_image" >&2; exit 1 ;;
esac
printf 'pinned_image=%s\n' "$pinned_image"
```

Use `$pinned_image` in the validation YAML and obtain host-side files from `$release_revision`. Treat image, YAML and helpers as one release unit.

For normal edge builds, runtime diagnostics separate build identity from channel, for example:

```text
Image version: edge-YYYY.MM.DD-<7-char-sha>
Channel: edge
Source revision: <full source SHA>
```

The OCI digest and full source SHA remain stronger evidence than the dated label.

## Dataset and ACL boundary

Create/use one administrator-owned root dataset with the **Generic** preset / POSIX ACL model, for example:

```text
Pool1/remote-dev
```

normally mounted at:

```text
/mnt/Pool1/remote-dev
```

The normal deployment uses that one ZFS dataset plus ordinary `workspaces/` and `state/` descendants. An administrator may deliberately make a required descendant a child dataset for snapshots/quotas/replication; Remote Dev treats the existing mountpoint as an existing directory and bootstrap must not replace/chmod/chown its content.

The root must already exist. Remote Dev never creates a missing parent or ZFS dataset implicitly.

The reference ACL contract is documented in:

- `docs/truenas-acl-contract.md`
- `docs/truenas-acl-contract.es.md`

Real #186 validation showed that Apps-preset NFSv4 inheritance is not equivalent to the private-state Generic/POSIX contract even when simple mode bits display `0700`. Do not treat mode bits alone as proof of the host ACL policy.

## Download matching bootstrap, preflight and ACL audit

From the TrueNAS shell:

```bash
: "${release_revision:?Run the release verification section first}"
release_base="https://raw.githubusercontent.com/eXPerience83/remote-dev-containers/${release_revision}"
layout_release_dir="$(mktemp -d /tmp/remote-dev-layout.XXXXXX)"
install -d "$layout_release_dir/scripts/lib"

for release_path in \
  scripts/init-data-layout.py \
  scripts/preflight-data-layout.py \
  scripts/truenas-acl-audit.py \
  scripts/lib/data_layout.py
do
  curl --proto '=https' --tlsv1.2 \
    --fail --silent --show-error --location \
    "${release_base}/${release_path}" \
    --output "${layout_release_dir}/${release_path}"
done
```

For the reference YAML:

```bash
sudo python3 "$layout_release_dir/scripts/init-data-layout.py" \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity

sudo python3 "$layout_release_dir/scripts/preflight-data-layout.py" \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity

sudo python3 "$layout_release_dir/scripts/truenas-acl-audit.py" \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity
```

Expected successful summaries include:

```text
Remote Dev data-layout preflight: OK (/mnt/Pool1/remote-dev; Codex + Antigravity)
Remote Dev TrueNAS ACL audit: OK (Generic/POSIX private-state contract)
```

Run the initializer a second time and expect:

```text
Remote Dev data-layout bootstrap: no changes required
```

Bootstrap creates only missing canonical descendants, applies initial modes only to paths it creates, rejects symlink ancestry and never deletes/migrates/recursively chmods/chowns existing project/state contents. It creates no browser-password secret tree.

A normal reference tree is:

```text
/mnt/Pool1/remote-dev/
├── workspaces/
│   ├── codex/
│   └── antigravity/
└── state/
    ├── codex/
    │   ├── agent/
    │   ├── runtime/
    │   ├── gh/
    │   ├── git/
    │   └── ssh/
    └── antigravity/
        ├── bin/
        ├── runtime/
        ├── vendor/
        ├── config/
        ├── gh/
        ├── git/
        └── ssh/
```

Only the root dataset needs to appear in the normal TrueNAS Datasets UI. Ordinary descendants created by bootstrap are directories inside it.

## Download the matching TrueNAS YAML

Do not maintain a second hand-copied stack definition in this runbook:

```bash
: "${release_revision:?Run the release verification section first}"
release_base="https://raw.githubusercontent.com/eXPerience83/remote-dev-containers/${release_revision}"

curl --proto '=https' --tlsv1.2 \
  --fail --silent --show-error --location \
  "${release_base}/compose/truenas.yml" \
  --output /tmp/remote-dev-truenas.yml
```

Before saving the Custom App:

1. set the image reference to `$pinned_image` for exact validation;
2. replace every example bind IP with the trusted LAN/private-mesh address used by the host;
3. replace the root path if `/mnt/Pool1/remote-dev` is not correct for this host;
4. configure a strong Codex `WEB_PASSWORD`;
5. configure a **different** Antigravity `WEB_PASSWORD` when the role is retained;
6. keep personalized values out of Git and screenshots/evidence;
7. preserve `ipc: private`, `cap_drop: [ALL]`, the capability-free launcher and the exact reviewed agent `cap_add` lists;
8. do not add privileged mode, host/joined PID/network/IPC namespaces, broad host mounts or a Docker/Podman socket;
9. keep `REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY="1"` only when intentionally enabling the experimental role.

TrueNAS can rewrite formatting/comments/interpolation during Custom App save/edit. Validation must inspect the effective saved/rendered configuration; never assume comments or `${...}` expressions survived serialization.

The reference stack contains:

```text
remote-dev-launcher      port 7680, no persistent/agent mounts
codex-remote-dev         port 7681, Codex-only persistent mounts
antigravity-remote-dev   port 7682, Antigravity-only persistent mounts
```

## First deployment checks

After saving the App, keep the exact immutable reference in the shell:

```bash
: "${pinned_image:?Run the release verification section first}"

sudo docker ps --filter name=remote-dev --filter name=codex-remote-dev --filter name=antigravity-remote-dev
sudo docker exec codex-remote-dev remote-dev-version
sudo docker exec codex-remote-dev remote-dev-doctor
sudo docker exec antigravity-remote-dev remote-dev-version
sudo docker exec antigravity-remote-dev remote-dev-doctor
```

Confirm the embedded revision equals `release_revision` and all enabled containers use the intended common configured `$pinned_image`/image ID.

Inspect only sanitized hardening/mount facts:

```bash
expected_image_id=""
for container in remote-dev-launcher codex-remote-dev antigravity-remote-dev; do
  configured_image="$(sudo docker inspect "$container" --format '{{.Config.Image}}')"
  image_id="$(sudo docker inspect "$container" --format '{{.Image}}')"
  test "$configured_image" = "$pinned_image" || {
    echo "ERROR: $container configured image differs from pinned image" >&2
    exit 1
  }
  if test -z "$expected_image_id"; then
    expected_image_id="$image_id"
  else
    test "$image_id" = "$expected_image_id" || {
      echo "ERROR: role image IDs differ" >&2
      exit 1
    }
  fi
  sudo docker inspect "$container" --format \
    'configured_image={{.Config.Image}} image_id={{.Image}} user={{.Config.User}} readonly={{.HostConfig.ReadonlyRootfs}} privileged={{.HostConfig.Privileged}} pid={{.HostConfig.PidMode}} network={{.HostConfig.NetworkMode}} ipc={{.HostConfig.IpcMode}} pids={{.HostConfig.PidsLimit}} cap_drop={{json .HostConfig.CapDrop}} cap_add={{json .HostConfig.CapAdd}} groups={{json .HostConfig.GroupAdd}} tmpfs={{json .HostConfig.Tmpfs}} security={{json .HostConfig.SecurityOpt}}'
  sudo docker inspect "$container" --format \
    '{{range .Mounts}}{{println .Destination "<-" .Source "rw=" .RW}}{{end}}'
done
```

Do **not** dump complete environments.

## Hardening checklist

For a change that can affect container security, confirm on the exact candidate:

- launcher: UID/GID `65532`, read-only root, no restored capabilities, no supplementary groups, no persistent/agent mounts, PID limit `64`, reviewed private tmpfs values;
- Codex/Antigravity: read-only root, `no-new-privileges`, `cap_drop=[ALL]`, no supplementary groups, PID limit `1024` and only the exact reviewed `CHOWN,DAC_OVERRIDE,FOWNER,KILL,SETGID,SETUID` additions;
- all roles: `ipc=private`, no privileged mode, no host/joined PID/network namespace, no engine socket and no broad host mount;
- launcher navigation/origin/CSP/health remains secret-free;
- agent terminals retain origin checking, client limits and independent authentication;
- role-private writable mount sources remain disjoint;
- diagnostics continue to identify the outer container as the isolation boundary.

See `docs/security.md` for the authoritative exact tmpfs/capability contract instead of duplicating every parameter here.

## Browser checks

- Port 7680 opens the navigation-only launcher on the trusted private network.
- The Codex link opens port 7681 and requires the Codex credential.
- The experimental Antigravity link opens port 7682 and requires its separate credential.
- The Codex credential must not authenticate to Antigravity and vice versa.
- Credentials must not appear in launcher HTML, URLs, history, logs or evidence.

The focused #69 authentication/cross-role/recreation gate is already complete. Re-run it only when a new change can affect that contract.

## Codex checks

When affected by the candidate, exercise:

- project selection/create/delete safety;
- Start and Resume from a concrete `/workspace/<project>`;
- autonomous and guarded modes through the project-owned launcher;
- device-code login/session persistence if authentication/state handling changed;
- optional Codex runtime trust/fallback behavior if the updater changed;
- Context7 managed status/test/device-login only when the integration boundary changed.

Do not publish account identities, API keys, device codes or private repository names.

## Antigravity checks

Antigravity is already implemented and its #29/#106/#131 lifecycle evidence is complete. Re-run the relevant subset only when a new candidate touches that behavior.

Useful current checks:

1. inspect `remote-dev-antigravity status` and/or `remote-dev-doctor`;
2. if the runtime is absent and installation is part of the test, use the explicit installer and review the vendor/non-affiliation notice;
3. record version/trust state without publishing account details;
4. use official login only when the scenario requires it;
5. verify project-scoped Start and vendor-native conversation Resume/continue behavior when those paths changed;
6. verify `/root/.gemini/config` and vendor runtime/settings remain narrow Antigravity-private mounts;
7. stop/start or recreate the App if persistence is part of the change;
8. confirm Codex and launcher remain isolated and functional.

Supported sessions keep vendor automatic update disabled. Do not run Codex and Antigravity concurrently against the same writable checkout; the default deployment gives them separate workspaces.

The #96 admission model and #53 policy disposition are already complete. Antigravity remains experimental by deliberate support decision, not because additional generic TrueNAS lifecycle testing is pending.

## Development-scratch revalidation

The #158 disk-backed `.remote-dev-tmp` gate is completed evidence. Do not list it as pending.

If a later change touches scratch/tmp/cache routing, revalidate only the affected facts:

- `/tmp` stays the role-private bounded hardened tmpfs;
- normal agent `TMPDIR`/uv/npm/pip caches point into that role's `/workspace/.remote-dev-tmp` fixed children;
- scratch remains on the role-private workspace filesystem, not the `/tmp` tmpfs;
- Codex/Antigravity scratch is not shared and launcher has no workspace/scratch mount;
- trusted staging remains on its dedicated paths (`/run` or canonical private runtime state), never on untrusted development scratch;
- deleting one stopped role's scratch recreates only that role's fixed directories without changing another role.

## Stop/start and recreation

For a candidate that changes persistence/deployment behavior:

1. place existence-only synthetic markers in relevant role-private state categories;
2. stop/start the App;
3. confirm expected state remains;
4. recreate services with the same dataset/image reference;
5. rerun `remote-dev-version`, Doctor and the host ACL audit;
6. confirm launcher remains mount-free and agent mount sources remain disjoint;
7. resume a Codex session and, when Antigravity is enabled/affected, its selected project/conversation;
8. remove synthetic markers after recording sanitized pass/fail evidence.

Do not use real credential contents as markers.

## Retired password-file deployments

Do not recreate a persistent browser-password directory or mount a browser credential file into an agent/launcher container.

If an older installation still contains retired password files:

1. configure and verify the replacement per-service `WEB_PASSWORD` values;
2. exercise stop/start or recreation;
3. retain any legacy copy only for an explicit rollback window;
4. remove obsolete files manually once migration is accepted.

Remote Dev does not automatically delete/migrate old credential files. A future secret-provider integration would require a new reviewed architecture rather than reviving the retired dual-path contract.

## Rollback

Keep the known-good immutable image reference and any data-layout/ACL migration backup until the new deployment passes its required gates.

For an image-only rollback where the persistent contract is compatible:

1. stop the current App;
2. restore the saved known-good YAML/image digest;
3. recreate services;
4. rerun matching diagnostics and host ACL audit before declaring recovery complete.

For a dataset ACL migration rollback, follow `docs/truenas-acl-contract.md`; restoring an NFSv4 backup dataset does **not** make it compliant merely because the dataset rename succeeds.

Never copy credentials casually between old/new trees and never delete the production persistent tree as part of routine validation.

## Completion evidence

Record sanitized evidence only:

- TrueNAS version and test date;
- exact image digest, channel/build identity and full embedded source revision;
- confirmation that image, YAML and host-side helper files came from the same revision;
- bootstrap/preflight/ACL-audit results when storage is in scope;
- confirmation that the root dataset existed before bootstrap;
- confirmation that bootstrap was idempotent and existing contents remained unchanged;
- common configured image identity plus disjoint role-private mount sources;
- relevant hardening inspect fields;
- confirmation that launcher has no agent mounts/password/socket;
- independent Codex/Antigravity authentication and cross-rejection when tested;
- Antigravity version/trust state when relevant, without account data;
- pass/fail for the specific Start/Resume/login/update/recreation behavior affected by the candidate;
- safe error messages and focused follow-up issue links if something fails.

Never post passwords, OAuth codes/URLs, tokens, cookies, API keys, account email, private repository names, conversation content or raw credential listings.
