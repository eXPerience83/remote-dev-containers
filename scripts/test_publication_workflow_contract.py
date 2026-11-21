#!/usr/bin/env python3
"""Canonical GitHub Actions step metadata and artifact path regressions."""
from __future__ import annotations

import unittest

from publication_workflow_contract import active_upload_paths, step_metadata


class PublicationStepContract(unittest.TestCase):
    def test_canonical_mandatory_run(self):
        block = (
            "      - name: Critical gate\n"
            "        env:\n"
            "          REPORT: scan.json\n"
            "        run: |\n"
            "          set -euo pipefail\n"
            "          true\n"
        )
        self.assertEqual(step_metadata(block), {"env": "", "run": "|"})
        for injection in (
            '        "if": false\n', "        'if': false\n", "        if: false\n",
            '        "continue-on-error": true\n',
            "        continue-on-error: true\n",
            "        <<: *unsafe\n", "        if: always()\n",
            "        if: false # expected if: always()\n",
        ):
            with self.subTest(injection=injection):
                with self.assertRaises(AssertionError):
                    step_metadata(block.replace("        env:\n", injection + "        env:\n"))

    def test_promotion_requires_exact_fresh_condition(self):
        block = (
            "      - name: Promote\n"
            "        if: steps.promotion_guard.outputs.mode == 'fresh'\n"
            "        run: |\n"
            "          set -euo pipefail\n"
        )
        self.assertEqual(
            step_metadata(block, expected_if="steps.promotion_guard.outputs.mode == 'fresh'")["if"],
            "steps.promotion_guard.outputs.mode == 'fresh'",
        )
        for mutation in (
            '        "if": steps.promotion_guard.outputs.mode == \'fresh\'\n',
            "        if: false\n", "        if: always()\n", "",
            "        if: steps.promotion_guard.outputs.mode == 'fresh' # ignore\n",
        ):
            with self.subTest(mutation=mutation):
                altered = block.replace(
                    "        if: steps.promotion_guard.outputs.mode == 'fresh'\n", mutation)
                with self.assertRaises(AssertionError):
                    step_metadata(altered,
                                  expected_if="steps.promotion_guard.outputs.mode == 'fresh'")

    def test_active_artifact_paths(self):
        upload = (
            "      - name: Upload\n"
            "        if: always()\n"
            "        uses: actions/upload-artifact@f00\n"
            "        with:\n"
            "          name: reports\n"
            "          path: |\n"
            "            sbom-base.spdx.json\n"
            "            sbom-runtime.spdx.json\n"
            "          retention-days: 14\n"
        )
        self.assertEqual(active_upload_paths(upload),
                         ("sbom-base.spdx.json", "sbom-runtime.spdx.json"))
        altered = upload.replace("            sbom-runtime.spdx.json\n",
                                "            # sbom-runtime.spdx.json\n")
        self.assertEqual(active_upload_paths(altered), ("sbom-base.spdx.json",))
        for bad in (
            upload.replace("          path: |", '          "path": |'),
            upload.replace("          path: |", "          path: >"),
            upload.replace("            sbom-runtime.spdx.json\n",
                           "            sbom-base.spdx.json\n"),
            upload.replace("        if: always()", '        "if": false'),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(AssertionError):
                    active_upload_paths(bad)


if __name__ == "__main__":
    unittest.main()
