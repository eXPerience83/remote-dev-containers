#!/usr/bin/env python3
"""Check arguments and failure propagation at the real probe entry point."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROBES = Path(__file__).resolve().with_name("run-runtime-publication-probes.sh")
IMAGE = "ghcr.io/experience83/remote-dev@sha256:" + "a" * 64
IDENTITY = ["v0.3.0", "b" * 40, "stable"]
STUB = """
import json, os, sys
from pathlib import Path
command = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as log:
    print(json.dumps([command, *args]), file=log)
sys.exit(73 if any(x.endswith("/" + os.environ["FAIL"]) or
                   x == os.environ["FAIL"] for x in args) else 0)
"""


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for command in ("docker", "bash"):
            stub = root / command
            stub.write_text("#!" + sys.executable + "\n" + STUB, encoding="utf-8")
            stub.chmod(0o755)
        calls = root / "calls"
        env = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}", "CALLS": str(calls)}
        for mode, image, identity, failure, count in (
            ("local", "remote-dev:local", [], "", 6),
            ("published", IMAGE, IDENTITY, "", 6),
            ("noexec failure", IMAGE, IDENTITY, "test-codex-runtime-noexec-staging.py", 3),
            ("authentication failure", IMAGE, IDENTITY, "test-web-password-runtime.sh", 5),
        ):
            calls.unlink(missing_ok=True)
            result = subprocess.run(
                ["/bin/bash", str(PROBES), image, *identity],
                env={**env, "FAIL": failure}, check=False, timeout=15,
            )
            observed = [json.loads(line) for line in calls.read_text().splitlines()]
            assert result.returncode == (73 if failure else 0), mode
            assert len(observed) == count and all(image in call for call in observed), mode
            expected = [
                "codex-smoke-test", "test-remote-dev-context7-runtime-isolation.py",
                "test-codex-runtime-noexec-staging.py", "runtime-smoke-test.sh",
                "test-web-password-runtime.sh", "test-cross-service-isolation.sh",
            ]
            for call, script in zip(observed, expected[:count], strict=True):
                assert any(arg.endswith("/" + script) for arg in call), (mode, call)
            assert observed[0][observed[0].index(image) + 1:] == identity, mode
            assert "--network" in observed[1] and "none" in observed[1], mode
            assert "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777" in observed[2], mode
    print("PASS: runtime probes execute against one image and propagate failures")


if __name__ == "__main__":
    main()
