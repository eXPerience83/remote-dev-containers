# TrueNAS ACL contract and safe migration

Remote Dev stores workspaces and agent credentials/state below one administrator-created TrueNAS Host Path root. On TrueNAS, POSIX mode bits alone are not enough to describe effective access when the dataset uses NFSv4 ACLs.

This document defines the host ACL contract proposed by issue #186 and the conservative migration path exercised on a real populated TrueNAS 26 system. The recorded migration evidence is dated 2026-09-02 and used Remote Dev candidate channel `candidate-pr-184` at source revision `2f355d4e19058f91a9be482d428eb16c097b0886`. The contemporaneous evidence did not record the exact TrueNAS 26 build string or the candidate image's immutable repository digest, so this evidence must not be presented as stable-release qualification. Issue #186 remains open; the exact PR #188 candidate still requires the final same-revision host audit, container diagnostics, restart/recreation and normal-use gates before merge or rollback-data removal.

## Reference contract for new deployments

Create the Remote Dev root dataset with the TrueNAS **Generic** preset.

This is a deliberate Remote Dev exception to TrueNAS's general guidance to use the **Apps** preset for application data. Remote Dev stores agent credentials and private runtime state in the same Host Path tree, and real-system validation for #186 showed that Apps-preset NFSv4 inheritance can leave additional host principals with effective access even when `ls -l` displays `0700`. The Generic/POSIX choice is therefore part of Remote Dev's private-state security contract, not a claim that the Apps preset is generally wrong for TrueNAS applications.

The reference root is:

```text
Pool1/remote-dev
/mnt/Pool1/remote-dev
```

On that 2026-09-02 TrueNAS 26 migration host, using the recorded `candidate-pr-184` / `2f355d4e19058f91a9be482d428eb16c097b0886` evidence above, the reference dataset reported these ZFS properties:

```text
acltype=posix
aclmode=discard
```

TrueNAS documentation describes the Generic preset's ACL mode as not applicable in the UI because Generic uses POSIX ACLs; the host-side audit nevertheless records the actual ZFS `aclmode` property and treats `discard` as the validated Remote Dev reference value.

Remote Dev's canonical layout still uses ordinary directories below that root unless an administrator deliberately creates a required descendant as a child dataset for snapshots, quotas or replication.

Structural and workspace roots use their documented `0755` initial modes. Every canonical private state leaf is root-owned (UID `0`), uses `0700`, and, on the reference TrueNAS layout, its effective ACL must be a **trivial POSIX1E ACL** containing only:

- owner/root: `rwx`;
- group: no access;
- other: no access;
- no named-user, named-group, mask/default or inherited entries.

The authoritative private-leaf list is not duplicated here; it comes from `scripts/lib/data_layout.py` and is consumed by bootstrap, preflight and the ACL audit.

## Why the Apps preset is not equivalent

TrueNAS **Apps** datasets use an NFSv4 ACL model with `aclmode=passthrough`. Real-system validation showed inherited ACEs remained effective on Remote Dev private leaves even when `ls -l` displayed `0700`.

That means `0700` can be true as a POSIX mode display while additional host identities still have effective access through NFSv4 ACEs. TrueNAS 26 documents an additional `MODIFY` entry for the Apps group (GID 568), while inherited ACLs can also include built-in administrator/user or directory-service principals depending on the parent and system. The exact principals observed on one host are evidence, not a universal allow/deny list.

Remote Dev therefore does **not** recommend the Apps preset for its Host Path root merely because Remote Dev itself is deployed as an App.

## Host ACL diagnostics

Run the audit from the TrueNAS shell with the script from the **same source revision** as the deployed image and host layout tools:

```bash
sudo python3 scripts/truenas-acl-audit.py \
  --root /mnt/Pool1/remote-dev \
  --include-antigravity
```

The audit is read-only. It checks:

- that the configured root is an exact ZFS dataset mountpoint;
- root `acltype` and `aclmode`;
- root ownership (UID `0`) of every canonical private leaf;
- canonical private-leaf mode `0700`;
- `filesystem.getacl` type `POSIX1E`;
- `trivial=true`;
- only owner/group/other entries with the expected effective permissions.

A successful reference deployment ends with:

```text
Remote Dev TrueNAS ACL audit: OK (Generic/POSIX private-state contract)
```

NFSv4, a non-root private owner, non-trivial POSIX ACLs, named/default entries or broader mode bits produce warnings and a non-zero exit status. The tool never changes ownership, permissions or ACLs.

### What `Run diagnostics` can and cannot see

`remote-dev-doctor` runs **inside** an isolated agent container. It now checks the POSIX mode of each private bind mountpoint and warns if a mounted private state path is broader than `0700`.

It intentionally does not claim to determine the TrueNAS host dataset ACL type or authoritative host ownership. The container does not receive the TrueNAS middleware/API, the host root or a container-engine socket just to inspect ACL policy. An inherited host NFSv4 ACE can therefore require the host-side audit even when the container sees `0700`.

This split preserves the isolation model:

- container diagnostics: mounted-path mode regression check;
- TrueNAS host audit: authoritative ZFS/ownership/effective-ACL check.

## Existing NFSv4 installations

Do not convert a populated root in place and do not run recursive `chmod`, `chown` or ACL rewriting as an implicit migration. Neither bootstrap nor container startup may silently perform a dataset ACL/ownership migration. Bootstrap preserves existing operator-owned paths; existing runtime-owned private-state permission hardening remains a separate runtime contract and must not be confused with host ACL migration.

The validated migration model is **side-by-side copy + verified cutover + retained rollback**.

### 1. Stop Remote Dev and inventory the source

Stop the TrueNAS Custom App before the final copy/cutover. Inventory the source for unexpected object types and hardlinks. A normal stopped Remote Dev tree is expected to contain directories, regular files and symlinks. Review device nodes, FIFOs or sockets before continuing.

### 2. Create rollback protection

Create a snapshot of the original dataset through the supported TrueNAS UI/API, then keep the original dataset itself intact during the migration.

### 3. Create a new Generic dataset

Create a temporary sibling dataset, for example:

```text
Pool1/remote-dev-posix-migrate
```

Use **Dataset Preset = Generic** and verify it is empty, `acltype=posix`, `aclmode=discard`.

### 4. Copy without carrying NFSv4 ACLs

The validated copy intentionally used rsync archive semantics without ACL/xattr copy flags:

```bash
sudo rsync -a --numeric-ids --info=progress2,stats2 \
  /mnt/Pool1/remote-dev/ \
  /mnt/Pool1/remote-dev-posix-migrate/
```

Do **not** add `-A` or `-X` to the validated procedure: the migration objective is to preserve content, symlinks, ownership IDs, modes and timestamps without transplanting the old ACL/security-metadata model. The validated dataset did not rely on arbitrary extended attributes. If a deployment intentionally depends on project or application xattrs, stop and design a targeted preservation/verification plan instead of adding `-X` wholesale. If the pre-copy inventory finds hardlinked regular files, review that case and add `-H` deliberately rather than assuming the validated dataset had hardlinks.

Verify file content before changing canonical directory modes:

```bash
sudo rsync -a --numeric-ids --checksum --dry-run --itemize-changes \
  /mnt/Pool1/remote-dev/ \
  /mnt/Pool1/remote-dev-posix-migrate/
```

No output means no rsync-detectable file/content difference under those same copy semantics; it is not a claim that omitted ACLs/xattrs were compared.

### 5. Normalize only canonical directory roots

Apply the documented `0755`/`0700` modes only to the canonical directories from `scripts/lib/data_layout.py`. Never use a recursive chmod over repositories, virtual environments, caches or user project content.

Then run the same-revision bootstrap, preflight and ACL audit against the temporary root. Bootstrap should report `no changes required`, preflight should return `OK`, and the ACL audit should return the Generic/POSIX success result.

The validated real migration already had root-owned private leaves, so it required no ownership rewrite. If the audit instead reports a private leaf owned by a non-root UID, stop and review that path before cutover. Do not introduce a recursive `chown` as an automatic remediation.

### 6. Verify no active users of either dataset

With the App still stopped, query TrueNAS for dataset processes and attachments on both source and destination. Do not rename while a process or attachment is using either dataset.

### 7. Cut over with a reversible rename

The tested TrueNAS 26 middleware requires `force=true` for dataset rename because the rename endpoint deliberately does not perform its own safety checks. Only use it after the explicit process/attachment checks above.

Rename the old dataset to a backup name, then rename the verified POSIX dataset to the canonical name. For example:

```text
Pool1/remote-dev                -> Pool1/remote-dev-nfsv4-backup
Pool1/remote-dev-posix-migrate  -> Pool1/remote-dev
```

After the rename, verify again that canonical `Pool1/remote-dev` is `posix/discard`, run preflight and the ACL audit against `/mnt/Pool1/remote-dev`, and only then start the App.

### 8. Validate real persistence after start

Confirm the launcher and each enabled agent load, the expected projects and previous sessions/conversations are present, and container bind mounts still source `/mnt/Pool1/remote-dev/...`.

Run container diagnostics and repeat the host ACL audit after startup. A process writing to the new dataset must not cause the private-state ACL to become broadened or non-trivial.

### 9. Keep rollback until normal use is proven

Do not immediately delete the old NFSv4 dataset. Keep it offline as a rollback source until the exact deployed revision has passed host ACL audit, container diagnostics, restart/recreation checks, session/conversation resume and at least one normal operator work cycle without requiring rollback. Here, **offline** means Remote Dev is stopped before any rollback operation, the retained NFSv4 dataset is not configured as an SMB/NFS or other share/export, no container bind mount points at its backup path, and TrueNAS reports no dataset processes or attachments using it. Verify those conditions after cutover and again immediately before rollback or deletion. If the retained dataset is still mounted as a local ZFS mountpoint solely for administrator rollback access, treat that mountpoint as sensitive host-only data and do not expose it through an application or network share. Retention is an operator decision rather than an automatic timer.

If rollback is required, stop Remote Dev before reversing the dataset names. Do not merge newer POSIX-side writes back into the NFSv4 backup casually; treat that as a separate data reconciliation task.

When those gates are complete, the old NFSv4 dataset may be removed deliberately through supported TrueNAS tooling. Decide separately whether to retain a snapshot or another verified backup according to the operator's normal backup policy; this project never deletes rollback data automatically.

## Deliberate non-goals

- No automatic ACL migration from bootstrap or container startup.
- No recursive permission or ownership normalization of project contents.
- No claim that container-local mode inspection can prove host NFSv4 privacy.
- No SMB exposure of `state`.
- SMB workspace ACL/sharing design remains separate under #71.
