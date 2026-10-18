#!/usr/bin/env python3
"""Bounded contract for the known Build AMD64 comparison steps; no YAML dependency."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
GUARD = "github.event_name == 'workflow_dispatch' && inputs.compare_images == true"
COMPARISON = (
    'Measure PR2 before/after image delta',
    'Record before base spdx-json evidence',
    'Record before base json evidence',
    'Record before runtime spdx-json evidence',
    'Record before runtime json evidence',
)
UPLOAD = 'Upload optional image comparison reports'
MANDATORY = (
    'Build and smoke test', 'Reproduce publisher mise isolation fixture',
    'Verify canonical and legacy local aliases', 'Verify bundled notices',
    'Generate base image SPDX SBOM', 'Generate Remote Dev image SPDX SBOM',
    'Scan base image for critical vulnerabilities',
    'Scan Remote Dev image for critical vulnerabilities',
    'Enforce no fixable critical vulnerabilities',
)


def steps(text):
    """Read only this repository's fixed named-step layout."""
    result = {}
    for block in text.split('      - name: ')[1:]:
        name, body = block.split('\n', 1)
        if name in result:
            raise AssertionError('duplicate named step: ' + name)
        result[name] = body
    return result


def condition(body):
    lines = [line.strip()[4:] for line in body.splitlines() if line.startswith('        if: ')]
    if len(lines) > 1:
        raise AssertionError('duplicate step guard')
    return lines[0] if lines else None


def validate(text):
    assert '''  workflow_dispatch:
    inputs:
      compare_images:
        description: "Build reference images and collect optional size/security comparisons"
        type: boolean
        required: false
        default: false
''' in text, 'comparison input must be a default-off optional boolean'
    blocks = steps(text)
    for name in COMPARISON:
        assert condition(blocks[name]) == GUARD, name
    assert condition(blocks[UPLOAD]) == 'always() && ' + GUARD
    for name in MANDATORY:
        assert condition(blocks[name]) is None, 'mandatory gate became conditional: ' + name
    assert condition(blocks['Upload security and SBOM reports']) == 'always()'
    assert "fetch-depth: ${{ " + GUARD + " && '0' || '1' }}" in text
    assert 'run: bash scripts/measure-tooling-image-delta.sh' in blocks[COMPARISON[0]]
    expected = (
        ('remote-dev-base:pr2-before', 'spdx-json', 'sbom-before-base.spdx.json'),
        ('remote-dev-base:pr2-before', 'json', 'trivy-before-base.json'),
        ('remote-dev:pr2-before', 'spdx-json', 'sbom-before-runtime.spdx.json'),
        ('remote-dev:pr2-before', 'json', 'trivy-before-runtime.json'),
    )
    for name, (image, fmt, output) in zip(COMPARISON[1:], expected, strict=True):
        for line in (f'image-ref: {image}', f'format: {fmt}', f'output: {output}'):
            assert line in blocks[name], (name, line)
    for path in ('sbom-before-*.spdx.json', 'trivy-before-*.json', 'tooling-image-delta.json'):
        assert path in blocks[UPLOAD]
        assert path not in blocks['Upload security and SBOM reports']
    assert 'if-no-files-found: ignore' in blocks[UPLOAD]
    assert 'name: image-comparison-reports' in blocks[UPLOAD]
    for path in ('sbom-base.spdx.json', 'sbom-remote-dev.spdx.json', 'trivy-base.json', 'trivy-remote-dev.json'):
        assert path in blocks['Upload security and SBOM reports']
    assert 'scripts/enforce-trivy-gate.sh' in blocks[MANDATORY[-1]]
    assert '"base image:trivy-base.json"' in blocks[MANDATORY[-1]]
    assert '"Remote Dev image:trivy-remote-dev.json"' in blocks[MANDATORY[-1]]
    # No reference image consumer or measurement may escape the guarded blocks.
    for name, body in blocks.items():
        if ':pr2-before' in body or 'measure-tooling-image-delta.sh' in body:
            assert name in COMPARISON, name


class ComparisonContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / '.github/workflows/build-amd64.yml').read_text()

    def test_committed_workflow_and_event_matrix(self):
        validate(self.text)
        # The exact asserted Actions expression uses a typed boolean, not string truthiness.
        for event, enabled, expected in (
            ('pull_request', False, False), ('pull_request', True, False),
            ('push', False, False), ('push', True, False),
            ('workflow_dispatch', None, False), ('workflow_dispatch', False, False),
            ('workflow_dispatch', True, True),
            ('workflow_dispatch', 'true', False), ('workflow_dispatch', 'false', False),
        ):
            with self.subTest(event=event, enabled=enabled):
                self.assertEqual(event == 'workflow_dispatch' and enabled is True, expected)
        # Comparison failure must still allow evidence upload; default runs never do.
        self.assertEqual(condition(steps(self.text)[UPLOAD]), 'always() && ' + GUARD)

    def test_every_comparison_guard_is_required(self):
        for name in (*COMPARISON, UPLOAD):
            body = steps(self.text)[name]
            guard = condition(body)
            changed = body.replace('        if: ' + guard + '\n', '', 1)
            with self.subTest(step=name), self.assertRaises(AssertionError):
                validate(self.text.replace(body, changed, 1))

    def test_default_on_and_missing_event_guard_rejected(self):
        for text in (self.text.replace('default: false', 'default: true', 1),
                     self.text.replace(GUARD, 'inputs.compare_images == true')):
            with self.assertRaises(AssertionError):
                validate(text)

    def test_optional_paths_cannot_leak_into_normal_upload(self):
        body = steps(self.text)['Upload security and SBOM reports']
        with self.assertRaises(AssertionError):
            validate(self.text.replace(body, body.replace('          path: |', '          path: |\n            tooling-image-delta.json'), 1))

    def test_optional_missing_files_are_quiet(self):
        with self.assertRaises(AssertionError):
            validate(self.text.replace('if-no-files-found: ignore', 'if-no-files-found: warn'))

    def test_mandatory_candidate_gates_stay_unconditional(self):
        for name in MANDATORY:
            with self.subTest(step=name), self.assertRaises(AssertionError):
                validate(self.text.replace('      - name: ' + name + '\n', '      - name: ' + name + '\n        if: ' + GUARD + '\n'))


if __name__ == '__main__':
    unittest.main()
