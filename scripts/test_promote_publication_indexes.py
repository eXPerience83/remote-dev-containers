#!/usr/bin/env python3
"""Exercise the promotion entry point with a scripted Buildx CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PROMOTE = Path(__file__).resolve().with_name("promote-publication-indexes.sh")
BASE = "ghcr.io/experience83/remote-dev-base"
RUNTIME = "ghcr.io/experience83/remote-dev"
BASE_DIGEST = "sha256:" + "a" * 64
RUNTIME_DIGEST = "sha256:" + "b" * 64
SHA = "c" * 40
VERSION = "v0.3.0"
STUB = """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
assert args[:2] == ["buildx", "imagetools"], args
with open("calls.jsonl", "a") as log:
    print(json.dumps(args[2:]), file=log)
failure = os.environ["FAIL"]
if args[2] == "create":
    if failure == "write":
        sys.exit(73)
    digest = args[-1].split("@")[1]
    if failure == "metadata":
        digest = "wrong"
    Path(args[args.index("--metadata-file") + 1]).write_text(
        json.dumps({"containerimage.descriptor": {"digest": digest}})
    )
elif args[2] == "inspect":
    refs = json.loads(os.environ["READBACKS"])
    digest = refs[args[3]]
    if failure == args[3]:
        digest = "wrong"
    print(json.dumps(digest))
else:
    sys.exit(64)
"""


def main() -> None:
    for channel, identifier, base_tags, runtime_tags in (
        ("edge", SHA, ["edge-amd64", "sha-" + SHA], ["edge", "edge-amd64", "sha-" + SHA]),
        ("stable", VERSION, [VERSION, "stable-amd64"], [VERSION, "stable", "stable-amd64", "latest"]),
    ):
        base_targets = [f"{BASE}:{tag}" for tag in base_tags]
        runtime_targets = [f"{RUNTIME}:{tag}" for tag in runtime_tags]
        readbacks = dict.fromkeys(base_targets, BASE_DIGEST) | dict.fromkeys(runtime_targets, RUNTIME_DIGEST)
        for failure in ("", "write", "metadata", base_targets[-1], runtime_targets[-1]):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                stub = root / "docker"
                stub.write_text("#!" + sys.executable + "\n" + STUB, encoding="utf-8")
                stub.chmod(0o755)
                base_ref = f"{BASE}@{BASE_DIGEST}"
                runtime_ref = f"{RUNTIME}@{RUNTIME_DIGEST}"
                result = subprocess.run(
                    ["bash", str(PROMOTE), channel, base_ref, runtime_ref, identifier],
                    cwd=root, capture_output=True, text=True, timeout=15,
                    env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                         "FAIL": failure, "READBACKS": json.dumps(readbacks)},
                )
                calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
                assert (result.returncode == 0) == (not failure), (channel, failure, result.stderr)
                expected = [("create", base_ref, base_targets)]
                if failure not in ("write", "metadata"):
                    expected += [("inspect", target, []) for target in base_targets]
                if not failure or failure == runtime_targets[-1]:
                    expected += [("create", runtime_ref, runtime_targets)]
                    expected += [("inspect", target, []) for target in runtime_targets]
                    assert (root / "base-promotion.json").is_file()
                observed = [
                    (call[0], call[-1], [call[i + 1] for i, arg in enumerate(call) if arg == "--tag"])
                    if call[0] == "create" else (call[0], call[1], [])
                    for call in calls
                ]
                assert observed == expected, (channel, failure, observed)
    print("PASS: promotion writes and rereads all aliases and stops on failure")


if __name__ == "__main__":
    main()
