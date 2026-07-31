#!/usr/bin/env python3
"""Unit tests for the fail-closed legal inventory implementation."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import legal_inventory  # noqa: E402
from legal_inventory import documents  # noqa: E402


class LegalInventoryTests(unittest.TestCase):
    """Exercise fail-closed inventory discovery and reconciliation behavior."""

    def test_git_blob_sha_matches_git_object_format(self) -> None:
        self.assertEqual(legal_inventory.git_blob_sha1(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_discovers_apt_downloads_and_global_npm(self) -> None:
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

    def test_pipeline_and_shell_wrapper_downloads_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dockerfile = Path(temporary) / "Dockerfile"
            dockerfile.write_text(
                """RUN printf x | curl https://vendor.example/pipe -o /tmp/pipe
RUN bash -lc 'wget https://vendor.example/wrapped -O /tmp/wrapped'
""",
                encoding="utf-8",
            )
            self.assertEqual(
                legal_inventory.docker_download_urls(dockerfile),
                ["https://vendor.example/pipe", "https://vendor.example/wrapped"],
            )

    def test_npm_install_aliases_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dockerfile = Path(temporary) / "Dockerfile"
            dockerfile.write_text(
                'RUN env CI=1 npm --global install "some-tool@${TOOL_VERSION}"\n',
                encoding="utf-8",
            )
            self.assertEqual(legal_inventory.global_npm_specs(dockerfile), [("some-tool", "TOOL_VERSION")])

    def test_apt_package_names_are_not_network_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dockerfile = Path(temporary) / "Dockerfile"
            dockerfile.write_text(
                "RUN apt-get install -y --no-install-recommends curl wget && git lfs install --system\n",
                encoding="utf-8",
            )
            self.assertEqual(legal_inventory.docker_download_urls(dockerfile), [])

    def test_fixed_global_npm_package_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dockerfile = Path(temporary) / "Dockerfile"
            dockerfile.write_text("RUN npm install --global some-tool@1.2.3\n", encoding="utf-8")
            with self.assertRaisesRegex(legal_inventory.InventoryError, "unsupported global npm package spec"):
                legal_inventory.global_npm_specs(dockerfile)

    def test_dynamic_network_fetch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dockerfile = Path(temporary) / "Dockerfile"
            dockerfile.write_text('RUN curl --fail "$TOOL_URL" -o /usr/local/bin/tool\n', encoding="utf-8")
            with self.assertRaisesRegex(legal_inventory.InventoryError, "literal HTTPS source"):
                legal_inventory.docker_download_urls(dockerfile)

    def test_direct_download_component_requires_source_document(self) -> None:
        inventory = {
            "schema_version": 1,
            "components": [
                {
                    "id": "tool",
                    "name": "Tool",
                    "distribution": "download",
                    "image_scope": "both",
                    "version_source": {"kind": "env", "key": "TOOL_VERSION"},
                    "inputs": ["TOOL_VERSION"],
                    "upstream": "https://example.com/tool",
                    "license_expression": "MIT",
                    "notice_treatment": "license required",
                    "notice_locations": ["components/tool/LICENSE"],
                    "trademark_policy": "descriptive use",
                    "download_url_markers": ["https://example.com/releases/"],
                    "sbom": {"status": "not-guaranteed", "reason": "binary"},
                }
            ],
        }
        with self.assertRaisesRegex(legal_inventory.InventoryError, "no source-locked legal document"):
            legal_inventory.validate_schema(inventory)

    def test_source_document_requires_https_and_exposed_location(self) -> None:
        component = {
            "id": "tool",
            "name": "Tool",
            "distribution": "download",
            "image_scope": "both",
            "version_source": {"kind": "env", "key": "TOOL_VERSION"},
            "inputs": ["TOOL_VERSION"],
            "upstream": "https://example.com/tool",
            "license_expression": "MIT",
            "notice_treatment": "license required",
            "notice_locations": ["components/tool/LICENSE"],
            "trademark_policy": "descriptive use",
            "sbom": {"status": "not-guaranteed", "reason": "binary"},
            "source_documents": [
                {
                    "path": "third_party/components/tool/NOTICE",
                    "url_template": "http://example.com/{version}/NOTICE",
                }
            ],
        }
        with self.assertRaisesRegex(legal_inventory.InventoryError, "must use HTTPS"):
            legal_inventory.validate_schema({"schema_version": 1, "components": [component]})

    def test_download_marker_rejects_query_and_fragment(self) -> None:
        component = {
            "id": "tool",
            "name": "Tool",
            "distribution": "download",
            "image_scope": "both",
            "version_source": {"kind": "env", "key": "TOOL_VERSION"},
            "inputs": ["TOOL_VERSION"],
            "upstream": "https://example.com/tool",
            "license_expression": "MIT",
            "notice_treatment": "license required",
            "notice_locations": ["components/tool/LICENSE"],
            "trademark_policy": "descriptive use",
            "sbom": {"status": "not-guaranteed", "reason": "binary"},
            "source_documents": [{
                "path": "third_party/components/tool/LICENSE",
                "url_template": "https://example.com/{version}/LICENSE",
            }],
        }
        for marker in (
            "https://example.com/releases/?channel=stable",
            "https://example.com/releases/#stable",
        ):
            with self.subTest(marker=marker):
                candidate = component | {"download_url_markers": [marker]}
                with self.assertRaisesRegex(legal_inventory.InventoryError, "query or fragment"):
                    legal_inventory.validate_schema({"schema_version": 1, "components": [candidate]})

    def test_new_component_refresh_remains_a_reviewable_git_diff(self) -> None:
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return b"new reviewed license candidate\n"

        class Opener:
            addheaders: list[tuple[str, str]] = []

            def open(self, _url: str, timeout: int):
                self.timeout = timeout
                return Response()

        component = {
            "id": "new-tool",
            "version_source": {"kind": "env", "key": "NEW_TOOL_VERSION"},
            "notice_locations": ["components/new-tool/LICENSE"],
            "source_documents": [{
                "path": "third_party/components/new-tool/LICENSE",
                "url_template": "https://vendor.example/new-tool/v{version}/LICENSE",
            }],
        }
        inventory = {"schema_version": 1, "components": [component]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            license_path = root / "third_party/components/new-tool/LICENSE"
            license_path.parent.mkdir(parents=True)
            license_path.write_text("old reviewed license\n", encoding="utf-8")
            lock_path = root / "third_party/sources.lock.json"
            lock_path.write_text(
                json.dumps({"schema_version": 1, "documents": [{
                    "component": "new-tool",
                    "git_blob_sha1": legal_inventory.git_blob_sha1(license_path.read_bytes()),
                    "path": "third_party/components/new-tool/LICENSE",
                    "url": "https://vendor.example/new-tool/v0.9/LICENSE",
                    "version": "0.9",
                }]}) + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)

            with mock.patch("legal_inventory.documents.urllib.request.build_opener", return_value=Opener()):
                documents.refresh_sources(root, inventory, {"NEW_TOOL_VERSION": "1.0"}, {})

            documents.validate_sources(root, inventory, {"NEW_TOOL_VERSION": "1.0"}, {})
            changed = subprocess.check_output(
                ["git", "diff", "--name-only"], cwd=root, text=True
            ).splitlines()
            self.assertEqual(
                changed,
                ["third_party/components/new-tool/LICENSE", "third_party/sources.lock.json"],
            )

    def test_unclaimed_version_input_fails_closed(self) -> None:
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
                'RUN curl "https://vendor.example/tool.tar.gz" -o tool.tar.gz\n', encoding="utf-8"
            )
            (root / "images/codex/Dockerfile").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(legal_inventory.InventoryError, "exactly one component"):
                legal_inventory.validate_discovery(root, inventory)

    def test_unclaimed_installer_command_fails_closed(self) -> None:
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
            (root / "images/base/Dockerfile").write_text("RUN python3 -m pip install new-tool==1.0\n", encoding="utf-8")
            (root / "images/codex/Dockerfile").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(legal_inventory.InventoryError, "installer command"):
                legal_inventory.validate_discovery(root, inventory)

    def test_invalid_apt_token_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dockerfile = Path(temporary) / "Dockerfile"
            dockerfile.write_text(
                "RUN apt-get install -y --no-install-recommends bash=$BASH_VERSION\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(legal_inventory.InventoryError, "unsupported APT package token"):
                legal_inventory.parse_apt_packages(dockerfile)

    def test_unknown_sbom_ecosystem_fails_closed(self) -> None:
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
                    "sbom": {"status": "covered-by-ecosystem"},
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
                            {"name": "bash", "externalRefs": [{"referenceLocator": "pkg:deb/ubuntu/bash@1"}]},
                            {"name": "mystery", "externalRefs": [{"referenceLocator": "pkg:gem/mystery@1"}]},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(legal_inventory.InventoryError, "unclassified package ecosystems: gem"):
                legal_inventory.reconcile_sboms(root, inventory, [f"base={sbom}", f"final={sbom}"])

    def test_final_sbom_must_include_base_package_identities(self) -> None:
        inventory = {
            "schema_version": 1,
            "components": [],
            "sbom_coverage": [{"owner": "packages", "purl_types": ["deb", "npm"]}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "images/base").mkdir(parents=True)
            (root / "images/base/Dockerfile").write_text(
                "RUN apt-get install -y --no-install-recommends \\\n        bash \\\n    && true\n", encoding="utf-8"
            )
            base = root / "base.json"
            final = root / "final.json"
            base.write_text(json.dumps({"packages": [
                {"externalRefs": [{"referenceLocator": "pkg:deb/ubuntu/bash@1"}]},
                {"externalRefs": [{"referenceLocator": "pkg:npm/tool@1"}]},
            ]}), encoding="utf-8")
            final.write_text(json.dumps({"packages": [
                {"externalRefs": [{"referenceLocator": "pkg:deb/ubuntu/bash@1"}]},
            ]}), encoding="utf-8")
            with self.assertRaisesRegex(legal_inventory.InventoryError, "final SBOM is missing"):
                legal_inventory.reconcile_sboms(root, inventory, [f"base={base}", f"final={final}"])


if __name__ == "__main__":
    unittest.main()
