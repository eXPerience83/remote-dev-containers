#!/usr/bin/env python3
"""Preserve license closure from the exact Linux wheels in the three CLI graphs."""
import argparse
import email
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message="invalid Python CLI notice evidence"):
    if not condition:
        raise ValueError(message)


def download(wheel):
    url = wheel['url']
    require(url.startswith('https://files.pythonhosted.org/packages/'))
    with urllib.request.urlopen(url, timeout=60) as response:
        require(response.geturl().startswith('https://files.pythonhosted.org/packages/'))
        data = response.read(64 * 1024 * 1024 + 1)
    require(len(data) <= 64 * 1024 * 1024)
    require('sha256:' + hashlib.sha256(data).hexdigest() == wheel['hash'])
    return data


def licenses(data, prefix='', depth=0):
    require(depth <= 1)
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        require(len(wheel.infolist()) <= 4096)
        require(sum(e.file_size for e in wheel.infolist()) <= 128 * 1024 * 1024)
        for entry in wheel.infolist():
            if entry.is_dir():
                continue
            path = PurePosixPath(entry.filename)
            require(not path.is_absolute() and '..' not in path.parts)
            require(entry.file_size <= 64 * 1024 * 1024)
            if path.name.lower().startswith(('license', 'copying', 'notice', 'authors')):
                result[prefix + entry.filename] = wheel.read(entry)
            # virtualenv redistributes seed wheels; preserve their notices too.
            if entry.filename.endswith('.whl'):
                result.update(licenses(wheel.read(entry), prefix + entry.filename + '/', depth + 1))
    return result


def expected_packages():
    lock = tomllib.loads((ROOT / 'mise.lock').read_text())
    packages = {}
    for tool in ('ruff', 'pytest', 'pre-commit'):
        ref = lock['tools']['pypi:' + tool][0]['uv']['path']
        graph = tomllib.loads((ROOT / ref / 'uv.lock').read_text())
        for package in graph['package']:
            if package['name'] == 'mise-pypi-tool-environment':
                continue
            key = package['name'] + '-' + package['version']
            wheels = package['wheels']
            selected = [w for w in wheels if w['url'].endswith('none-any.whl') or
                        ('manylinux' in w['url'] and ('x86_64' in w['url'] or 'aarch64' in w['url'])
                         and (package['name'] == 'ruff' or '-cp314-cp314-' in w['url']))]
            require(selected, key)
            packages[key] = (package, selected)
    return packages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    target = ROOT / 'third_party/components/python-clis'
    manifest_path = target / 'manifest.json'
    packages = expected_packages()
    if not args.write:
        manifest = json.loads(manifest_path.read_text())
        require(set(manifest['packages']) == set(packages))
        for key, (_, wheels) in packages.items():
            record = manifest['packages'][key]
            require(record['wheels'] == wheels and record['notices'] and record['license'], key)
            for name, digest in record['notices'].items():
                require(not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts)
                path = target / key / name
                require(not path.is_symlink() and path.is_file())
                require(hashlib.sha256(path.read_bytes()).hexdigest() == digest)
        print('Python CLI wheel/license closure: OK')
        return
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'packages': {}}
    manifest = {'schema_version': 1, 'packages': {}}
    for key, (package, wheels) in sorted(packages.items()):
        chunks = []
        license_expression = None
        for index, artifact in enumerate(wheels):
            data = download(artifact)
            with zipfile.ZipFile(io.BytesIO(data)) as wheel:
                metadata = next(n for n in wheel.namelist() if n.endswith('.dist-info/METADATA'))
                msg = email.message_from_bytes(wheel.read(metadata))
                license_expression = msg.get('License-Expression') or msg.get('License') or '; '.join(
                    c for c in msg.get_all('Classifier', []) if c.startswith('License ::'))
            extracted = licenses(data)
            require(extracted, key)
            for name, content in sorted(extracted.items()):
                # Preserve exact upstream bytes with explicit artifact/member labels.
                label = artifact['url'].rsplit('/', 1)[1] + '/' + name
                chunks.append(('\n===== ' + label + ' =====\n').encode() + content)
        combined = b'\n'.join(chunks)
        path = target / key / 'NOTICES.txt'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(combined)
        notices = {'NOTICES.txt': hashlib.sha256(combined).hexdigest()}
        manifest['packages'][key] = {'name': package['name'], 'version': package['version'],
            'license': license_expression, 'wheels': wheels, 'notices': notices}
        print(key, license_expression)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    # Remove only previously generated notice files after publishing replacements.
    for key, record in previous['packages'].items():
        for name in record['notices']:
            path = target / key / name
            require(path.resolve().is_relative_to(target.resolve()))
            if name not in manifest['packages'].get(key, {}).get('notices', {}):
                path.unlink(missing_ok=True)
    for directory in sorted((p for p in target.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()


if __name__ == '__main__':
    main()
