#!/usr/bin/env python3
"""Bounded audit of the installed control plane; no general Dockerfile parser."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INTERPRETER = '/usr/local/lib/remote-dev/python'
# All Python programs installed in the final image are administrative. Host-only
# validators, publisher scripts and project/test tools are deliberately excluded.
PROGRAMS = {
    'remote-dev-agent-guidance.py': '/usr/local/bin/remote-dev-agent-guidance',
    'validate-codex-project-boundary.py': '/usr/local/bin/validate-codex-project-boundary',
    'remote-dev-codex-runtime.py': '/usr/local/bin/remote-dev-codex-runtime',
    'remote-dev-prepare-development-scratch.py': '/usr/local/bin/remote-dev-prepare-development-scratch',
    'remote-dev-context7.py': '/usr/local/lib/remote-dev/remote-dev-context7.py',
    'remote-dev-context7-device-login.py': '/usr/local/bin/remote-dev-context7-device-login',
    'remote-dev-antigravity-oauth.py': '/usr/local/bin/remote-dev-antigravity-oauth',
    'remote-dev-antigravity-picker.py': '/usr/local/bin/remote-dev-antigravity-picker',
    'remote-dev-antigravity-policy.py': '/usr/local/bin/remote-dev-antigravity-policy',
    'remote-dev-launcher.py': '/usr/local/bin/remote-dev-launcher',
}


class Contract(unittest.TestCase):
    def test_installed_inventory_and_binding(self):
        docker = (ROOT / 'images/codex/Dockerfile').read_text()
        copied = {}
        for line in docker.splitlines():
            if line.startswith('COPY ') and 'scripts/' in line and '.py ' in line:
                source, destination = line.split()[-2:]
                copied[Path(source).name] = destination
        self.assertEqual(copied, PROGRAMS)
        binding = docker.split("&& sed -i '1c\\#!" + INTERPRETER + " -I'", 1)[1].split('&&', 1)[0]
        self.assertEqual(set(binding.replace('\\', '').split()), set(PROGRAMS.values()))
        base = (ROOT / 'images/base/Dockerfile').read_text()
        self.assertIn('admin_python="$(realpath "$(mise which python)")"', base)
        self.assertIn('test "${admin_python%/*}" = "$MISE_DATA_DIR/installs/python/$PYTHON_VERSION/bin"', base)
        self.assertIn('ln -s "$admin_python" ' + INTERPRETER, base)

    def test_administrative_nested_invocations(self):
        for name in ('run-codex.sh', 'remote-dev-context7-entrypoint.sh',
                     'remote-dev-context7-device-login.py', 'lib/antigravity-runtime/integrity.sh'):
            text = (ROOT / 'scripts' / name).read_text()
            self.assertIn(INTERPRETER, text, name)
            self.assertNotIn('/opt/remote-dev/mise/shims/python', text, name)
            self.assertNotIn('python3 -', text, name)
        doctor = (ROOT / 'scripts/remote-dev-doctor.sh').read_text()
        self.assertIn('python --version', doctor)  # Project diagnostic remains project-aware.

    @unittest.skipUnless(Path('/opt/remote-dev/mise/shims/python3').exists(), 'real mise image shims unavailable')
    def test_real_untrusted_and_missing_mise_with_direct_status_and_verify(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory(dir='/tmp') as private:
            root = Path(temp)
            interpreter = root / 'image-python'
            interpreter.symlink_to(Path(sys.executable).resolve())
            home = Path(private) / 'home'; home.mkdir(mode=0o700)
            config = Path(private) / 'config'; config.mkdir(mode=0o700)
            bundled = root / 'codex'
            bundled.write_text('#!/bin/sh\nprintf "codex-cli 0.160.0\\n"\n')
            bundled.chmod(0o755)
            env = dict(os.environ, PATH='/opt/remote-dev/mise/shims:/usr/local/bin:/usr/bin:/bin',
                       MISE_STATE_DIR=str(root / 'state'), MISE_CACHE_DIR=str(root / 'cache'),
                       MISE_GLOBAL_CONFIG_FILE=str(root / 'empty.toml'),
                       MISE_NOT_FOUND_AUTO_INSTALL='false', MISE_NOT_FOUND_SYSTEM_FALLBACK='false',
                       CODEX_HOME=str(home), WORKSPACE=str(root / 'workspace'),
                       REMOTE_DEV_CODEX_BUNDLED_BINARY=str(bundled),
                       REMOTE_DEV_CODEX_RUNTIME_ROOT=str(root / 'runtime'))
            for key in ('MISE_TRUSTED_CONFIG_PATHS', 'MISE_TRUSTED_CONFIG_FILES'):
                env.pop(key, None)
            programs = {}
            for source in ('remote-dev-agent-guidance.py', 'remote-dev-codex-runtime.py'):
                text = (ROOT / 'scripts' / source).read_text()
                text = text.replace("Path('/usr/share/remote-dev/agent-rules/development-environment.md')",
                                    f'Path({str(ROOT / "config/agent-rules/development-environment.md")!r})')
                text = text.replace("Path('/root/.gemini/config')", f'Path({str(config)!r})')
                p = root / source
                p.write_text(f'#!{interpreter} -I\n' + text.split('\n', 1)[1]); p.chmod(0o555)
                programs[source] = p
            for kind, contents in (('neutral', ''),
                                   ('untrusted', '[env]\nPROBE = "{{ exec(command=\'false\') }}"\n'),
                                   ('missing', '[tools]\npython = "3.12.1"\n')):
                cwd = root / kind; cwd.mkdir()
                if contents:
                    (cwd / 'mise.toml').write_text(contents)
                    ordinary = subprocess.run(['python3', '--version'], cwd=cwd, env=env,
                                              capture_output=True, text=True)
                    self.assertNotEqual(ordinary.returncode, 0)
                    self.assertIn('not trusted' if kind == 'untrusted' else 'Tool not installed for shim', ordinary.stderr)
                state = root / 'state'
                before = {str(p): p.read_bytes() for p in state.rglob('*') if p.is_file()}
                for role in ('codex', 'antigravity'):
                    result = subprocess.run([str(programs['remote-dev-agent-guidance.py']), 'status', role],
                                            cwd=cwd, env=dict(env, REMOTE_DEV_ROLE=role), capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                for command in ('status', 'verify'):
                    result = subprocess.run([str(programs['remote-dev-codex-runtime.py']), command],
                                            cwd=cwd, env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(before, {str(p): p.read_bytes() for p in state.rglob('*') if p.is_file()})

    def test_direct_installed_entrypoints_ignore_hostile_lookup_and_pythonpath(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            interpreter = root / 'image-python'
            interpreter.symlink_to(Path(sys.executable).resolve())
            (root / 'mise.toml').write_text('[env]\nPROBE = "{{ exec(command=\'false\') }}"\n')
            fake = root / 'python3'
            fake.write_text('#!/bin/sh\nexit 91\n'); fake.chmod(0o755)
            (root / 'sitecustomize.py').write_text('raise SystemExit(92)\n')
            env = dict(os.environ, PATH=f'{root}:/usr/bin:/bin', PYTHONPATH=str(root), WEB_PASSWORD="", ALLOW_INSECURE_WEB="0")
            for source in PROGRAMS:
                with self.subTest(source=source):
                    program = root / source
                    text = (ROOT / 'scripts' / source).read_text()
                    program.write_text(text)
                    program.chmod(0o555)
                    subprocess.run(['sed', '-i', f'1c\\#!{interpreter} -I', str(program)], check=True)
                    result = subprocess.run([str(program), '--help'], cwd=root, env=env,
                                            capture_output=True, text=True, timeout=10)
                    if source == 'remote-dev-launcher.py':
                        self.assertEqual(result.returncode, 2, result.stderr)
                        self.assertIn('web authentication is not configured', result.stderr)
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
