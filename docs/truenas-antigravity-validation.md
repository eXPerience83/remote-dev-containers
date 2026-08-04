# TrueNAS experimental deployment and Antigravity validation

This runbook prepares the real validation tracked by issues #28, #29 and #69.
It applies to the first three-service TrueNAS implementation merged in commit
`3044a8ce21ed7a1215db1530e9e9679ac6469f67`.

Antigravity remains experimental until the manual login, filesystem-discovery,
persistence and recreation checks in #29 are complete. Do not expose ports
7680, 7681 or 7682 directly to the Internet.

## Scope and exclusions

This cycle validates:

- the navigation-only launcher on port 7680;
- Codex on independently authenticated port 7681;
- experimental Antigravity on independently authenticated port 7682;
- file-backed terminal passwords;
- the canonical role-scoped persistent-data layout;
- install, login, stop/start and container recreation behavior;
- isolation between launcher, Codex and Antigravity.

SMB sharing, Windows access and TrueNAS ACL design are intentionally deferred to
issue #71. Do not create an SMB share for `state` or `secrets`.

## Preserve the current deployment

Before changing the App:

1. save a copy of the current custom-App YAML;
2. record the current image ID and embedded source revision;
3. leave the existing `/mnt/Pool1/codex` tree untouched;
4. do not delete the old tree until the new deployment has passed recreation and
   rollback checks.

Example read-only inventory commands:

```bash
docker inspect codex-remote-dev --format 'container_image_id={{.Image}}'
docker exec codex-remote-dev remote-dev-version || true
docker inspect codex-remote-dev --format '{{json .Mounts}}' | jq .
```

Never print password environment values or credential-file contents.

## Verify and pin the published image

Pull the public AMD64 edge tag:

```bash
docker pull ghcr.io/experience83/remote-dev:edge-amd64
```

Verify that the embedded revision is the implementation being validated:

```bash
expected_revision=3044a8ce21ed7a1215db1530e9e9679ac6469f67
actual_revision="$(
  docker image inspect ghcr.io/experience83/remote-dev:edge-amd64 \
    --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
)"
printf 'expected=%s\nactual=%s\n' "$expected_revision" "$actual_revision"
test "$actual_revision" = "$expected_revision"
```

Record the immutable repository digest:

```bash
docker image inspect ghcr.io/experience83/remote-dev:edge-amd64 \
  --format '{{range .RepoDigests}}{{println .}}{{end}}'
```

Use the `ghcr.io/experience83/remote-dev@sha256:...` digest reference in the
TrueNAS validation YAML. Do not validate this lifecycle against the mutable edge
tag alone.

## Dataset boundary

Create these TrueNAS datasets with the **Generic** preset and no SMB share:

```text
Pool1/remote-dev
Pool1/remote-dev/workspaces
Pool1/remote-dev/state
Pool1/remote-dev/secrets
```

Only the four dataset boundaries above are required. The service-specific paths
below are ordinary directories inside them. Keeping `workspaces` separate makes
a later, independently reviewed SMB/ACL design possible without exposing
`state` or `secrets`.

## Create the canonical directories

Run from the TrueNAS shell after the datasets exist:

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
  /mnt/Pool1/remote-dev/state/antigravity/ssh \
  /mnt/Pool1/remote-dev/secrets/codex \
  /mnt/Pool1/remote-dev/secrets/antigravity
```

Do not create symlinks anywhere inside `/mnt/Pool1/remote-dev`.

## Create independent terminal passwords

Create two non-empty, single-line files. Their values may be changed later by
replacing the file and recreating/restarting the corresponding container; no
secret dataset must be deleted merely to rotate a password.

```bash
sudo bash -c '
  set -euo pipefail
  umask 077
  read -rsp "Codex terminal password: " password
  printf "\n"
  test -n "$password"
  printf "%s\n" "$password" > /mnt/Pool1/remote-dev/secrets/codex/web_password.txt
  unset password
'

sudo bash -c '
  set -euo pipefail
  umask 077
  read -rsp "Antigravity terminal password: " password
  printf "\n"
  test -n "$password"
  printf "%s\n" "$password" > /mnt/Pool1/remote-dev/secrets/antigravity/web_password.txt
  unset password
'

sudo chmod 0600 \
  /mnt/Pool1/remote-dev/secrets/codex/web_password.txt \
  /mnt/Pool1/remote-dev/secrets/antigravity/web_password.txt
```

Do not display either file with `cat`, `head`, `sed`, `xxd` or diagnostic
commands.

## Run the authoritative host preflight

Download the preflight from the exact implementation commit and run it before
saving the App YAML:

```bash
curl --fail --silent --show-error --location \
  https://raw.githubusercontent.com/eXPerience83/remote-dev-containers/3044a8ce21ed7a1215db1530e9e9679ac6469f67/scripts/preflight-data-layout.py \
  --output /tmp/remote-dev-preflight-data-layout.py

python3 /tmp/remote-dev-preflight-data-layout.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity
```

Expected result:

```text
Remote Dev data-layout preflight: OK (/mnt/Pool1/remote-dev; Codex + Antigravity)
```

The preflight rejects missing paths, symlink components, empty/multiline/NUL
passwords and password files with permissions broader than `0600`.

## Prepare the TrueNAS YAML

Use `compose/truenas.yml` from the exact implementation commit as the source:

```bash
curl --fail --silent --show-error --location \
  https://raw.githubusercontent.com/eXPerience83/remote-dev-containers/3044a8ce21ed7a1215db1530e9e9679ac6469f67/compose/truenas.yml \
  --output /tmp/remote-dev-truenas.yml
```

Before pasting it into the TrueNAS Custom App editor:

1. replace the image anchor with the immutable digest recorded above;
2. replace all three example `192.168.1.10` bindings with the trusted LAN or
   Tailscale address already used by the deployment;
3. leave the launcher unauthenticated for the current trusted-network model;
4. leave `WEB_PASSWORD_FILE=/run/secrets/web_password` for both agents;
5. do not add `WEB_PASSWORD` environment variables;
6. do not add privileged mode, capabilities, host networking, host-root mounts
   or a Docker socket;
7. keep `REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY="1"` only for this controlled
   validation.

The resulting stack must contain exactly:

```text
remote-dev-launcher      port 7680, no mounts
codex-remote-dev         port 7681, Codex-only mounts and password
antigravity-remote-dev   port 7682, Antigravity-only mounts and password
```

## First deployment checks

After stopping the old App and saving the replacement YAML:

```bash
docker ps --filter name=remote-dev --filter name=codex-remote-dev --filter name=antigravity-remote-dev
docker exec codex-remote-dev remote-dev-version
docker exec antigravity-remote-dev remote-dev-version
docker exec antigravity-remote-dev remote-dev-doctor
```

Confirm the embedded revision and digest match the pinned image. The
Antigravity diagnostic should report `not installed` without making the
container unhealthy.

Inspect only redacted configuration facts:

```bash
for container in remote-dev-launcher codex-remote-dev antigravity-remote-dev; do
  echo "== $container =="
  docker inspect "$container" --format \
    'privileged={{.HostConfig.Privileged}} network={{.HostConfig.NetworkMode}} cap_add={{json .HostConfig.CapAdd}} security={{json .HostConfig.SecurityOpt}} image={{.Image}}'
  docker inspect "$container" --format \
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
8. recreate all three containers with the same datasets;
9. confirm executable, login/settings behavior and workspace persistence;
10. verify Codex and launcher remain isolated and functional.

Do not run Codex and Antigravity concurrently against the same writable checkout.
The default deployment gives them separate workspaces.

## Rollback

If the new stack fails:

1. stop the new App;
2. restore the saved old YAML;
3. restore the previously recorded image reference if needed;
4. continue using `/mnt/Pool1/codex`;
5. leave `/mnt/Pool1/remote-dev` intact for diagnosis.

Do not copy credential files between the old and new trees and do not delete
either tree during the validation cycle.

## Completion evidence

Post sanitized results to #29 and #69:

- TrueNAS version and test date;
- exact image digest and embedded revision;
- Antigravity CLI version;
- browser/access method without account identity;
- pass/fail for install, login, stop/start and recreation;
- confirmed mount destinations and permission metadata;
- confirmation that launcher has no mounts;
- confirmation that `WEB_PASSWORD` is absent and both password files are
  read-only mounts;
- any safe error messages and follow-up issue links.

Never post passwords, OAuth codes, tokens, cookies, account email, private
repository names or raw credential listings.
