#!/usr/bin/env python3
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/resolve-published-image-digest.sh"
BASE = "ghcr.io/experience83/remote-dev-base"
RUNTIME = "ghcr.io/experience83/remote-dev"


class ResolveDigestTests(unittest.TestCase):
    def run_resolver(
        self, repository: str, tag: str, repo_digests: list[str]
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            fake_dir = Path(tmp)
            docker = fake_dir / "docker"
            docker.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "case \"${1:-}\" in\n"
                "  pull) exit 0 ;;\n"
                "  image)\n"
                "    test \"${2:-}\" = inspect\n"
                "    printf '%s\\n' \"${FAKE_REPO_DIGESTS:-}\"\n"
                "    ;;\n"
                "  *) exit 91 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env["PATH"] = f"{fake_dir}:{env['PATH']}"
            env["FAKE_REPO_DIGESTS"] = "\n".join(repo_digests)
            return subprocess.run(
                ["bash", str(SCRIPT), repository, tag],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

    def test_resolves_one_exact_matching_digest(self) -> None:
        expected = f"{RUNTIME}@sha256:" + "a" * 64
        completed = self.run_resolver(
            RUNTIME,
            "edge-amd64",
            ["docker.io/unrelated/image@sha256:" + "b" * 64, expected],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), expected)

    def test_duplicate_identical_repo_digest_is_deduplicated(self) -> None:
        expected = f"{BASE}@sha256:" + "c" * 64
        completed = self.run_resolver(BASE, "edge-amd64", [expected, expected])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), expected)

    def test_multiple_matching_digests_are_rejected(self) -> None:
        completed = self.run_resolver(
            BASE,
            "edge-amd64",
            [
                f"{BASE}@sha256:" + "d" * 64,
                f"{BASE}@sha256:" + "e" * 64,
            ],
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("expected exactly one immutable RepoDigest", completed.stderr)

    def test_missing_matching_digest_is_rejected(self) -> None:
        completed = self.run_resolver(BASE, "edge-amd64", [])
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("found 0", completed.stderr)

    def test_noncanonical_repository_is_rejected_before_docker(self) -> None:
        completed = self.run_resolver(
            "ghcr.io/example/remote-dev", "edge-amd64", []
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("unsupported published image repository", completed.stderr)

    def test_non_edge_tag_is_rejected(self) -> None:
        completed = self.run_resolver(RUNTIME, "latest", [])
        self.assertEqual(completed.returncode, 2)
        self.assertIn("may resolve only edge-amd64", completed.stderr)


if __name__ == "__main__":
    unittest.main()
