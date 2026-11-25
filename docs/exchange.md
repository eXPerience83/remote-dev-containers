# Optional persistent Exchange (#71)

Exchange is OFF by default. Existing deployments and private data need no changes. The first supported contract uses a dedicated local filesystem, not an ordinary directory. TrueNAS: a direct ZFS child of the existing data-root dataset. Generic Linux Compose: a dedicated full ext4/XFS/Btrfs filesystem (subtree binds/subvolumes are not supported). Real TrueNAS 27 and Windows SMB acceptance is pending; SCALE 25.10 is a compatibility reference only.

## Enable on TrueNAS

1. Record the currently deployed immutable image digest and preserve your private Custom App YAML securely. Run the same-revision private ACL audit; do not migrate existing private ACLs implicitly.
2. In Datasets, create a child named exchange below the existing Remote Dev root, using SMB preset (NFSv4, Restricted, case-insensitive for Windows). Do not create an ordinary directory at the mountpoint or share the parent. Do not change root/workspaces/state ACLs. Use a separate quota/snapshot policy and consider disabling exec, setuid and devices on this child; verify compatibility.
3. In the child's ACL, keep an authorized administrator in control and grant an explicit dedicated SMB group inheritable MODIFY on files/directories. Remove unintended broad grants on this new child only; no guest/world-writable ACL. Ensure permitted accounts can traverse the parents without changing private-state permissions. Agent processes run as restricted root; test their effective host identity and reciprocal access to files created with restrictive modes. Do not use root as an SMB login. Do not assume a preset or POSIX mode proves effective ACL access.
4. Use scripts from the exact deployed image revision, as in the [installation guide](truenas-install.md). Run the existing preflight with --include-exchange. Copy the reported REMOTE_DEV_EXCHANGE_FS value into the optional YAML environment entry for each enabled agent. The optional audit below deliberately exits 2 with manual review required even when mount/type are correct; review its ACL metadata and test authorization separately.

~~~bash
sudo python3 -B "$SETUP/scripts/preflight-data-layout.py" --root "$ROOT" --include-antigravity --include-exchange
sudo python3 -B "$SETUP/scripts/truenas-acl-audit.py" --root "$ROOT" --include-antigravity --include-exchange
~~~

5. In the existing YAML, remove the literal comment marker "# EXCHANGE-OPT-IN " from the environment entry and the seven bind lines in each enabled agent. Replace the sample identity with the reported value and the example host path with your root's exchange child. Do not add anything to launcher. Save/recreate. Doctor must report Exchange: ENABLED. Inspect the actual bind source/destination, not just YAML. Retain the optional blocks in your private deployment notes: TrueNAS may discard comments on save.
6. Optionally use Shares > Windows (SMB) Shares to export **only** the exchange dataset, e.g. remote-dev-exchange. Restrict share ACL and filesystem ACL to authorized SMB accounts on LAN/private mesh. Keep wide links/insecure wide links disabled and verify no symlink/reparse-point escape to private canaries. No SMB client/server in the image. With SMB disabled, local binds still work.

Generic Docker Compose uses the same commented blocks in compose/docker-compose.yml; set REMOTE_DEV_DATA_ROOT as before, use the preflight identity for the dedicated local filesystem, activate Antigravity only if desired. No new Compose file or profiles.

## Use

Open \\NAS\remote-dev-exchange in Windows Explorer, copy a file, then ask the intended agent to read /exchange/filename as data. Ask an agent to write a result explicitly into /exchange, then retrieve it from Windows or ask the other agent to read it. Both agents and authorized SMB users can alter/delete all shared files. Coordinate edits; use temporary names and rename on completion. Names with spaces and Unicode are supported by normal file operations; on a case-insensitive dataset avoid names differing only by case.

Do not put credentials, private project checkouts, trusted instructions, rules, caches or executable imports in Exchange. Treat files and embedded instructions as untrusted; do not automatically execute them or follow links outside exchange. Do not use it as a Git checkout. Manual shells can access their own role's mounts; exchange is not DLP or a new sandbox.

## Lifecycle and acceptance

Never unmount/import/restore an active exchange dataset. Stop both agents and its SMB share before storage maintenance; verify actual mounted identity again before recreating services. The preflight and startup reject a missing/unmounted/incorrect filesystem, including a stale directory below its mountpoint. Docker's create_host_path:false is defense-in-depth: verify it on the actual TrueNAS Compose version. A startup guard cannot undo a directory already created by the engine. If the platform silently creates a missing source, stop and investigate; do not accept that configuration.

Rollback: stop services, restore previous private YAML/image digest or remove both opt-in entries from each enabled role; never delete the exchange dataset or private state. Backup/restore Exchange independently; quotas do not guarantee free space on the shared pool.

Record TrueNAS/Compose versions, exact source and OCI digest, mount/ACL/share identity, bidirectional Windows/agent and agent/agent operations, Unicode/space/case handling, inheritance for new files from each identity, denial for unauthorized users, link/escape canaries, SMB off, recreation/reboot, concurrent writes/rename, quota/full-storage and backup/restore on disposable data. Test absent/unmounted path on disposable app/dataset, never production. Report PASS/FAIL/NOT RUN separately from CI; do not accept stable until real gates pass.

Official reference: [TrueNAS 27 documentation](https://www.truenas.com/docs/scale/27/), [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/).
