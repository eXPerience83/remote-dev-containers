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

    def test_command_substitution_downloads_are_discovered(self) -> None:
        self.assertEqual(
            self.dockerfile_result(
                'RUN token="$(curl https://vendor.example/substituted)"\n',
                legal_inventory.docker_download_urls,
            ),
            ["https://vendor.example/substituted"],
        )
        self.assertEqual(
            self.dockerfile_result(
                'RUN test "$(npm --version)" = "1.0.0"\n',
                legal_inventory.global_npm_specs,
            ),
            [],
        )

    def test_legacy_backtick_substitutions_fail_closed(self) -> None:
        with self.assertRaisesRegex(legal_inventory.InventoryError, "backtick"):
            self.dockerfile_result(
                "RUN result=`curl https://vendor.example/legacy`\n",
                legal_inventory.docker_download_urls,
            )

    def test_docker_instruction_keywords_are_case_insensitive(self) -> None:
        self.assertEqual(
            self.dockerfile_result(
                "run curl https://vendor.example/run -o /tmp/run\n"
                "aDd https://vendor.example/add /tmp/add\n",
                legal_inventory.docker_download_urls,
            ),
            ["https://vendor.example/add", "https://vendor.example/run"],
        )

    def test_dynamic_add_sources_fail_closed(self) -> None:
        with self.assertRaisesRegex(legal_inventory.InventoryError, "variable-based ADD"):
            self.dockerfile_result(
                "ARG TOOL_URL\nADD ${TOOL_URL} /usr/local/bin/tool\n",
                legal_inventory.docker_download_urls,
            )

    def test_external_build_stages_fail_closed(self) -> None:
        with self.assertRaisesRegex(legal_inventory.InventoryError, "external FROM image"):
            self.dockerfile_result(
                "FROM ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST}\n"
                "FROM vendor/tool:1.0 AS tool\n"
                "COPY --from=tool /usr/local/bin/tool /usr/local/bin/tool\n",
                legal_inventory.docker_download_urls,
            )

        self.assertEqual(
            self.dockerfile_result(
                "FROM ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST} AS builder\n"
                "FROM builder AS final\n"
                "COPY --from=builder /tool /usr/local/bin/tool\n",
                legal_inventory.docker_download_urls,
            ),
            [],
        )
        with self.assertRaisesRegex(legal_inventory.InventoryError, "external COPY --from"):
            self.dockerfile_result(
                "FROM ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST}\n"
                "COPY --from=vendor/tool:1.0 /tool /usr/local/bin/tool\n",
                legal_inventory.docker_download_urls,
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
            'RUN npm --global true install "tool@${TOOL_VERSION}"\n',
            'RUN npm --global=true install "tool@${TOOL_VERSION}"\n',
            'RUN npm --audit false --global true install "tool@${TOOL_VERSION}"\n',
            'RUN npm install --global true "tool@${TOOL_VERSION}"\n',
            'RUN npm --global false --global true install "tool@${TOOL_VERSION}"\n',
            'RUN npm installT --location=global "tool@${TOOL_VERSION}"\n',
        ):
            with self.subTest(instruction=instruction):
                self.assertEqual(
                    self.dockerfile_result(instruction, legal_inventory.global_npm_specs),
                    [("tool", "TOOL_VERSION")],
                )

    def test_local_npm_installs_fail_closed(self) -> None:
        for instruction in (
            "RUN npm install lodash@4.17.21\n",
            "RUN npm ci\n",
            "RUN npm clean-install\n",
            "RUN npm install-test lodash@4.17.21\n",
            "RUN npm it lodash@4.17.21\n",
            "RUN npm install-ci-test\n",
            "RUN npm cit\n",
            "RUN npm clean-install-test\n",
            "RUN npm sit\n",
            "RUN npm installTest lodash@4.17.21\n",
            "RUN npm install-t lodash@4.17.21\n",
            "RUN npm installCiTest\n",
            "RUN npm --loglevel warn install lodash@4.17.21\n",
            "RUN npm --loglevel=warn install lodash@4.17.21\n",
            "RUN npm --audit false install lodash@4.17.21\n",
            "RUN npm --audit=false install lodash@4.17.21\n",
            "RUN npm --global false install lodash@4.17.21\n",
            "RUN npm --global=false install lodash@4.17.21\n",
            "RUN npm --global true --global false install lodash@4.17.21\n",
            "RUN npm install --audit false lodash@4.17.21\n",
            "RUN npm install --global false lodash@4.17.21\n",
        ):
            with self.subTest(instruction=instruction):
                with self.assertRaisesRegex(legal_inventory.InventoryError, "local npm installs"):
                    self.dockerfile_result(instruction, legal_inventory.global_npm_specs)

    def test_ambiguous_npm_precommand_options_fail_closed(self) -> None:
        with self.assertRaisesRegex(legal_inventory.InventoryError, "unsupported npm option"):
            self.dockerfile_result(
                "RUN npm -L warn install lodash@4.17.21\n",
                legal_inventory.global_npm_specs,
            )

    def test_invalid_attached_npm_boolean_fails_closed(self) -> None:
        with self.assertRaisesRegex(legal_inventory.InventoryError, "invalid Boolean value"):
            self.dockerfile_result(
                "RUN npm --global=maybe install lodash@4.17.21\n",
                legal_inventory.global_npm_specs,
            )

    def test_non_install_npm_commands_are_ignored(self) -> None:
        for instruction in (
            "RUN npm --version\n",
            "RUN npm c get registry\n",
            "RUN npm test\n",
        ):
            with self.subTest(instruction=instruction):
                self.assertEqual(
                    self.dockerfile_result(instruction, legal_inventory.global_npm_specs),
                    [],
                )

    def test_run_heredocs_fail_closed(self) -> None:
        with self.assertRaisesRegex(legal_inventory.InventoryError, "heredocs are unsupported"):
            self.dockerfile_result(
                "RUN <<EOF\ncurl https://vendor.example/tool -o /tmp/tool\nEOF\n",
                legal_inventory.docker_download_urls,
            )

    def test_onbuild_triggers_fail_closed_case_insensitively(self) -> None:
        for instruction in (
            "ONBUILD RUN curl https://vendor.example/tool -o /tmp/tool\n",
            "onbuild add https://vendor.example/tool /usr/local/bin/tool\n",
            'OnBuild RUN ["curl", "https://vendor.example/tool", "-o", "/tmp/tool"]\n',
        ):
            with self.subTest(instruction=instruction):
                with self.assertRaisesRegex(legal_inventory.InventoryError, "ONBUILD is unsupported"):
                    self.dockerfile_result(instruction, legal_inventory.docker_download_urls)

    def test_download_markers_use_https_origin_and_path_boundaries(self) -> None:
        marker = "https://github.com/cli/cli/releases/download/"
        self.assertTrue(
            legal_inventory.download_marker_matches(
                marker,
                "https://GitHub.COM/cli/cli/releases/download/v1/file",
            )
        )
        for url in (
            "https://mirror.example/fetch?source=https://github.com/cli/cli/releases/download/",
            "https://mirror.example/https://github.com/cli/cli/releases/download/v1/file",
            "https://github.com/cli/cli/releases/download-evil/file",
        ):
            with self.subTest(url=url):
                self.assertFalse(legal_inventory.download_marker_matches(marker, url))

    def test_download_ownership_rejects_unowned_and_ambiguous_urls(self) -> None:
        def validate(url: str, markers: list[tuple[str, str]]) -> None:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "images/base").mkdir(parents=True)
                (root / "images/codex").mkdir(parents=True)
                (root / "images/base/Dockerfile").write_text(
                    f"FROM ubuntu:${{UBUNTU_VERSION}}@${{UBUNTU_DIGEST}}\nRUN curl {url} -o /tmp/tool\n",
                    encoding="utf-8",
                )
                (root / "images/codex/Dockerfile").write_text("FROM ${BASE_IMAGE}\n", encoding="utf-8")
                components: dict[str, list[str]] = {}
                for component, marker in markers:
                    components.setdefault(component, []).append(marker)
                inventory = {
                    "components": [
                        {"id": component, "download_url_markers": component_markers}
                        for component, component_markers in components.items()
                    ]
                }
                legal_inventory.validate_discovery(root, inventory)

        validate(
            "https://GitHub.COM/cli/cli/releases/download/v1/file",
            [("github-cli", "https://github.com/cli/cli/releases/download/")],
        )
        for url in (
            "https://mirror.example/fetch?source=https://github.com/cli/cli/releases/download/",
            "https://mirror.example/https://github.com/cli/cli/releases/download/v1/file",
            "https://github.com/cli/cli/releases/download-evil/file",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(legal_inventory.InventoryError, "exactly one component"):
                    validate(url, [("github-cli", "https://github.com/cli/cli/releases/download/")])
        with self.assertRaisesRegex(legal_inventory.InventoryError, "exactly one component"):
            validate(
                "https://github.com/cli/cli/releases/download/v1/file",
                [
                    ("github-cli", "https://github.com/cli/cli/releases/"),
                    ("github-cli-mirror", "https://github.com/cli/cli/releases/download/"),
                ],
            )
        with self.assertRaisesRegex(legal_inventory.InventoryError, "exactly one component"):
            validate(
                "https://github.com/cli/cli/releases/download/v1/file",
                [
                    ("github-cli", "https://github.com/cli/cli/releases/"),
                    ("github-cli", "https://github.com/cli/cli/releases/download/"),
                ],
            )

    def test_build_helper_acquisition_fails_closed_but_validation_is_allowed(self) -> None:
        def validate(script_text: str) -> None:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "images/base").mkdir(parents=True)
                (root / "images/codex").mkdir(parents=True)
                (root / "scripts").mkdir()
                (root / "scripts/install-new-tool.sh").write_text(script_text, encoding="utf-8")
                (root / "images/base/Dockerfile").write_text(
                    "FROM ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST}\n"
                    "COPY scripts/install-new-tool.sh /tmp/install-new-tool.sh\n"
                    "RUN bash /tmp/install-new-tool.sh\n",
                    encoding="utf-8",
                )
                (root / "images/codex/Dockerfile").write_text("FROM ${BASE_IMAGE}\n", encoding="utf-8")
                legal_inventory.validate_discovery(root, {"components": [{"id": "project"}]})

        with self.assertRaisesRegex(legal_inventory.InventoryError, "build helper.*curl"):
            validate("#!/usr/bin/env bash\ncurl https://vendor.example/tool -o /tmp/tool\n")
        validate("#!/usr/bin/env bash\nset -euo pipefail\nprintf 'validation only\\n'\n")

    def test_build_helper_interpreter_downloads_fail_closed(self) -> None:
        for command in (
            "python3 -c \"import urllib.request; urllib.request.urlretrieve('https://vendor.example/tool')\"",
            "node -e \"fetch('https://vendor.example/tool')\"",
            "busybox wget https://vendor.example/tool",
        ):
            with self.subTest(command=command):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    (root / "images/base").mkdir(parents=True)
                    (root / "images/codex").mkdir(parents=True)
                    (root / "scripts").mkdir()
                    (root / "scripts/helper.sh").write_text(f"#!/bin/sh\n{command}\n", encoding="utf-8")
                    (root / "images/base/Dockerfile").write_text(
                        "FROM ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST}\n"
                        "COPY scripts/helper.sh /helper.sh\nRUN sh /helper.sh\n",
                        encoding="utf-8",
                    )
                    (root / "images/codex/Dockerfile").write_text("FROM ${BASE_IMAGE}\n", encoding="utf-8")
                    with self.assertRaisesRegex(legal_inventory.InventoryError, "build helper"):
                        legal_inventory.validate_discovery(root, {"components": [{"id": "project"}]})

    def test_inline_interpreter_downloads_and_dynamic_helpers_fail_closed(self) -> None:
        for instruction in (
            "RUN python3 -c \"import urllib.request; urllib.request.urlretrieve('https://vendor.example/tool')\"\n",
            "RUN node -e \"fetch('https://vendor.example/tool')\"\n",
            "RUN busybox wget https://vendor.example/tool\n",
        ):
            with self.subTest(instruction=instruction):
                with self.assertRaisesRegex(legal_inventory.InventoryError, "network acquisition|busybox wget"):
                    self.dockerfile_result(instruction, legal_inventory.docker_download_urls)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "images/base").mkdir(parents=True)
            (root / "images/codex").mkdir(parents=True)
            (root / "images/base/Dockerfile").write_text(
                "FROM ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST}\nRUN bash $GENERATED_INSTALLER\n",
                encoding="utf-8",
            )
            (root / "images/codex/Dockerfile").write_text("FROM ${BASE_IMAGE}\n", encoding="utf-8")
            with self.assertRaisesRegex(legal_inventory.InventoryError, "cannot be resolved"):
                legal_inventory.validate_discovery(root, {"components": [{"id": "project"}]})

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

    def test_image_notice_check_rejects_tampering_lock_drift_and_missing_copyright(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            notice_root = root / "notice"
            third_party = notice_root / "third_party"
            system_docs = root / "system-docs"
            component_license = third_party / "components/tool/LICENSE"
            component_notice = third_party / "components/tool/NOTICE"
            component_license.parent.mkdir(parents=True)
            (third_party / "runtime/python").mkdir(parents=True)
            (third_party / "runtime/npm").mkdir(parents=True)
            (system_docs / "bash").mkdir(parents=True)
            (notice_root / "LICENSE").write_text("project\n", encoding="utf-8")
            (third_party / "README.md").write_text("inventory\n", encoding="utf-8")
            (third_party / "optional-agents.md").write_text("policy\n", encoding="utf-8")
            component_license.write_text("license\n", encoding="utf-8")
            component_notice.write_text("notice\n", encoding="utf-8")
            (third_party / "runtime/python/NOTICE.dep").write_text("dependency\n", encoding="utf-8")
            (third_party / "runtime/npm/LICENSE").write_text("npm\n", encoding="utf-8")
            copyright_path = system_docs / "bash/copyright"
            copyright_path.write_text("bash\n", encoding="utf-8")
            packages = root / "packages.txt"
            packages.write_text("bash\n", encoding="utf-8")

            def blob(path: Path) -> str:
                data = path.read_bytes()
                return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()

            inventory = {
                "schema_version": 1,
                "components": [{
                    "id": "tool",
                    "image_scope": "both",
                    "inputs": ["TOOL_VERSION"],
                    "notice_locations": [
                        "components/tool/LICENSE",
                        "components/tool/NOTICE",
                        "/usr/share/doc/<package>/copyright",
                    ],
                    "source_documents": [
                        {
                            "path": "third_party/components/tool/LICENSE",
                            "url_template": "https://vendor.example/{version}/LICENSE",
                        },
                        {
                            "path": "third_party/components/tool/NOTICE",
                            "url_template": "https://vendor.example/{version}/NOTICE",
                        },
                    ],
                    "version_source": {"kind": "env", "key": "TOOL_VERSION"},
                }],
            }
            source_lock = {
                "schema_version": 1,
                "documents": [
                    {
                        "component": "tool",
                        "path": "third_party/components/tool/LICENSE",
                        "git_blob_sha1": blob(component_license),
                        "version": "1.0",
                    },
                    {
                        "component": "tool",
                        "path": "third_party/components/tool/NOTICE",
                        "git_blob_sha1": blob(component_notice),
                        "version": "1.0",
                    },
                ],
            }
            inventory_path = third_party / "inventory.json"
            source_lock_path = third_party / "sources.lock.json"
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            source_lock_path.write_text(json.dumps(source_lock), encoding="utf-8")
            (third_party / "BUILD-VERSIONS.env").write_text("TOOL_VERSION=1.0\n", encoding="utf-8")
            environment = os.environ | {
                "PATH": "/usr/bin:/bin",
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

            truncated_lock = {"schema_version": 1, "documents": source_lock["documents"][:1]}
            source_lock_path.write_text(json.dumps(truncated_lock), encoding="utf-8")
            self.assertNotEqual(
                subprocess.run(
                    command,
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode,
                0,
            )
            source_lock_path.write_text(json.dumps(source_lock), encoding="utf-8")

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
