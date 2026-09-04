# TrueNAS experimental deployment and Antigravity validation

This runbook describes the **current** TrueNAS Custom App deployment/revalidation path for the experimental Remote Dev stack. It preserves the conclusions of the completed #29/#69/#131/#106/#158/#167/#186 validation work without presenting those closed issues as still-pending gates.

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

- **Codex:** configure its own non-empty value.
- **Antigravity:** configure a different value; generic Compose maps a distinct operator-facing value to that service's runtime password.
- **Optional authenticated launcher:** the generic launcher-auth override uses its own distinct launcher password.

The launcher receives no agent password. The former file-backed browser-password path is retired. Browser passwords are deployment configuration, not part of the persistent data layout.

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
- Antigravity explicit vendor-runtime/admission/integrity behavior when relevant.

SMB sharing remains separate under #71 and must never expose `state`. Stronger browser/remote access remains separate under #181.

## Preserve the existing deployment first

Before changing a real App:

1. save a sanitized copy of the current Custom App YAML;
2. record the current configured image reference, image ID and embedded source revision;
3. record the known-good immutable repository digest used for rollback;
4. keep the populated persistent tree intact;
5. do not delete or migrate state merely to exercise an empty-root bootstrap test.

If an empty-root acceptance test is needed, create a disposable administrator-owned **Generic/POSIX** dataset instead of emptying a production root. Never dump complete container environments or credential files.

## Select and pin one complete release unit

Normal integrated validation uses:

```bash
validation_image=ghcr.io/experience83/remote-dev:edge-amd64
expected_revision=""
```

For an exact pre-merge gate, publish the reviewed PR candidate first and use the corresponding `dev-amd64` image plus exact expected revision.

Pull the selected reference and read its embedded source revision:

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

A normal edge runtime identity separates build identity from channel:

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

The normal deployment uses that one ZFS dataset plus ordinary `workspaces/` and `state/` descendants. Deliberate child datasets remain valid for operator-defined snapshot/quota/replication boundaries.

The root must already exist. Remote Dev never creates a missing parent or ZFS dataset implicitly.

Real #186 validation showed that Apps-preset NFSv4 inheritance is not equivalent to the private-state Generic/POSIX contract even when simple mode bits display `0700`. Do not treat mode bits alone as proof of the host ACL policy.

See `docs/truenas-acl-contract.md` / `.es.md`.

## Download matching bootstrap, preflight and ACL audit

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

Run the initializer a second time and expect `no changes required`.

Bootstrap creates only missing canonical descendants, rejects symlink ancestry and never deletes/migrates/recursively rewrites existing project/state contents. It creates no browser-password secret tree.

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

## Download the matching TrueNAS YAML

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
2. replace every example bind IP with the trusted LAN/private-mesh address;
3. replace the root path if needed;
4. configure a strong Codex browser password;
5. configure a **different** Antigravity browser password when retained;
6. keep personalized values out of Git/screenshots/evidence;
7. preserve `ipc: private`, `cap_drop: [ALL]`, the capability-free launcher and exact reviewed agent capability lists;
8. do not add privileged mode, host/joined namespaces, broad host mounts or a Docker/Podman socket;
9. keep the experimental Antigravity role enabled only when intentionally testing/using it.

TrueNAS can rewrite formatting/comments/interpolation during Custom App save/edit. Validation must inspect the effective saved/rendered configuration.

## First deployment checks

```bash
: "${pinned_image:?Run the release verification section first}"

sudo docker ps --filter name=remote-dev --filter name=codex-remote-dev --filter name=antigravity-remote-dev
sudo docker exec codex-remote-dev remote-dev-version
sudo docker exec codex-remote-dev remote-dev-doctor
sudo docker exec antigravity-remote-dev remote-dev-version
sudo docker exec antigravity-remote-dev remote-dev-doctor
```

Confirm the embedded revision equals `release_revision` and all enabled containers use the intended common image reference/ID. Inspect only sanitized hardening/mount facts; do **not** dump complete environments.

## Hardening checklist

For changes that can affect container security, confirm:

- launcher: UID/GID `65532`, read-only root, no restored capabilities, no supplementary groups, no persistent/agent mounts, PID limit `64`;
- Codex/Antigravity: read-only root, `no-new-privileges`, `cap_drop=[ALL]`, no supplementary groups, PID limit `1024` and only the exact reviewed agent capability additions;
- all roles: private IPC, no privileged mode, no host/joined namespaces, no engine socket and no broad host mount;
- launcher navigation/origin/CSP/health remains secret-free;
- agent terminals retain independent authentication;
- writable mount sources remain disjoint;
- diagnostics continue to identify the outer container as the isolation boundary.

See `docs/security.md` for exact current parameters.

## Browser checks

- Port 7680 opens the navigation-only launcher on the trusted private network.
- Codex opens port 7681 and requires its credential.
- Antigravity opens port 7682 and requires its separate credential.
- The Codex credential must not authenticate to Antigravity and vice versa.
- Credentials must not appear in launcher HTML, URLs, history, logs or evidence.

The focused #69 authentication/cross-role/recreation gate is already complete. Re-run it only when a new change can affect that contract.

## Codex checks

When affected, exercise project selection/create/delete safety, project-scoped Start/Resume, autonomous/guarded launch behavior, login/session persistence, optional runtime trust/fallback and Context7 only when the candidate changes those boundaries.

## Antigravity checks

Antigravity's #29/#106/#131 lifecycle evidence is complete. Re-run the relevant subset only when a new candidate touches that behavior.

Useful checks include status/Doctor, explicit install when in scope, version/trust state, official login when required, project-scoped Start/Resume, narrow private state mounts, stop/start/recreation and verification that Codex/launcher remain isolated.

Supported sessions keep vendor automatic update disabled. Do not run Codex and Antigravity concurrently against the same writable checkout.

The #96 admission model and #53 policy disposition are complete. Antigravity remains experimental by deliberate support decision, not because generic TrueNAS lifecycle testing is pending.

## Development-scratch revalidation

The #158 disk-backed scratch gate is completed evidence. Re-run only if scratch/tmp/cache routing changes. Preserve bounded `/tmp`, role-private workspace-backed development scratch, separation across agents and dedicated trusted staging paths.

## Stop/start and recreation

For a candidate affecting persistence/deployment behavior:

1. place existence-only synthetic markers in relevant role-private state;
2. stop/start the App;
3. confirm expected state remains;
4. recreate services with the same dataset/image reference;
5. rerun diagnostics and host ACL audit;
6. confirm launcher remains mount-free and agent mount sources remain disjoint;
7. resume relevant sessions;
8. remove synthetic markers after sanitized evidence is recorded.

Do not use real credential contents as markers.

## Rollback

Keep the known-good immutable image reference and any data-layout/ACL migration backup until the new deployment passes its required gates.

For image-only rollback where the persistent contract is compatible, restore the known-good YAML/image digest, recreate services and rerun matching diagnostics/ACL audit. For ACL migration rollback, follow `docs/truenas-acl-contract.md`.

Never copy credentials casually between old/new trees and never delete production persistent data as routine validation.

## Completion evidence

Record sanitized evidence only: TrueNAS version/date, exact image digest/channel/build identity/full source revision, same-revision helper confirmation, bootstrap/preflight/ACL results when in scope, common image identity plus disjoint mounts, relevant hardening facts, launcher isolation, independent authentication, Antigravity version/trust state when relevant and pass/fail for the specific lifecycle behavior affected by the candidate.

Never post passwords, OAuth codes/URLs, tokens, cookies, API keys, account email, private repository names, conversation content or raw credential listings.
