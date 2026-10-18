#!/usr/bin/env python3
"""Offline wheel/license closure regressions, including embedded seed licenses."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cli_notices', ROOT / 'scripts/sync-python-cli-notices.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as wheel:
        for name, content in files.items():
            wheel.writestr(name, content)
    return output.getvalue()


class Notices(unittest.TestCase):
    def test_embedded_seed_license_exact_bytes(self):
        data = archive({'pkg.dist-info/licenses/': b'', 'pkg.dist-info/licenses/LICENSE': b'own\r\n',
                        'embed/seed.whl': archive({'seed.dist-info/LICENSE': b'seed\n'})})
        self.assertEqual(module.licenses(data), {'pkg.dist-info/licenses/LICENSE': b'own\r\n',
                         'embed/seed.whl/seed.dist-info/LICENSE': b'seed\n'})

    def test_zip_traversal_and_recursive_nesting_rejected(self):
        with self.assertRaises(ValueError):
            module.licenses(archive({'../LICENSE': b'bad'}))
        with self.assertRaises(ValueError):
            module.licenses(archive({'seed.whl': archive({'nested.whl': archive({'LICENSE': b'bad'})})}))

    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        shutil.copy2(ROOT / 'mise.lock', root / 'mise.lock')
        shutil.copytree(ROOT / '.mise', root / '.mise')
        target = root / 'third_party/components/python-clis'
        shutil.copytree(ROOT / 'third_party/components/python-clis', target)
        return root, target

    def check(self, root):
        with patch.object(module, 'ROOT', root), patch.object(sys, 'argv', ['sync-python-cli-notices']), \
                patch.object(module.urllib.request, 'urlopen', side_effect=AssertionError('passive network')):
            module.main()

    def test_real_evidence_check_is_offline(self):
        root, _ = self.fixture()
        self.check(root)

    def test_tampered_missing_and_symlinked_notices_rejected(self):
        for kind in ('tampered', 'missing', 'symlink'):
            root, target = self.fixture()
            manifest = json.loads((target / 'manifest.json').read_text())
            key, record = next(iter(manifest['packages'].items()))
            name = next(iter(record['notices']))
            path = target / key / name
            if kind == 'tampered':
                path.write_bytes(b'tampered')
            elif kind == 'missing':
                path.unlink()
            else:
                original = root / 'notice'
                path.rename(original)
                path.symlink_to(original)
            with self.assertRaises(ValueError):
                self.check(root)

    def test_wheel_record_mismatch_rejected(self):
        root, target = self.fixture()
        path = target / 'manifest.json'
        manifest = json.loads(path.read_text())
        next(iter(manifest['packages'].values()))['wheels'][0]['hash'] = 'sha256:' + '0' * 64
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            self.check(root)


if __name__ == '__main__':
    unittest.main()
