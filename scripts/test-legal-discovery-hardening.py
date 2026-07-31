#!/usr/bin/env python3
"""Regression tests for fail-closed legal discovery and in-image notice checks."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import legal_inventory  # noqa: E402
from legal_inventory.installer_scan import discovered_installer_instructions  # noqa: E402


class LegalDiscoveryHardeningTests(unittest.TestCase):
    def dockerfile_result(self, text: str, function):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "Dockerfile"
            path.write_text(text, encoding="utf-8")
            return function(path)

    def test_exec_form_downloads_are_discovered(self) -> None:
        self.assertEqual(
            self.dockerfile_result(
                'RUN ["curl", "https://vendor.example/tool", "-o", "/tmp/tool"]\n',
                legal_inventory.docker_download_urls,
            ),
            ["https://vendor.example/tool"],
        )
        self.assertEqual(
            self.dockerfile_result(
                'RUN ["bash", "-lc", "wget https://vendor.example/wrapped -O /tmp/wrapped"]\n',
                legal_inventory.docker_download_urls,
            ),
            ["https://vendor.example/wrapped"],
        )

    def test_every_apt_install_is_discovered(self) -> None:
        self.assertEqual(
            self.dockerfile_result(
                "RUN apt-get install -y bash\nRUN apt install --no-install-recommends jq\n",
                legal_inventory.parse_apt_packages,
            ),
            ["bash", "jq"],
        )

    def test_compound_downloads_fail_closed(self) -> None:
        for instruction in (
            "RUN if curl https://vendor.example/tool -o /tmp/tool; then true; fi\n",
            "RUN while true; do wget https://vendor.example/tool -O /tmp/tool; done\n",
            "RUN ! curl https://vendor.example/tool -o /tmp/tool\n",
        ):
            with self.subTest(instruction=instruction):
                with self.assertRaisesRegex(legal_inventory.InventoryError, "compound shell"):
                    self.dockerfile_result(instruction, legal_inventory.docker_download_urls)

    def test_npm_global_location_modes_are_discovered(self) -> None:
        for instruction in (
            'RUN npm install --location=global "tool@${TOOL_VERSION}"\n',
            'RUN npm --location global add "tool@${TOOL_VERSION}"\n',
            'RUN npm --global install "tool@${TOOL_VERSION}"\n',
        ):
            with self.subTest(instruction=instruction):
                self.assertEqual(
                    self.dockerfile_result(instruction, legal_inventory.global_npm_specs),
                    [("tool", "TOOL_VERSION")],
                )

    def test_run_heredocs_fail_closed(self) -> None:
        with self.assertRaisesRegex(legal_inventory.InventoryError, "heredocs are unsupported"):
            self.dockerfile_result(
                "RUN <<EOF\ncurl https://vendor.example/tool -o /tmp/tool\nEOF\n",
                legal_inventory.docker_download_urls,
            )

    def test_pip_global_options_are_discovered(self) -> None:
        for instruction in (
            "RUN pip --disable-pip-version-check install tool==1.0\n",
            "RUN python3 -m pip --disable-pip-version-check install tool==1.0\n",
        ):
            with self.subTest(instruction=instruction):
                self.assertTrue(self.dockerfile_result(instruction, discovered_installer_instructions))

    def test_git_global_options_do_not_hide_clone(self) -> None:
        for instruction in (
            "RUN git -c http.version=HTTP/1.1 clone https://vendor.example/repo\n",
            "RUN git --no-pager clone https://vendor.example/repo\n",
        ):
            with self.subTest(instruction=instruction):
                self.assertEqual(
                    self.dockerfile_result(instruction, legal_inventory.docker_download_urls),
                    ["https://vendor.example/repo"],
                )

    def test_effective_version_preflight_rejects_stale_license(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "scripts").mkdir()
            shutil.copy(
                SCRIPTS / "validate-third-party-inventory.sh",
                root / "scripts/validate-third-party-inventory.sh",
            )
            (root / "third_party/components/github-cli").mkdir(parents=True)
            (root / "images/base").mkdir(parents=True)
            (root / "images/codex").mkdir(parents=True)
            license_path = root / "third_party/components/github-cli/LICENSE"
            license_path.write_text("license\n", encoding="utf-8")
            blob = subprocess.check_output(["git", "hash-object", str(license_path)], text=True).strip()
            inventory = {
                "schema_version": 1,
                "components": [{
                    "id": "github-cli",
                    "inputs": ["GH_VERSION"],
                    "download_url_markers": ["https://github.com/cli/cli/releases/download/"],
                    "version_source": {"kind": "env", "key": "GH_VERSION"},
                }],
                "docker_arg_aliases": {},
            }
            source_lock = {
                "schema_version": 1,
                "documents": [{
                    "component": "github-cli",
                    "path": "third_party/components/github-cli/LICENSE",
                    "git_blob_sha1": blob,
                    "version": "1.0",
                }],
            }
            (root / "third_party/inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
            (root / "third_party/sources.lock.json").write_text(json.dumps(source_lock), encoding="utf-8")
            (root / "third_party/README.md").write_text(
                "generated from `third_party/inventory.json`\n", encoding="utf-8"
            )
            (root / "third_party/optional-agents.md").write_text("policy\n", encoding="utf-8")
            (root / "images/base/Dockerfile").write_text(
                "ARG GH_VERSION=1.0\nRUN curl https://github.com/cli/cli/releases/download/v1/tool\n",
                encoding="utf-8",
            )
            (root / "images/codex/Dockerfile").write_text("", encoding="utf-8")
            (root / "mise.lock").write_text("", encoding="utf-8")
            environment = os.environ | {"REMOTE_DEV_GH_VERSION": "2.0"}
            result = subprocess.run(
                ["bash", str(root / "scripts/validate-third-party-inventory.sh")],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("differs from reviewed legal sources", result.stderr)

    def test_image_notice_check_rejects_tampering_and_missing_copyright(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            notice_root = root / "notice"
            third_party = notice_root / "third_party"
            system_docs = root / "system-docs"
            component_license = third_party / "components/tool/LICENSE"
            component_license.parent.mkdir(parents=True)
            (third_party / "runtime/python").mkdir(parents=True)
            (third_party / "runtime/npm").mkdir(parents=True)
            (system_docs / "bash").mkdir(parents=True)
            (notice_root / "LICENSE").write_text("project\n", encoding="utf-8")
            (third_party / "README.md").write_text("inventory\n", encoding="utf-8")
            (third_party / "optional-agents.md").write_text("policy\n", encoding="utf-8")
            component_license.write_text("license\n", encoding="utf-8")
            (third_party / "runtime/python/NOTICE.dep").write_text("dependency\n", encoding="utf-8")
            (third_party / "runtime/npm/LICENSE").write_text("npm\n", encoding="utf-8")
            copyright_path = system_docs / "bash/copyright"
            copyright_path.write_text("bash\n", encoding="utf-8")
            packages = root / "packages.txt"
            packages.write_text("bash\n", encoding="utf-8")
            data = component_license.read_bytes()
            blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
            inventory = {
                "schema_version": 1,
                "components": [{
                    "id": "tool",
                    "image_scope": "both",
                    "inputs": ["TOOL_VERSION"],
                    "notice_locations": ["components/tool/LICENSE", "/usr/share/doc/<package>/copyright"],
                    "version_source": {"kind": "env", "key": "TOOL_VERSION"},
                }],
            }
            source_lock = {
                "schema_version": 1,
                "documents": [{
                    "component": "tool",
                    "path": "third_party/components/tool/LICENSE",
                    "git_blob_sha1": blob,
                    "version": "1.0",
                }],
            }
            (third_party / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
            (third_party / "sources.lock.json").write_text(json.dumps(source_lock), encoding="utf-8")
            (third_party / "BUILD-VERSIONS.env").write_text("TOOL_VERSION=1.0\n", encoding="utf-8")
            environment = os.environ | {
                "REMOTE_DEV_NOTICE_ROOT": str(notice_root),
                "REMOTE_DEV_SYSTEM_DOC_ROOT": str(system_docs),
                "REMOTE_DEV_INSTALLED_PACKAGES_FILE": str(packages),
            }
            command = ["bash", str(SCRIPTS / "remote-dev-notices.sh"), "--check"]
            self.assertEqual(subprocess.run(command, env=environment, check=False).returncode, 0)
            component_license.write_text("tampered\n", encoding="utf-8")
            self.assertNotEqual(
                subprocess.run(
                    command,
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode,
                0,
            )
            component_license.write_text("license\n", encoding="utf-8")
            copyright_path.unlink()
            self.assertNotEqual(
                subprocess.run(
                    command,
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode,
                0,
            )


if __name__ == "__main__":
    unittest.main()
