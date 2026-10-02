#!/usr/bin/env python3
"""Host-safe data validation and real consumer regressions; no vendor credentials."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'config/common-tool-baseline.txt'
LIB = ROOT / 'scripts/common-tool-baseline.sh'


class CommonBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manifest = self.root / 'baseline.txt'
        self.manifest.write_bytes(MANIFEST.read_bytes())

    def read(self):
        return subprocess.run(
            ['bash', '-c', 'source "$1"; remote_dev_read_common_tool_baseline "$2"',
             '_', str(LIB), str(self.manifest)], capture_output=True, text=True, timeout=5)

    def test_canonical_inventory_and_documentation(self):
        result = self.read()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, MANIFEST.read_text())
        commands = result.stdout.splitlines()
        self.assertEqual(len(commands), len(set(commands)))
        section = (ROOT / 'docs/tool-matrix.md').read_text().split('| Area | Public commands |')[1].split('## Role-specific')[0]
        self.assertEqual(set(re.findall(r'`([a-z][a-z0-9-]*)`', section)), set(commands))
        self.assertTrue(set(commands).isdisjoint({'codex', 'agy', 'tini', 'pytest', 'ruff', 'mypy', 'run-codex', 'run-antigravity'}))

    def test_reject_invalid_data_without_output_or_execution(self):
        marker = self.root / 'executed'
        for text in ('', '\n', 'bash\n\n', 'bash\nbash\n', 'bash\r\n', 'bash args\n', '/bin/bash\n', '# comment\n', f'bash\n$(touch {marker})\n', f'bash;touch {marker}\n'):
            with self.subTest(text=text):
                self.manifest.write_text(text)
                result = self.read()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertFalse(marker.exists())

    def test_reject_missing_symlink_and_fifo(self):
        self.manifest.unlink()
        self.assertNotEqual(self.read().returncode, 0)
        self.manifest.symlink_to(MANIFEST)
        self.assertNotEqual(self.read().returncode, 0)
        self.manifest.unlink()
        os.mkfifo(self.manifest)
        self.assertNotEqual(self.read().returncode, 0)

    def consumer(self, name):
        # Substitute only installed paths in a private copy; run the real script.
        text = (ROOT / 'scripts' / name).read_text()
        library = self.root / 'reader.sh'
        library.write_text(LIB.read_text().replace('/usr/share/remote-dev/common-tool-baseline.txt', str(self.manifest)))
        paths = self.root / 'antigravity-paths.sh'
        paths.write_text((ROOT / 'scripts/lib/antigravity-paths.sh').read_text().replace('/root', str(self.root)))
        replacements = {
            '/usr/local/lib/remote-dev/common-tool-baseline.sh': str(library),
            '/usr/local/lib/remote-dev/remote-dev-runtime.sh': str(ROOT / 'scripts/lib/remote-dev-runtime.sh'),
            '/usr/local/lib/remote-dev/antigravity-paths.sh': str(paths),
            '/usr/local/bin/remote-dev-codex-runtime': str(self.root / 'missing-codex-runtime'),
            '/usr/local/bin/remote-dev-context7': str(self.root / 'missing-context7'),
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        fixture = self.root / name
        fixture.write_text(text)
        # Exclude host vendor CLIs and mise shims; diagnostics may report missing
        # unrelated state, but must check every manifest entry without networking.
        env = dict(PATH='/usr/bin:/bin', HOME=str(self.root), WORKSPACE=str(self.root),
                   GH_CONFIG_DIR=str(self.root / 'gh'), CODEX_HOME=str(self.root / 'codex'),
                   REMOTE_DEV_CODEX_RUNTIME_ROOT=str(self.root / 'codex-runtime'))
        return ['bash', str(fixture)], env

    def test_base_verify_consumes_manifest_and_fails_closed(self):
        self.manifest.write_text('contract-probe\n')
        args, env = self.consumer('base-verify.sh')
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('MISSING: contract-probe', result.stderr)
        self.manifest.write_text('bash\n\n')
        result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('invalid command name', result.stderr)
        self.assertNotIn('MISSING:', result.stderr)

    def test_doctor_shared_baseline_role_separation_and_launcher_exemption(self):
        self.manifest.write_text(MANIFEST.read_text() + 'contract-probe\n')
        args, env = self.consumer('remote-dev-doctor.sh')
        for role in ('codex', 'antigravity', 'shell', 'launcher'):
            with self.subTest(role=role):
                result = subprocess.run(args, env=dict(env, REMOTE_DEV_ROLE=role, REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY='1'), capture_output=True, text=True, timeout=10)
                output = result.stdout
                if role == 'launcher':
                    self.assertNotIn('Public common baseline:', output)
                    self.assertNotIn('contract-probe', output)
                else:
                    baseline = output.split('Public common baseline:\n')[1].split('Remote Dev operational commands:')[0]
                    self.assertEqual([line.split()[0] for line in baseline.splitlines() if line.strip()], self.manifest.read_text().splitlines())
                    self.assertRegex(baseline, r'contract-probe\s+MISSING')
                    if role == 'codex':
                        self.assertIn('Codex commands:', output)
                        self.assertNotIn('Antigravity commands', output)
                    elif role == 'antigravity':
                        self.assertIn('Antigravity commands', output)
                        self.assertNotIn('Codex commands:', output)
                self.manifest.write_text('bash\n\n')
                invalid = subprocess.run(args, env=dict(env, REMOTE_DEV_ROLE=role, REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY='1'), capture_output=True, text=True, timeout=10)
                if role == 'launcher':
                    self.assertNotIn('common tool baseline', invalid.stderr)
                else:
                    self.assertNotEqual(invalid.returncode, 0)
                    self.assertIn('invalid command name', invalid.stderr)
                self.manifest.write_text(MANIFEST.read_text() + 'contract-probe\n')


if __name__ == '__main__':
    unittest.main()
