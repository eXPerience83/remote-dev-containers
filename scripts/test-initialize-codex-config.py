#!/usr/bin/env python3
"""Offline initialization, interruption and persistence acceptance."""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import shutil
import subprocess
import fcntl
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('guidance', ROOT / 'scripts/remote-dev-agent-guidance.py')
g = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = g
spec.loader.exec_module(g)


CHILD_AUDIT = """import sys, runpy
from pathlib import Path
log = Path(sys.argv.pop(1))
def deny_network(event, args):
    if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
        log.write_text(event)
        raise RuntimeError('initializer attempted network or external execution')
sys.addaudithook(deny_network)
"""


def initialize(home):
    os.environ.update(CODEX_HOME=str(home), REMOTE_DEV_ROLE='codex')
    return g.initialize_codex()


class Initialization(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.home.mkdir(mode=0o700)
        env = patch.dict(os.environ, CODEX_HOME=str(self.home), REMOTE_DEV_ROLE='codex')
        env.start(); self.addCleanup(env.stop)
        network = patch.object(socket, 'socket', side_effect=AssertionError('offline'))
        network.start(); self.addCleanup(network.stop)

    def test_empty_and_removed_and_disabled(self):
        self.assertEqual(list(self.home.iterdir()), [])
        g.initialize_codex()
        config = self.home / 'config.toml'
        self.assertEqual(config.read_bytes(), g.INITIAL_CONFIG)
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        config.write_text('[mcp_servers.openaiDeveloperDocs]\nenabled=false\n')
        g.initialize_codex()
        self.assertIn('false', config.read_text())
        config.unlink()
        g.initialize_codex()
        self.assertFalse(config.exists())

    def test_existing(self):
        for name in ('config.toml', 'AGENTS.md', 'auth.json'):
            with self.subTest(name=name):
                for p in self.home.iterdir(): shutil.rmtree(p) if p.is_dir() else p.unlink()
                target = self.home / name
                target.write_bytes(b'private synthetic state')
                g.initialize_codex()
                self.assertEqual(target.read_bytes(), b'private synthetic state')
                self.assertEqual((self.home / 'config.toml').exists(), name == 'config.toml')

    def test_recovery_pending_and_staged(self):
        for staged in (False, True):
            with self.subTest(staged=staged):
                for p in self.home.iterdir(): shutil.rmtree(p) if p.is_dir() else p.unlink()
                (self.home / g.INITIAL_MARKER).mkdir(mode=0o700)
                if staged: (self.home / g.INITIAL_MARKER / g.INITIAL_STAGE).write_bytes(g.INITIAL_CONFIG)
                g.initialize_codex()
                self.assertEqual((self.home / 'config.toml').read_bytes(), g.INITIAL_CONFIG)

    def test_interruption_at_each_write(self):
        for boundary in (1, 2):
            with self.subTest(boundary=boundary):
                for p in self.home.iterdir():
                    shutil.rmtree(p) if p.is_dir() else p.unlink()
                original = g.atomic_write
                calls = 0
                def interrupt(*args):
                    nonlocal calls
                    calls += 1
                    if calls == boundary:
                        raise OSError('synthetic interruption')
                    return original(*args)
                with patch.object(g, 'atomic_write', side_effect=interrupt):
                    with self.assertRaises(OSError): g.initialize_codex()
                g.initialize_codex()
                self.assertEqual((self.home / 'config.toml').read_bytes(), g.INITIAL_CONFIG)

    def test_pending_decision_survives_new_guidance(self):
        """Provider-created state after interruption must not cancel provisioning."""
        (self.home / g.INITIAL_MARKER).mkdir(mode=0o700)
        (self.home / 'AGENTS.md').write_text('user guidance\n')
        g.initialize_codex()
        self.assertEqual((self.home / 'config.toml').read_bytes(), g.INITIAL_CONFIG)
        self.assertEqual((self.home / 'AGENTS.md').read_text(), 'user guidance\n')

    def test_completed_transaction_removes_link(self):
        """A completed marker must not retain a second link to private config."""
        tx = self.home / g.INITIAL_MARKER
        tx.mkdir(mode=0o700)
        (tx / 'done').write_bytes(b'done\n')
        stage = tx / g.INITIAL_STAGE
        stage.write_bytes(b'private synthetic config')
        os.link(stage, self.home / 'config.toml')
        g.initialize_codex()
        self.assertFalse(stage.exists())
        self.assertEqual((self.home / 'config.toml').stat().st_nlink, 1)

    def test_lock_contention_is_bounded(self):
        """A stalled initializer cannot block web startup indefinitely."""
        fd = os.open(self.home, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            with patch.object(g.time, 'monotonic', side_effect=[0, 3]):
                with self.assertRaises(g.GuidanceError) as caught:
                    g.initialize_codex()
            self.assertEqual(caught.exception.state, 'busy')
            self.assertEqual(list(self.home.iterdir()), [])
        finally:
            os.close(fd)

    def test_concurrent_user_config_wins(self):
        original = g.os.link
        def create_user_config(*args, **kwargs):
            (self.home / 'config.toml').write_text('user = true\n')
            return original(*args, **kwargs)
        with patch.object(g.os, 'link', side_effect=create_user_config):
            g.initialize_codex()
        self.assertEqual((self.home / 'config.toml').read_text(), 'user = true\n')

    def test_crash_after_publication(self):
        (self.home / g.INITIAL_MARKER).mkdir(mode=0o700)
        stage = self.home / g.INITIAL_MARKER / g.INITIAL_STAGE
        stage.write_bytes(g.INITIAL_CONFIG)
        os.link(stage, self.home / 'config.toml')
        g.initialize_codex()
        self.assertFalse(stage.exists())
        self.assertEqual((self.home / 'config.toml').stat().st_nlink, 1)

    def test_roles_and_unsafe_marker(self):
        with patch.dict(os.environ, REMOTE_DEV_ROLE='antigravity'):
            self.assertEqual(g.initialize_codex(), 'unsupported')
        self.assertEqual(list(self.home.iterdir()), [])
        (self.home / g.INITIAL_MARKER).symlink_to('/dev/null')
        with self.assertRaises((g.GuidanceError, OSError)): g.initialize_codex()

    def test_concurrent(self):
        with ProcessPoolExecutor(4, mp_context=multiprocessing.get_context('fork')) as pool:
            self.assertEqual(list(pool.map(initialize, [self.home] * 8)), ['current'] * 8)
        self.assertEqual((self.home / 'config.toml').read_bytes(), g.INITIAL_CONFIG)

    def test_actual_first_startup(self):
        executable_temp = tempfile.TemporaryDirectory()
        self.addCleanup(executable_temp.cleanup)
        bin_dir = Path(executable_temp.name) / 'bin'
        bin_dir.mkdir()
        library = bin_dir / 'runtime'
        library.write_text("remote_dev_resolve_role() { echo codex; }\n"
                           "remote_dev_resolve_start_mode() { echo menu; }\n"
                           "remote_dev_default_tmux_session() { echo test; }\n"
                           "remote_dev_validate_workspace_root() { echo \"$1\"; }\n"
                           "remote_dev_prepare_development_environment() { :; }\n")
        helper = bin_dir / 'guidance'
        audit_log = bin_dir / 'network-attempt'
        helper.write_text(f'#!{sys.executable}\n' + CHILD_AUDIT +
                          f'runpy.run_path({str(ROOT / "scripts/remote-dev-agent-guidance.py")!r}, run_name="__main__")\n')
        for name, code in [('secure', ':'), ('git', ':'), ('gh', 'exit 1'),
                           ('ttyd', 'test -f "$CODEX_HOME/config.toml" && test -f "$CODEX_HOME/.remote-dev-initial-config-v1/done"')]:
            (bin_dir / name).write_text('#!/bin/sh\n' + code + '\n')
        for file in bin_dir.iterdir(): file.chmod(0o700)
        startup = bin_dir / 'startup'
        source = (ROOT / 'scripts/start-remote-dev-web.sh').read_text()
        source = source.replace('/usr/local/lib/remote-dev/remote-dev-runtime.sh', str(library))
        source = source.replace('/usr/local/bin/secure-persistent-state', str(bin_dir / 'secure'))
        source = source.replace('/usr/local/bin/remote-dev-agent-guidance', str(helper) + " " + str(audit_log))
        source = source.replace('/root/.ssh', str(bin_dir / 'ssh'))
        startup.write_text(source)
        env = dict(os.environ, PATH=str(bin_dir) + ':' + os.environ['PATH'],
                   GH_CONFIG_DIR=str(bin_dir / 'gh-state'), GIT_CONFIG_GLOBAL=str(bin_dir / 'git-state/config'),
                   ALLOW_INSECURE_WEB='1')
        self.assertEqual(list(self.home.iterdir()), [])
        result = subprocess.run(['bash', str(startup)], env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(audit_log.exists(), "child initializer attempted network/external execution")
        self.assertEqual((self.home / 'config.toml').read_bytes(), g.INITIAL_CONFIG)

    def test_child_audit_detects_attempts(self):
        """Positive controls prove subprocess instrumentation actually detects attempts."""
        for code in ('import socket; socket.socket()',
                     'import subprocess; subprocess.run(["curl", "https://example.invalid"])'):
            log = self.home / 'attempt'
            log.unlink(missing_ok=True)
            result = subprocess.run([sys.executable, '-c', CHILD_AUDIT + code, str(log)],
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(log.exists())

    @unittest.skipUnless(os.geteuid() == 0, 'synthetic host ownership requires root')
    def test_native_skipped_home_owner_allowance(self):
        """Native mounts accept the host owner; custom homes keep stricter checks."""
        skipped = self.home / g.INITIAL_SKIPPED
        skipped.mkdir(mode=0o700)
        os.chown(self.home, 12345, 12345)
        os.chown(skipped, 12345, 12345)
        with patch.object(g, 'CODEX_NATIVE_HOME', self.home):
            self.assertEqual(g.initialize_codex(), 'existing')
        with self.assertRaises(g.GuidanceError):
            g.initialize_codex()

    def test_startup_order(self):
        source = (ROOT / 'scripts/start-remote-dev-web.sh').read_text()
        self.assertLess(source.index('initialize codex'), source.index('gh auth status'))
        self.assertLess(source.index('initialize codex'), source.index('exec "${cmd[@]}"'))


if __name__ == '__main__': unittest.main()
