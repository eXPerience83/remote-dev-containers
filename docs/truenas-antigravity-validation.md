# TrueNAS experimental deployment and Antigravity validation

This runbook preserves and reuses the completed Antigravity lifecycle evidence from #29 while preparing the focused browser-authentication validation still owned by #69. Historical lifecycle steps remain documented here for reproducibility; they are not evidence that #29 is still open.
The image, `compose/truenas.yml` and `scripts/preflight-data-layout.py` must all
come from the same immutable source revision. Never combine a pinned image with
host-side files downloaded from a moving branch such as `main`.

The Antigravity lifecycle validation in #29 is complete, but Antigravity remains
experimental until the remaining support/security/documentation gates are
reconciled. Do not expose ports 7680, 7681 or 7682 directly to the Internet.

## Browser-password contract

Remote Dev now has one supported browser-password mechanism: a non-empty,
single-line `WEB_PASSWORD` in each authenticated endpoint's environment.

- **Codex:** configure `WEB_PASSWORD`.
- **Antigravity:** configure an independent value which the generic Compose
  maps from `ANTIGRAVITY_WEB_PASSWORD` to that service's `WEB_PASSWORD`.
- **Optional authenticated launcher:** the generic launcher-auth override maps
  `LAUNCHER_PASSWORD` to the launcher's `WEB_PASSWORD`.

The old file-backed terminal-password path is retired. Browser passwords are not
part of the persistent data layout and no browser-password file is mounted into
`/run`. A TrueNAS administrator can inspect environment-backed values through
the App YAML or container metadata, so this deployment model assumes a trusted
administrator and private host configuration.

## Scope and exclusions

This cycle validates:

- the navigation-only launcher on port 7680;
- Codex on independently authenticated port 7681;
- experimental Antigravity on independently authenticated port 7682;
- two independent terminal passwords;
- the canonical role-scoped persistent-data layout;
- install, login, stop/start and container recreation behavior;
- isolation between launcher, Codex and Antigravity.

SMB sharing, Windows access and TrueNAS ACL design are intentionally deferred to
issue #71. Do not create an SMB share for `state`.

## Preserve the current deployment

Before changing the App:

1. save a copy of the current custom-App YAML;
2. record the current image ID and embedded source revision;
3. leave the currently deployed legacy data tree untouched;
4. do not delete the old tree until the new deployment has passed recreation and
   rollback checks.

Example read-only inventory commands:

```bash
sudo docker inspect codex-remote-dev --format 'container_image_id={{.Image}} configured_image={{.Config.Image}}'
sudo docker exec codex-remote-dev remote-dev-version || true
sudo docker inspect codex-remote-dev --format '{{json .Mounts}}' | jq .
```

Never print password environment values or other credential contents.

## Verify and pin one complete release unit

Choose one channel reference for the whole validation. The normal integrated
path uses `edge-amd64`:

```bash
validation_image=ghcr.io/experience83/remote-dev:edge-amd64
expected_revision=""
```

For an exact pre-merge gate, first publish the exact current PR head using the
existing owner-authorized `/publish-candidate <full-head-sha>` workflow; do not
publish a candidate as part of an ordinary validation run. Then select
`ghcr.io/experience83/remote-dev:dev-amd64` instead, and record the published
full PR head as `expected_revision`. That candidate's embedded revision must
equal `expected_revision` before proceeding.

```bash
validation_image=ghcr.io/experience83/remote-dev:dev-amd64
expected_revision="REPLACE_WITH_PUBLISHED_FULL_PR_HEAD"
```

Pull the selected reference and read its embedded immutable source revision:

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

For a candidate path, compare `release_revision` with the recorded
`expected_revision` exactly; do not accept an older `dev-amd64` publication.

Record the immutable repository digest and keep it in the same shell session:

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

Use `$pinned_image` in the TrueNAS validation YAML. Download all host-side files
from `$release_revision`; the selected channel image, immutable digest and host
files must be updated together as one release unit.

## Dataset boundary

Create one TrueNAS dataset with the **Generic** preset and no SMB share:

```text
Pool1/remote-dev
```

The directories below are ordinary persistent subdirectories inside that one
ZFS dataset. Recreating the TrueNAS App or its containers does not remove them.
Additional child datasets are unnecessary unless a future SMB, ACL, quota,
snapshot or replication policy needs a separate boundary.

## Create the persistent directories

Run from the TrueNAS shell after the single dataset exists. These host
subdirectories are required before saving the Custom App because the canonical
YAML uses `create_host_path: false`; Compose must not create missing persistent
paths implicitly.

```bash
sudo install -d -m 0755 \
  /mnt/Pool1/remote-dev/workspaces/codex \
  /mnt/Pool1/remote-dev/workspaces/antigravity

sudo install -d -m 0700 \
  /mnt/Pool1/remote-dev/state/codex/agent \
  /mnt/Pool1/remote-dev/state/codex/runtime \
  /mnt/Pool1/remote-dev/state/codex/gh \
  /mnt/Pool1/remote-dev/state/codex/git \
  /mnt/Pool1/remote-dev/state/codex/ssh \
  /mnt/Pool1/remote-dev/state/antigravity/bin \
  /mnt/Pool1/remote-dev/state/antigravity/runtime \
  /mnt/Pool1/remote-dev/state/antigravity/vendor \
  /mnt/Pool1/remote-dev/state/antigravity/config \
  /mnt/Pool1/remote-dev/state/antigravity/gh \
  /mnt/Pool1/remote-dev/state/antigravity/git \
  /mnt/Pool1/remote-dev/state/antigravity/ssh
```

Do not create symlinks anywhere inside `/mnt/Pool1/remote-dev`.

The resulting host tree is:

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

`state/antigravity/config` is mounted only into the Antigravity service at
`/root/.gemini/config`. The official CLI uses its `projects/` child for
project-specific runtime configuration. This mount remains separate from
`state/antigravity/vendor -> /root/.gemini/antigravity-cli`; only these narrow
Antigravity-private paths are writable, and the container root filesystem
remains read-only.

## Download and run the matching host preflight

Download the preflight from the image's embedded source revision, not `main`:

```bash
: "${release_revision:?Run the release verification section first}"
release_base="https://raw.githubusercontent.com/eXPerience83/remote-dev-containers/${release_revision}"

curl --proto '=https' --tlsv1.2 \
  --fail --silent --show-error --location \
  "${release_base}/scripts/preflight-data-layout.py" \
  --output /tmp/remote-dev-preflight-data-layout.py

python3 /tmp/remote-dev-preflight-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity
```

Expected result:

```text
Remote Dev data-layout preflight: OK (/mnt/Pool1/remote-dev; Codex + Antigravity)
```

The preflight validates persistent bind sources and symlink ancestry only. The
actual browser passwords are validated by each runtime when the containers
start.

## Download the matching TrueNAS YAML

`compose/truenas.yml` is the canonical complete TrueNAS Custom App YAML. Do not
maintain a hand-copied second YAML in this runbook: download that file from the
same source revision as the image and preflight, then apply only the documented
site-specific substitutions below. This keeps future mount and hardening
changes in one source of truth.

```bash
: "${release_revision:?Run the release verification section first}"
release_base="https://raw.githubusercontent.com/eXPerience83/remote-dev-containers/${release_revision}"

curl --proto '=https' --tlsv1.2 \
  --fail --silent --show-error --location \
  "${release_base}/compose/truenas.yml" \
  --output /tmp/remote-dev-truenas.yml
```

Before pasting it into the TrueNAS Custom App editor:

1. replace the image anchor with `$pinned_image` recorded above;
2. replace all three example `192.168.1.10` bindings with the trusted LAN or
   Tailscale address already used by the deployment;
3. leave the launcher unauthenticated for the current trusted-network model;
4. replace the empty Codex `WEB_PASSWORD` value with a strong password;
5. replace the empty Antigravity `WEB_PASSWORD` value with a different strong
   password;
6. keep both values quoted and never commit the personalized YAML to Git;
7. preserve `ipc: private`, `cap_drop: [ALL]`, the capability-free launcher and
   the reviewed agent `cap_add` lists; do not add privileged mode, host or joined
   PID/network/IPC namespaces, host-root mounts or a Docker socket;
8. keep `REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY="1"` only for this controlled
   validation.

The resulting stack must contain exactly:

```text
remote-dev-launcher      port 7680, no mounts
codex-remote-dev         port 7681, Codex-only persistent mounts
antigravity-remote-dev   port 7682, Antigravity-only persistent mounts
```

## First deployment checks

After stopping the old App and saving the replacement YAML, verify that the
shell still contains the exact immutable reference used in the YAML:

```bash
: "${pinned_image:?Run the release verification section first}"

sudo docker ps --filter name=remote-dev --filter name=codex-remote-dev --filter name=antigravity-remote-dev
sudo docker exec codex-remote-dev remote-dev-version
sudo docker exec antigravity-remote-dev remote-dev-version
sudo docker exec antigravity-remote-dev remote-dev-doctor
```

Confirm the embedded revision matches `release_revision`, and that all three
containers use the same configured `$pinned_image` and image ID. The
Antigravity diagnostic should report its current admitted runtime state without
making the container unhealthy solely because the optional runtime is absent.

Inspect only redacted configuration facts and assert the configured immutable
reference, not only the local content-addressable image ID:

```bash
expected_image_id=""
for container in remote-dev-launcher codex-remote-dev antigravity-remote-dev; do
  echo "== $container =="
  configured_image="$(sudo docker inspect "$container" --format '{{.Config.Image}}')"
  image_id="$(sudo docker inspect "$container" --format '{{.Image}}')"
  if [[ "$configured_image" != "$pinned_image" ]]; then
    echo "ERROR: $container configured image does not match the selected pinned image" >&2
    exit 1
  fi
  if test -z "$expected_image_id"; then
    expected_image_id="$image_id"
  elif [[ "$image_id" != "$expected_image_id" ]]; then
    echo "ERROR: $container image ID differs from the first role image ID" >&2
    exit 1
  fi
  sudo docker inspect "$container" --format \
    'configured_image={{.Config.Image}} image_id={{.Image}} user={{.Config.User}} readonly={{.HostConfig.ReadonlyRootfs}} privileged={{.HostConfig.Privileged}} pid={{.HostConfig.PidMode}} network={{.HostConfig.NetworkMode}} ipc={{.HostConfig.IpcMode}} pids={{.HostConfig.PidsLimit}} cap_drop={{json .HostConfig.CapDrop}} cap_add={{json .HostConfig.CapAdd}} groups={{json .HostConfig.GroupAdd}} tmpfs={{json .HostConfig.Tmpfs}} security={{json .HostConfig.SecurityOpt}}'
  sudo docker inspect "$container" --format \
    '{{range .Mounts}}{{println .Destination "<-" .Source "rw=" .RW}}{{end}}'
done
```

Do not dump complete container environments. Verify only variable names when
needed.

## Hardening candidate checklist

Record sanitized facts only; do not infer success from an older image or a
different source revision.

- Record the TrueNAS version, test date, exact `expected_revision`,
  `$pinned_image` immutable repository digest and channel selected after
  publishing that exact head. Confirm the embedded revision equals the published
  head and launcher, Codex and Antigravity all use the same configured
  `$pinned_image` and image ID.
- Save the rendered/serialized App configuration and the inspect fields above.
  Confirm every role has a read-only root filesystem,
  `no-new-privileges:true`, `cap_drop=[ALL]`, no configured supplementary
  groups, no privileged or host/joined PID/network namespace, `ipc=private`, and
  no engine socket or broad mount.
- Confirm launcher runs directly as UID/GID `65532`, has no `cap_add`, PID limit
  `64`, `/tmp` at `rw,noexec,nosuid,nodev,size=64m,mode=1777` and `/run` at
  `rw,noexec,nosuid,nodev,size=16m,mode=755`. Confirm its HTTP process has no
  supplementary groups, zero effective capabilities and `NoNewPrivs: 1`.
- Confirm each agent has exactly
  `CHOWN,DAC_OVERRIDE,FOWNER,KILL,SETGID,SETUID`, PID limit `1024`, and `/tmp` at
  `rw,noexec,nosuid,nodev,size=512m,mode=1777`. Confirm Codex `/run` is
  `rw,exec,nosuid,nodev,size=1536m,mode=755` and Antigravity `/run` is
  `rw,noexec,nosuid,nodev,size=64m,mode=755`.
- Verify launcher navigation, its configured authentication mode, origin/CSP,
  GET/HEAD-only behavior and secret-free `/healthz`. Verify both agent terminals
  retain independent authentication, origin checking, client limits and
  role-specific credential-independent health. Confirm each role rejects the
  other role's synthetic browser credential during a controlled test.
- Exercise Codex autonomous (`danger-full-access` + `never`) and guarded
  (`danger-full-access` + launch-scoped untrusted trust for the active project)
  workflows. Confirm guarded prompts for commands except explicit exec-policy
  allows and is not merely trusted-project `on-request`. Record successful Start,
  Resume, Shell, login and doctor behavior, and confirm diagnostics still name
  the outer container as the boundary. Where Context7 is already configured,
  confirm that existing managed path remains functional without recording its
  key or account data.
- Record Antigravity's installed/review state, explicit launch, OAuth
  persistence, native in-TUI `/resume` conversation picker and `--continue`
  behavior. Confirm that `/root/.gemini/config/projects` can be created and
  remains separate from `/root/.gemini/antigravity-cli` while the root
  filesystem stays read-only. Antigravity remains experimental; a real account
  result must not be replaced with a synthetic claim.
- Place existence-only synthetic canaries in every role-private mount category.
  Stop/start and recreate launcher, Codex and Antigravity separately; after each
  recreation, repeat the mount/security inspection and confirm other-role
  canaries, health and private state are unchanged.
- Record no password, token, OAuth URL/code, account name, credential content or
  private repository name in the evidence.

## Issue #158 development-scratch candidate gate

This is a manual gate for one exact candidate image digest and embedded source
revision. Do not record it as passed until every check below has been observed on
the real TrueNAS deployment. Use only sanitized paths and filesystem facts; do
not dump a complete process environment.

1. Record the candidate digest and `remote-dev-version` revision. Confirm the
   launcher, Codex and Antigravity containers use that same image ID.
2. In each agent container, inspect `findmnt -T /tmp` and `df -h /tmp`. Confirm
   `/tmp` is still the private 512 MiB tmpfs mounted
   `rw,noexec,nosuid,nodev`. Confirm the launcher retains its existing smaller
   private tmpfs and has no `/workspace` mount.
3. Start a normal Codex session and a normal Antigravity session. Read only
   `TMPDIR`, `TMP`, `TEMP`, `UV_CACHE_DIR`, `NPM_CONFIG_CACHE` and
   `PIP_CACHE_DIR` from the session process. Confirm they resolve respectively
   to `tmp`, `uv-cache`, `npm-cache` and `pip-cache` below
   `/workspace/.remote-dev-tmp`.
4. For both agents, compare `stat -c '%d' /workspace
   /workspace/.remote-dev-tmp/tmp /tmp`. The workspace and scratch device IDs
   must match, while the `/tmp` device ID must differ. Confirm the five fixed
   scratch directories have the service UID/GID and mode `0700`.
5. Put distinct existence-only markers in the Codex and Antigravity scratch
   roots. Confirm neither marker is visible from the other role and neither is
   visible from the launcher. This must agree with the distinct host workspace
   sources reported by container inspection.
6. Run a representative uv resolution/install workload in the Codex session
   that previously pressured the 512 MiB tmpfs. Sample `du` for the fixed
   scratch tree and `df` for both its backing filesystem and `/tmp` before and
   after. Confirm temporary/cache growth occurs on workspace-backed storage and
   `/tmp` remains available for its intended small runtime uses. Do not add a
   synthetic oversized fixture to CI.
7. Re-run the fixed-path sensitive-operation checks: Codex updater staging must
   remain below `/run/remote-dev-codex-update`; Context7 device login must retain
   its private `/run` roots; Antigravity install/admission/publication must use
   canonical private runtime state; Context7 atomic writes must remain adjacent
   to their target; and Antigravity OAuth must retain its explicit small `/tmp`
   files. Do not include credentials or vendor login output in evidence.
8. Stop one agent service, delete only its `.remote-dev-tmp` host-workspace
   child, and restart it. Confirm the five fixed directories are safely
   recreated and the other role's marker remains unchanged. Restore or remove
   test markers after recording the result.

Expected result: large normal development temporary/cache activity is
disk-backed and role-private, while `/tmp`, launcher isolation and every reviewed
trusted-staging boundary remain unchanged. Candidate-specific evidence is
intentionally pending until a human performs this gate before merge.

## Browser checks

- Port 7680 opens the launcher without a password on the trusted network.
- The Codex link opens port 7681 and requires the Codex credential.
- The experimental Antigravity link opens port 7682 and requires the separate
  Antigravity credential.
- The Codex credential must not authenticate to Antigravity, and the Antigravity
  credential must not authenticate to Codex.
- Credentials never appear in launcher HTML, URLs or browser history.

## Antigravity lifecycle gate

Starting from the Antigravity menu:

1. inspect the current runtime/admission state;
2. if absent, run the explicit installer and review the vendor/non-affiliation
   notice;
3. record the installed version without publishing account details;
4. complete the official individual/free login flow when needed;
5. confirm `/root/.gemini/config/projects` is writable through only the narrow
   Antigravity config mount, and record filesystem changes as path names and
   metadata only;
6. run a disposable repository test when lifecycle evidence must be refreshed;
7. stop/start the App;
8. recreate all three containers with the same dataset;
9. confirm executable, login/settings behavior and workspace persistence;
10. verify Codex and launcher remain isolated and functional.

Do not run Codex and Antigravity concurrently against the same writable checkout.
The default deployment gives them separate workspaces.

## Retired password-file mode

Do not recreate a persistent browser-password directory or mount a browser
credential file into an agent or launcher container. #69 standardizes the
supported browser authentication contract on per-service environment values.
If an existing deployment still has retired browser-password files, configure
and verify the replacement `WEB_PASSWORD` values first, including stop/start or
recreation. Keep any legacy copy only for the explicit rollback window, then
remove the obsolete files manually after the migration is accepted. Remote Dev
does not delete or migrate those credential files automatically.
If a future secret-provider integration is desired, it must be designed and
reviewed as a new mechanism rather than reviving the retired dual-path contract.

## Rollback

If the new stack fails:

1. stop the new App;
2. restore the saved old YAML;
3. restore the previously recorded image reference if needed;
4. continue using the previously recorded legacy data tree;
5. leave `/mnt/Pool1/remote-dev` intact for diagnosis.

Do not copy credentials between old and new configurations and do not delete the
persistent tree during the validation cycle.

## Completion evidence

Keep related Antigravity lifecycle and password evidence linked to the owning
issues:

- TrueNAS version and test date;
- exact image digest and embedded revision;
- rendered and inspected hardening fields from the exact candidate;
- confirmation that YAML and preflight came from that same revision;
- confirmation that Codex and Antigravity used independent environment-backed
  browser passwords, without recording either value;
- Antigravity CLI version;
- browser/access method without account identity;
- pass/fail for install, login, stop/start and recreation when exercised;
- confirmed mount destinations and permission metadata;
- confirmation that the launcher has no mounts and runs as UID/GID `65532`
  without added capabilities;
- confirmation that Codex and Antigravity credentials are independent and
  cross-rejected;
- any safe error messages and follow-up issue links.

Never post passwords, OAuth codes, tokens, cookies, account email, private
repository names or raw credential listings.
