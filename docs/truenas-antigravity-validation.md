# TrueNAS experimental deployment and Antigravity validation

This runbook prepares the real validation tracked by issues #28, #29 and #69.
It applies to the first three-service TrueNAS implementation merged in commit
`3044a8ce21ed7a1215db1530e9e9679ac6469f67` and to the current host-side
Compose/preflight files on `main`.

Antigravity remains experimental until the manual login, filesystem-discovery,
persistence and recreation checks in #29 are complete. Do not expose ports
7680, 7681 or 7682 directly to the Internet.

## Deployment modes

Remote Dev supports both terminal-password sources:

- **Home mode:** `WEB_PASSWORD` is written directly in the private TrueNAS App
  YAML. This is the default in `compose/truenas.yml` and requires no persistent
  secret directory.
- **Hardened mode:** `WEB_PASSWORD_FILE` points to a role-specific read-only
  file. This avoids placing the value in the container environment and remains
  the recommended choice for shared or separately administered systems.

`WEB_PASSWORD_FILE` takes precedence when both variables are present. A TrueNAS
administrator can inspect environment-backed values through the App YAML or
Docker metadata, so home mode is intended for a trusted domestic NAS.

## Scope and exclusions

This cycle validates:

- the navigation-only launcher on port 7680;
- Codex on independently authenticated port 7681;
- experimental Antigravity on independently authenticated port 7682;
- two independent home-mode terminal passwords;
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

Never print password environment values or credential-file contents.

## Verify and pin the published image

Pull the public AMD64 edge tag:

```bash
sudo docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

Verify that the embedded revision is the implementation being validated:

```bash
expected_revision=3044a8ce21ed7a1215db1530e9e9679ac6469f67
actual_revision="$(
  sudo docker image inspect ghcr.io/experience83/remote-dev:edge-amd64 \
    --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
)"
printf 'expected=%s\nactual=%s\n' "$expected_revision" "$actual_revision"
test "$actual_revision" = "$expected_revision"
```

Record the immutable repository digest:

```bash
sudo docker image inspect ghcr.io/experience83/remote-dev:edge-amd64 \
  --format '{{range .RepoDigests}}{{println .}}{{end}}'
```

Use the `ghcr.io/experience83/remote-dev@sha256:...` digest reference in the
TrueNAS validation YAML. Do not validate this lifecycle against the mutable edge
tag alone.

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

Run from the TrueNAS shell after the single dataset exists:

```bash
sudo install -d -m 0755 \
  /mnt/Pool1/remote-dev/workspaces/codex \
  /mnt/Pool1/remote-dev/workspaces/antigravity

sudo install -d -m 0700 \
  /mnt/Pool1/remote-dev/state/codex/agent \
  /mnt/Pool1/remote-dev/state/codex/gh \
  /mnt/Pool1/remote-dev/state/codex/git \
  /mnt/Pool1/remote-dev/state/codex/ssh \
  /mnt/Pool1/remote-dev/state/antigravity/bin \
  /mnt/Pool1/remote-dev/state/antigravity/runtime \
  /mnt/Pool1/remote-dev/state/antigravity/vendor \
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
    │   ├── gh/
    │   ├── git/
    │   └── ssh/
    └── antigravity/
        ├── bin/
        ├── runtime/
        ├── vendor/
        ├── gh/
        ├── git/
        └── ssh/
```

## Run the authoritative host preflight

Download the current preflight and run it before saving the App YAML:

```bash
curl --fail --silent --show-error --location \
  https://raw.githubusercontent.com/eXPerience83/remote-dev-containers/main/scripts/preflight-data-layout.py \
  --output /tmp/remote-dev-preflight-data-layout.py

python3 /tmp/remote-dev-preflight-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity \
  --password-source environment
```

Expected result:

```text
Remote Dev data-layout preflight: OK (/mnt/Pool1/remote-dev; Codex + Antigravity; passwords=environment)
```

Environment mode validates only persistent bind sources and symlink ancestry;
the actual passwords are validated by the runtime when the containers start.

## Prepare the TrueNAS YAML

Use the current `compose/truenas.yml` as the source:

```bash
curl --fail --silent --show-error --location \
  https://raw.githubusercontent.com/eXPerience83/remote-dev-containers/main/compose/truenas.yml \
  --output /tmp/remote-dev-truenas.yml
```

Before pasting it into the TrueNAS Custom App editor:

1. replace the image anchor with the immutable digest recorded above;
2. replace all three example `192.168.1.10` bindings with the trusted LAN or
   Tailscale address already used by the deployment;
3. leave the launcher unauthenticated for the current trusted-network model;
4. replace the Codex `WEB_PASSWORD` placeholder with a strong password;
5. replace the Antigravity `WEB_PASSWORD` placeholder with a different strong
   password;
6. keep both values quoted and never commit the personalized YAML to Git;
7. do not add privileged mode, capabilities, host networking, host-root mounts
   or a Docker socket;
8. keep `REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY="1"` only for this controlled
   validation.

The resulting stack must contain exactly:

```text
remote-dev-launcher      port 7680, no mounts
codex-remote-dev         port 7681, Codex-only persistent mounts
antigravity-remote-dev   port 7682, Antigravity-only persistent mounts
```

## First deployment checks

After stopping the old App and saving the replacement YAML, set `pinned_image`
to the exact `ghcr.io/experience83/remote-dev@sha256:...` reference used in the
YAML and run:

```bash
pinned_image='ghcr.io/experience83/remote-dev@sha256:replace-with-recorded-digest'

sudo docker ps --filter name=remote-dev --filter name=codex-remote-dev --filter name=antigravity-remote-dev
sudo docker exec codex-remote-dev remote-dev-version
sudo docker exec antigravity-remote-dev remote-dev-version
sudo docker exec antigravity-remote-dev remote-dev-doctor
```

Confirm the embedded revision and digest match the pinned image. The
Antigravity diagnostic should report `not installed` without making the
container unhealthy.

Inspect only redacted configuration facts and assert the configured immutable
reference, not only the local content-addressable image ID:

```bash
for container in remote-dev-launcher codex-remote-dev antigravity-remote-dev; do
  echo "== $container =="
  configured_image="$(sudo docker inspect "$container" --format '{{.Config.Image}}')"
  test "$configured_image" = "$pinned_image"
  sudo docker inspect "$container" --format \
    'configured_image={{.Config.Image}} image_id={{.Image}} privileged={{.HostConfig.Privileged}} network={{.HostConfig.NetworkMode}} cap_add={{json .HostConfig.CapAdd}} security={{json .HostConfig.SecurityOpt}}'
  sudo docker inspect "$container" --format \
    '{{range .Mounts}}{{println .Destination "<-" .Source "rw=" .RW}}{{end}}'
done
```

Do not dump complete container environments. Verify only variable names when
needed.

## Browser checks

- Port 7680 opens the launcher without a password on the trusted network.
- The Codex link opens port 7681 and requires the Codex credential.
- The experimental Antigravity link opens port 7682 and requires the separate
  Antigravity credential.
- Credentials never appear in launcher HTML, URLs or browser history.

## Antigravity lifecycle gate

Starting from the Antigravity menu:

1. confirm `not installed`;
2. run the explicit installer and review the vendor/non-affiliation notice;
3. record the installed version without publishing account details;
4. complete the official individual/free login flow;
5. record filesystem changes as path names and metadata only;
6. run a disposable repository test;
7. stop/start the App;
8. recreate all three containers with the same dataset;
9. confirm executable, login/settings behavior and workspace persistence;
10. verify Codex and launcher remain isolated and functional.

Do not run Codex and Antigravity concurrently against the same writable checkout.
The default deployment gives them separate workspaces.

## Hardened password-file alternative

A deployment that must keep terminal passwords out of container environment
metadata can use `WEB_PASSWORD_FILE` instead. Create ordinary directories inside
the same dataset:

```text
/mnt/Pool1/remote-dev/secrets/codex/web_password.txt
/mnt/Pool1/remote-dev/secrets/antigravity/web_password.txt
```

Use one non-empty single-line file per role, mode `0600`, mount each file
read-only at `/run/secrets/web_password`, remove the corresponding
`WEB_PASSWORD` variable and run:

```bash
python3 /tmp/remote-dev-preflight-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity \
  --password-source file
```

The generic `compose/docker-compose.yml` remains the repository example for
file-backed credentials.

## Rollback

If the new stack fails:

1. stop the new App;
2. restore the saved old YAML;
3. restore the previously recorded image reference if needed;
4. continue using the previously recorded legacy data tree;
5. leave `/mnt/Pool1/remote-dev` intact for diagnosis.

Do not copy credentials between the old and new trees and do not delete either
tree during the validation cycle.

## Completion evidence

Post sanitized results to #29 and #69:

- TrueNAS version and test date;
- exact image digest and embedded revision;
- password source (`environment` or `file`) without its value;
- Antigravity CLI version;
- browser/access method without account identity;
- pass/fail for install, login, stop/start and recreation;
- confirmed mount destinations and permission metadata;
- confirmation that launcher has no mounts;
- confirmation that Codex and Antigravity use independent credentials;
- any safe error messages and follow-up issue links.

Never post passwords, OAuth codes, tokens, cookies, account email, private
repository names or raw credential listings.
