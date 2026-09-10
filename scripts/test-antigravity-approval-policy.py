#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "remote-dev-antigravity-policy.py"
SPEC = importlib.util.spec_from_file_location("remote_dev_antigravity_policy", MODULE_PATH)
assert SPEC and SPEC.loader
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)


def write_settings(root: Path, data: object, mode: int = 0o600) -> Path:
    vendor = root / "vendor"
    vendor.mkdir(mode=0o700)
    path = vendor / "settings.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    path.chmod(mode)
    return path


def assert_ok(data: dict[str, object]) -> None:
    report = policy.guarded_report(data)
    assert report.compatible, report


def assert_blocked(data: dict[str, object]) -> None:
    report = policy.guarded_report(data)
    assert not report.compatible, report


def main() -> None:
    assert_ok({})
    assert_ok({"toolPermission": "request-review"})
    assert_ok({"toolPermission": "strict"})
    assert_ok({"artifactReviewPolicy": "asks-for-review"})
    assert_ok({"agentMode": "default"})
    assert_ok({"agentMode": "plan"})
    assert_ok(
        {
            "toolPermission": "request-review",
            "artifactReviewPolicy": "asks-for-review",
            "agentMode": "default",
            "permissions": {
                "allow": ["command(git status)"],
                "ask": ["command(curl)"],
                "deny": ["command(rm)"],
            },
        }
    )

    for value in ("always-proceed", "proceed-in-sandbox"):
        assert_blocked({"toolPermission": value})
    for value in ("agent-decides", "always-proceed"):
        assert_blocked({"artifactReviewPolicy": value})
    assert_blocked({"agentMode": "accept-edits"})

    assert_blocked({"toolPermission": "future-mode"})
    assert_blocked({"artifactReviewPolicy": "future-policy"})
    assert_blocked({"agentMode": "future-mode"})
    assert_blocked({"toolPermission": True})
    assert_blocked({"artifactReviewPolicy": []})
    assert_blocked({"agentMode": {}})

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        missing = root / "vendor" / "settings.json"
        snapshot, report = policy.inspect_guarded(missing)
        assert not snapshot.exists
        assert report.compatible

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        denied = root / "vendor" / "settings.json"
        original_lstat = policy.os.lstat

        def denied_lstat(path: object) -> os.stat_result:
            if Path(path) == denied:
                raise PermissionError(13, "permission denied")
            return original_lstat(path)

        policy.os.lstat = denied_lstat
        try:
            try:
                policy.inspect_guarded(denied)
            except policy.PolicyError as exc:
                assert "cannot inspect settings file metadata" in str(exc)
            else:
                raise AssertionError("inaccessible settings must fail closed as PolicyError")
        finally:
            policy.os.lstat = original_lstat

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        original = {
            "theme": "dark",
            "allowNonWorkspaceAccess": True,
            "toolPermission": "request-review",
            "artifactReviewPolicy": "asks-for-review",
            "agentMode": "default",
            "permissions": {
                "allow": ["command(git status)"],
                "ask": ["command(curl)"],
                "deny": ["command(rm)"],
            },
            "unknownFutureSetting": {"nested": [1, 2, 3]},
        }
        path = write_settings(root, original)
        before = path.read_bytes()
        snapshot, report = policy.inspect_guarded(path)
        assert snapshot.data == original
        assert report.compatible
        assert path.read_bytes() == before, "policy inspection must remain read-only"
        assert "user-managed" in report.summary

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        vendor = root / "vendor"
        vendor.mkdir(mode=0o700)
        real = vendor / "real.json"
        real.write_text("{}\n", encoding="utf-8")
        real.chmod(0o600)
        link = vendor / "settings.json"
        link.symlink_to(real)
        try:
            policy.inspect_guarded(link)
        except policy.PolicyError:
            pass
        else:
            raise AssertionError("symlink settings must fail closed")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = write_settings(root, {"toolPermission": "request-review"}, mode=0o644)
        try:
            policy.inspect_guarded(path)
        except policy.PolicyError:
            pass
        else:
            raise AssertionError("broad settings permissions must fail closed")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        vendor = root / "vendor"
        vendor.mkdir(mode=0o700)
        path = vendor / "settings.json"
        path.write_text("{broken", encoding="utf-8")
        path.chmod(0o600)
        try:
            policy.inspect_guarded(path)
        except policy.PolicyError:
            pass
        else:
            raise AssertionError("malformed JSON must fail closed")

    assert not hasattr(policy, "repair_guarded"), "policy helper must not mutate vendor settings"
    print("Antigravity guarded approval policy read-only diagnostics: OK")


if __name__ == "__main__":
    main()
