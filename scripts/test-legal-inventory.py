#!/usr/bin/env python3
"""Unit tests for the fail-closed legal inventory implementation."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import legal_inventory  # noqa: E402


class LegalInventoryTests(unittest.TestCase):
    """Exercise fail-closed inventory discovery and reconciliation behavior."""
    def test_git_blob_sha_matches_git_object_format(self) -> None:
        """Verify git blob sha matches git object format."""
        self.assertEqual(
            legal_inventory.git_blob_sha1(b"hello\n"),
            "ce013625030ba8dba906f756967f9e9ca394464a",
        )

    def test_discovers_apt_downloads_and_global_npm(self) -> None:
        """Verify discovers apt downloads and global npm."""
        with tempfile.TemporaryDirectory() as temporary:
            dockerfile = Path(temporary) / "Dockerfile"
            dockerfile.write_text(
                """RUN apt-get update \\
    && apt-get install -y --no-install-recommends \\
        bash \\
        jq \\
    && rm -rf /var/lib/apt/lists/*
RUN curl --fail \\
    \"https://github.com/example/tool/releases/download/v${TOOL_VERSION}/tool\" -o tool
RUN npm install --global --ignore-scripts \"npm@${NPM_VERSION}\"
LABEL docs=\"https://github.com/example/docs\"
""",
                encoding="utf-8",
            )
            self.assertEqual(legal_inventory.parse_apt_packages(dockerfile), ["bash", "jq"])
            self.assertEqual(
                legal_inventory.docker_download_urls(dockerfile),
                ["https://github.com/example/tool/releases/download/v${TOOL_VERSION}/tool"],
            )
            self.assertEqual(legal_inventory.global_npm_specs(dockerfile), [("npm", "NPM_VERSION")])

    def test_unclaimed_version_input_fails_closed(self) -> None:
        """Verify unclaimed version input fails closed."""
        inventory = {
            "schema_version": 1,
            "components": [
                {
                    "id": "project",
                    "name": "Project",
                    "distribution": "project",
                    "image_scope": "project",
                    "version_source": {"kind": "env", "key": "BASE_VERSION"},
                    "inputs": ["BASE_VERSION"],
                    "upstream": "example",
                    "license_expression": "Apache-2.0",
                    "notice_treatment": "text",
                    "notice_locations": ["/LICENSE"],
                    "trademark_policy": "text",
                    "sbom": {"status": "not-applicable", "reason": "project"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "images/base").mkdir(parents=True)
            (root / "images/codex").mkdir(parents=True)
            (root / "images/base/Dockerfile").write_text("ARG BASE_VERSION=1\n", encoding="utf-8")
            (root / "images/codex/Dockerfile").write_text("", encoding="utf-8")
            env = {"BASE_VERSION": "1", "NEW_TOOL_VERSION": "2"}
            with self.assertRaisesRegex(legal_inventory.InventoryError, "not inventoried"):
                legal_inventory.validate_inputs(root, inventory, env, {})

    def test_unclaimed_direct_download_fails_closed(self) -> None:
        """Verify unclaimed direct download fails closed."""
        inventory = {
            "schema_version": 1,
            "components": [
                {
                    "id": "project",
                    "name": "Project",
                    "distribution": "project",
                    "image_scope": "project",
                    "version_source": {"kind": "project"},
                    "inputs": [],
                    "upstream": "example",
                    "license_expression": "Apache-2.0",
                    "notice_treatment": "text",
                    "notice_locations": ["/LICENSE"],
                    "trademark_policy": "text",
                    "sbom": {"status": "not-applicable", "reason": "project"}
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "images/base").mkdir(parents=True)
            (root / "images/codex").mkdir(parents=True)
            (root / "images/base/Dockerfile").write_text(
                'RUN curl "https://vendor.example/tool.tar.gz" -o tool.tar.gz\n', encoding="utf-8"
            )
            (root / "images/codex/Dockerfile").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(legal_inventory.InventoryError, "exactly one component"):
                legal_inventory.validate_discovery(root, inventory)

    def test_unclaimed_installer_command_fails_closed(self) -> None:
        """Verify new package-manager installation paths require an owner."""
        inventory = {
            "schema_version": 1,
            "components": [
                {
                    "id": "project",
                    "name": "Project",
                    "distribution": "project",
                    "image_scope": "project",
                    "version_source": {"kind": "project"},
                    "inputs": [],
                    "upstream": "example",
                    "license_expression": "Apache-2.0",
                    "notice_treatment": "text",
                    "notice_locations": ["/LICENSE"],
                    "trademark_policy": "text",
                    "sbom": {"status": "not-applicable", "reason": "project"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "images/base").mkdir(parents=True)
            (root / "images/codex").mkdir(parents=True)
            (root / "images/base/Dockerfile").write_text(
                "RUN python3 -m pip install new-tool==1.0\n", encoding="utf-8"
            )
            (root / "images/codex/Dockerfile").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(legal_inventory.InventoryError, "installer command"):
                legal_inventory.validate_discovery(root, inventory)

    def test_invalid_apt_token_fails_closed(self) -> None:
        """Verify dynamic or pinned APT syntax cannot disappear from inventory."""
        with tempfile.TemporaryDirectory() as temporary:
            dockerfile = Path(temporary) / "Dockerfile"
            dockerfile.write_text(
                "RUN apt-get install -y --no-install-recommends bash=$BASH_VERSION\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(legal_inventory.InventoryError, "unsupported APT package token"):
                legal_inventory.parse_apt_packages(dockerfile)

    def test_unknown_sbom_ecosystem_fails_closed(self) -> None:
        """Verify unknown sbom ecosystem fails closed."""
        inventory = {
            "schema_version": 1,
            "components": [
                {
                    "id": "apt",
                    "name": "APT",
                    "distribution": "apt",
                    "image_scope": "both",
                    "version_source": {"kind": "discovered"},
                    "inputs": [],
                    "upstream": "ubuntu",
                    "license_expression": "multiple",
                    "notice_treatment": "text",
                    "notice_locations": ["/usr/share/doc/<package>/copyright"],
                    "trademark_policy": "text",
                    "sbom": {"status": "covered-by-ecosystem"}
                }
            ],
            "sbom_coverage": [{"owner": "apt packages", "purl_types": ["deb"]}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "images/base").mkdir(parents=True)
            (root / "images/base/Dockerfile").write_text(
                """RUN apt-get install -y --no-install-recommends \\
        bash \\
    && true
""",
                encoding="utf-8",
            )
            sbom = root / "sbom.json"
            sbom.write_text(
                json.dumps(
                    {
                        "packages": [
                            {
                                "name": "bash",
                                "externalRefs": [{"referenceLocator": "pkg:deb/ubuntu/bash@1"}],
                            },
                            {
                                "name": "mystery",
                                "externalRefs": [{"referenceLocator": "pkg:gem/mystery@1"}],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(legal_inventory.InventoryError, "unclassified package ecosystems: gem"):
                legal_inventory.reconcile_sboms(root, inventory, [f"base={sbom}", f"final={sbom}"])


if __name__ == "__main__":
    unittest.main()
