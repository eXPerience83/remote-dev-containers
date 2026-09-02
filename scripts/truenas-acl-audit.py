#!/usr/bin/env python3
"""Audit the effective TrueNAS ACL contract for Remote Dev persistent state."""

from __future__ import annotations

import argparse
import json
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from lib.data_layout import canonical_path, directory_specs, validate_layout


@dataclass(frozen=True)
class Finding:
    """One host ACL audit finding."""

    level: str
    message: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse TrueNAS ACL audit arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Audit a TrueNAS Remote Dev data root for the Generic/POSIX "
            "reference ACL contract without modifying filesystem state."
        )
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Existing TrueNAS dataset mountpoint used as REMOTE_DEV_DATA_ROOT",
    )
    parser.add_argument(
        "--include-antigravity",
        action="store_true",
        help="Also audit the optional isolated Antigravity private-state leaves",
    )
    return parser.parse_args(argv)


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one read-only host inspection command and capture its output."""
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def find_root_dataset(root: Path) -> tuple[str | None, str | None]:
    """Return the ZFS dataset mounted exactly at root, or a diagnostic error."""
    result = run_command(
        ["zfs", "list", "-H", "-o", "name,mountpoint", "-t", "filesystem"]
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        return None, f"cannot list ZFS datasets: {detail}"

    root_text = str(root)
    for line in result.stdout.splitlines():
        fields = line.split("\t", 1)
        if len(fields) == 2 and fields[1] == root_text:
            return fields[0], None
    return None, f"configured root is not an exact ZFS dataset mountpoint: {root}"


def read_dataset_acl_properties(dataset: str) -> tuple[dict[str, str], str | None]:
    """Read the ACL properties needed for the TrueNAS reference contract."""
    result = run_command(
        ["zfs", "get", "-H", "-o", "property,value", "acltype,aclmode", dataset]
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        return {}, f"cannot read ACL properties for {dataset}: {detail}"

    properties: dict[str, str] = {}
    for line in result.stdout.splitlines():
        fields = line.split("\t", 1)
        if len(fields) == 2:
            properties[fields[0]] = fields[1]
    missing = {"acltype", "aclmode"} - properties.keys()
    if missing:
        return {}, (
            f"missing ZFS ACL properties for {dataset}: "
            f"{', '.join(sorted(missing))}"
        )
    return properties, None


def read_effective_acl(path: Path) -> tuple[dict[str, object] | None, str | None]:
    """Ask the TrueNAS middleware for the effective ACL on one path."""
    result = run_command(["midclt", "call", "filesystem.getacl", str(path)])
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        return None, f"cannot read TrueNAS ACL for {path}: {detail}"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"invalid filesystem.getacl response for {path}: {exc}"
    if not isinstance(payload, dict):
        return None, f"unexpected filesystem.getacl response for {path}"
    return payload, None


def validate_private_acl(payload: dict[str, object]) -> list[str]:
    """Return problems with one role-private leaf's effective ACL."""
    errors: list[str] = []
    acltype = payload.get("acltype")
    if acltype != "POSIX1E":
        errors.append(f"effective ACL type is {acltype!r}, expected 'POSIX1E'")
    if payload.get("trivial") is not True:
        errors.append("effective POSIX ACL is not trivial")

    raw_acl = payload.get("acl")
    if not isinstance(raw_acl, list):
        errors.append("filesystem.getacl did not return an ACL entry list")
        return errors

    expected = {
        "USER_OBJ": (True, True, True),
        "GROUP_OBJ": (False, False, False),
        "OTHER": (False, False, False),
    }
    if len(raw_acl) != len(expected):
        errors.append(
            f"effective ACL has {len(raw_acl)} entries, "
            "expected only owner/group/other"
        )

    seen: set[str] = set()
    for raw_entry in raw_acl:
        if not isinstance(raw_entry, dict):
            errors.append("effective ACL contains a malformed entry")
            continue
        tag = raw_entry.get("tag")
        if not isinstance(tag, str) or tag not in expected:
            errors.append(f"unexpected effective ACL entry: {tag!r}")
            continue
        if tag in seen:
            errors.append(f"duplicate effective ACL entry: {tag}")
            continue
        seen.add(tag)
        if raw_entry.get("default") is not False:
            errors.append(
                f"effective ACL entry {tag} is unexpectedly inherited/default"
            )
        perms = raw_entry.get("perms")
        if not isinstance(perms, dict):
            errors.append(f"effective ACL entry {tag} has malformed permissions")
            continue
        actual = (
            perms.get("READ") is True,
            perms.get("WRITE") is True,
            perms.get("EXECUTE") is True,
        )
        if actual != expected[tag]:
            errors.append(
                f"effective ACL entry {tag} permissions are {actual}, "
                f"expected {expected[tag]}"
            )

    missing = expected.keys() - seen
    if missing:
        errors.append(f"effective ACL is missing entries: {', '.join(sorted(missing))}")
    return errors


def audit(root: Path, *, include_antigravity: bool) -> tuple[list[str], list[Finding]]:
    """Return informational lines and every security/tooling finding."""
    root = canonical_path(root)
    info: list[str] = []
    findings: list[Finding] = []

    layout_errors = validate_layout(root, include_antigravity=include_antigravity)
    if layout_errors:
        findings.extend(Finding("ERROR", error) for error in layout_errors)
        return info, findings

    dataset, dataset_error = find_root_dataset(root)
    if dataset_error:
        findings.append(Finding("ERROR", dataset_error))
        return info, findings
    assert dataset is not None

    properties, properties_error = read_dataset_acl_properties(dataset)
    if properties_error:
        findings.append(Finding("ERROR", properties_error))
        return info, findings

    acltype = properties["acltype"]
    aclmode = properties["aclmode"]
    info.append(f"Dataset {dataset}: acltype={acltype} aclmode={aclmode}")
    if acltype != "posix":
        findings.append(
            Finding(
                "WARNING",
                f"root dataset {dataset} uses acltype={acltype}; "
                "Remote Dev's TrueNAS reference contract is Generic/POSIX",
            )
        )
    if aclmode != "discard":
        findings.append(
            Finding(
                "WARNING",
                f"root dataset {dataset} uses aclmode={aclmode}; "
                "the Generic/POSIX reference is aclmode=discard",
            )
        )

    private_specs = tuple(
        spec
        for spec in directory_specs(include_antigravity=include_antigravity)
        if spec.mode == 0o700
    )
    for spec in private_specs:
        path = root / spec.suffix
        mode = stat.S_IMODE(path.stat().st_mode)
        acl_payload, acl_error = read_effective_acl(path)
        if acl_error:
            findings.append(Finding("ERROR", acl_error))
            continue
        assert acl_payload is not None

        path_errors: list[str] = []
        if mode != 0o700:
            path_errors.append(f"mode is {mode:04o}, expected 0700")
        path_errors.extend(validate_private_acl(acl_payload))
        if path_errors:
            for error in path_errors:
                findings.append(Finding("WARNING", f"{path}: {error}"))
        else:
            info.append(f"Private state OK: {path} (0700, POSIX1E trivial)")

    return info, findings


def main(argv: list[str] | None = None) -> int:
    """Run the read-only TrueNAS ACL audit."""
    args = parse_args(argv)
    try:
        info, findings = audit(
            args.root,
            include_antigravity=args.include_antigravity,
        )
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired) as exc:
        print(f"Remote Dev TrueNAS ACL audit failed: {exc}", file=sys.stderr)
        return 2

    print("Remote Dev TrueNAS ACL audit")
    print("============================")
    for line in info:
        print(line)
    for finding in findings:
        print(f"{finding.level}: {finding.message}", file=sys.stderr)

    if findings:
        print(
            "Remote Dev TrueNAS ACL audit: ATTENTION REQUIRED. "
            "Do not recursively chmod/chown or rewrite ACLs as an implicit fix.",
            file=sys.stderr,
        )
        return 1

    print("Remote Dev TrueNAS ACL audit: OK (Generic/POSIX private-state contract)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
