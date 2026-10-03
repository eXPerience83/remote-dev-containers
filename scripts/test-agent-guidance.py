#!/usr/bin/env python3
"""Synthetic native adapters, ownership, discovery and offline filesystem tests."""
import importlib.util
from importlib.machinery import SourceFileLoader
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('REMOTE_DEV_GUIDANCE_SOURCE', ROOT / 'scripts/remote-dev-agent-guidance.py'))
RULE = Path(os.environ.get('REMOTE_DEV_GUIDANCE_RULE', ROOT / 'config/agent-rules/development-environment.md'))
spec = importlib.util.spec_from_loader('guidance', SourceFileLoader('guidance', str(SOURCE)))
g = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = g
spec.loader.exec_module(g)


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'codex'
        self.home.mkdir(mode=0o700)
        self.agy = self.root / '.gemini/config'
        self.agy.mkdir(parents=True, mode=0o700)
        self.canonical = self.root / 'rule.md'
        self.canonical.write_bytes(RULE.read_bytes())
        self.rule = self.canonical.read_bytes()
        self.block = g.START + b'\n' + self.rule + g.END + b'\n'
        self.base = self.home / 'AGENTS.md'
        self.override = self.home / 'AGENTS.override.md'
        self.target = self.agy / 'rules' / g.ANTIGRAVITY_NAME
        self.repo = self.root / 'workspace/project'
        self.repo.mkdir(parents=True)
        (self.repo / 'AGENTS.md').write_bytes(b'private repository instructions\r\n')
        self.environment = patch.dict(os.environ, CODEX_HOME=str(self.home), WORKSPACE=str(self.root / 'workspace'), REMOTE_DEV_ROLE='codex')
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for name, value in [('CANONICAL', self.canonical), ('ANTIGRAVITY_CONFIG', self.agy)]:
            p = patch.object(g, name, value); p.start(); self.addCleanup(p.stop)
        network = patch.object(socket, 'socket', side_effect=AssertionError('guidance must be offline'))
        network.start(); self.addCleanup(network.stop)

    def run_guidance(self, provider='codex', reconcile=True):
        with patch.dict(os.environ, REMOTE_DEV_ROLE=provider):
            try:
                return g.run(provider, reconcile=reconcile)
            except g.GuidanceError as exc:
                return exc.state
            except (OSError, UnicodeError, ValueError):
                return 'unsafe'

    def test_missing_and_passive_status(self):
        self.assertEqual(self.run_guidance(reconcile=False), 'missing')
        self.assertFalse(self.base.exists())
        self.assertEqual(self.run_guidance(), 'current')
        self.assertEqual(self.base.read_bytes(), self.block)
        self.assertEqual(self.base.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.override.exists())
        self.assertEqual(self.run_guidance(reconcile=False), 'current')

    def test_preserve_user_bytes_and_idempotence(self):
        user = b'\r\n<!-- User comment -->\r\nUser instructions\r\n\t  '
        self.base.write_bytes(user)
        self.base.chmod(0o640)
        self.assertEqual(self.run_guidance(), 'current')
        first = self.base.read_bytes()
        inode = self.base.stat().st_ino
        self.assertEqual(first, self.block + user)
        self.assertEqual(self.run_guidance(), 'current')
        self.assertEqual(self.base.read_bytes(), first)
        self.assertEqual(self.base.stat().st_ino, inode)
        self.assertEqual(self.base.stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.repo / 'AGENTS.md').read_bytes(), b'private repository instructions\r\n')

    def test_user_override_precedence_and_inactive_file_preservation(self):
        self.run_guidance()
        previous = self.base.read_bytes()
        self.override.write_bytes(b'user override\r\n')
        self.assertEqual(self.run_guidance(), 'current')
        self.assertEqual(self.override.read_bytes(), self.block + b'user override\r\n')
        self.assertEqual(self.base.read_bytes(), previous)

    def test_whitespace_override_untouched(self):
        whitespace = '\r\n\t \u2003\u0085'.encode()
        self.override.write_bytes(whitespace)
        self.base.write_bytes(b'base user')
        self.assertEqual(self.run_guidance(), 'current')
        self.assertEqual(self.override.read_bytes(), whitespace)
        self.assertEqual(self.base.read_bytes(), self.block + b'base user')

    def test_managed_only_override_restores_native_fallback(self):
        whitespace = b'\r\n\t  \r\n'
        self.override.write_bytes(self.block + whitespace)
        self.base.write_bytes(b'base user')
        self.assertEqual(self.run_guidance(reconcile=False), 'stale')
        self.assertEqual(self.override.read_bytes(), self.block + whitespace)
        self.assertEqual(self.run_guidance(), 'current')
        self.assertEqual(self.override.read_bytes(), whitespace)
        self.assertEqual(self.base.read_bytes(), self.block + b'base user')
        self.assertEqual(self.run_guidance(reconcile=False), 'current')

    def test_override_only_block_no_base(self):
        self.override.write_bytes(self.block)
        self.run_guidance()
        self.assertEqual(self.override.read_bytes(), b'')
        self.assertEqual(self.base.read_bytes(), self.block)

    def test_canonical_update_only_changes_owned_span(self):
        before, after = b'User prefix\r\n', b'\r\nUser suffix \t'
        self.base.write_bytes(before + self.block + after)
        self.canonical.write_bytes(b'# Updated environment\nUse inherited `$TMPDIR`.\n')
        self.assertEqual(self.run_guidance(reconcile=False), 'stale')
        self.assertEqual(self.run_guidance(), 'current')
        expected = g.START + b'\n' + self.canonical.read_bytes() + g.END + b'\n'
        self.assertEqual(self.base.read_bytes(), before + expected + after)

    def test_crlf_managed_span_preserves_surrounding_bytes(self):
        old = self.block.replace(b'\n', b'\r\n')
        self.base.write_bytes(old + b'\r\nuser\r\n')
        self.run_guidance()
        self.assertEqual(self.base.read_bytes(), self.block + b'\r\nuser\r\n')

    def test_conflicting_markers_preserve_both_files(self):
        malformed = [self.block * 2, g.START + b'\npartial', g.END + b'\n',
                     b'prefix ' + g.START + b'\n' + g.END + b'\n',
                     g.START + b' extra\n' + g.END + b'\n',
                     g.END + b'\n' + g.START + b'\n']
        for data in malformed:
            for target in (self.base, self.override):
                with self.subTest(data=data, target=target.name):
                    self.base.write_bytes(b'base user')
                    self.override.write_bytes(b'')
                    target.write_bytes(data)
                    before = (self.base.read_bytes(), self.override.read_bytes())
                    self.assertEqual(self.run_guidance(), 'unowned-conflict')
                    self.assertEqual((self.base.read_bytes(), self.override.read_bytes()), before)

    def test_managed_override_and_bad_base_do_not_partially_edit(self):
        self.override.write_bytes(self.block + b' \r\n')
        self.base.write_bytes(g.START)
        self.assertEqual(self.run_guidance(), 'unowned-conflict')
        self.assertEqual(self.override.read_bytes(), self.block + b' \r\n')

    def test_unsafe_targets(self):
        for target in (self.base, self.override):
            for kind in ('symlink', 'dangling', 'fifo', 'encoding', 'oversize', 'mode', 'unreadable', 'hardlink'):
                with self.subTest(target=target.name, kind=kind):
                    self.base.unlink(missing_ok=True); self.override.unlink(missing_ok=True)
                    if kind == 'symlink': target.symlink_to(self.canonical)
                    elif kind == 'dangling': target.symlink_to(self.root / 'missing')
                    elif kind == 'fifo': os.mkfifo(target)
                    elif kind == 'encoding': target.write_bytes(b'\xff')
                    elif kind == 'oversize': target.write_bytes(b'x' * (g.MAX_BYTES + 1))
                    elif kind == 'hardlink': os.link(self.canonical, target)
                    else:
                        target.write_bytes(b'user'); target.chmod(0o666 if kind == 'mode' else 0)
                    before = target.lstat()
                    self.assertEqual(self.run_guidance(), 'unsafe')
                    self.assertEqual(g.identity(target.lstat()), g.identity(before))
                    self.assertEqual(self.canonical.read_bytes(), self.rule)
                    target.unlink()

    def test_directory_override_matches_native_skip_with_warning(self):
        self.override.mkdir()
        self.base.write_bytes(b'user')
        self.assertEqual(self.run_guidance(), 'unsafe')
        self.assertTrue(self.override.is_dir())
        self.assertEqual(self.base.read_bytes(), self.block + b'user')
        self.assertEqual(self.run_guidance(reconcile=False), 'unsafe')

    def test_native_recoverable_read_error_fallback(self):
        original = g.read_file
        def unreadable(fd, name, **kwargs):
            if name == 'AGENTS.override.md': raise PermissionError(13, 'synthetic read failure')
            return original(fd, name, **kwargs)
        with patch.object(g, 'read_file', side_effect=unreadable):
            self.assertEqual(self.run_guidance(), 'unsafe')
        self.assertEqual(self.base.read_bytes(), self.block)

    def test_rust_0160_trim_unicode_semantics(self):
        self.assertFalse(g.codex_nonempty('\u0085\u2003\u3000\t\r\n'.encode()))
        for c in range(0x1c, 0x20):
            self.override.write_bytes(bytes([c]))
            self.run_guidance()
            self.assertEqual(self.override.read_bytes(), self.block + bytes([c]))

    def test_unsafe_parents_and_project_home_rejection(self):
        self.home.rmdir(); self.home.symlink_to(self.repo)
        self.assertEqual(self.run_guidance(), 'unsafe')
        self.home.unlink(); self.home.mkdir(); self.home.chmod(0o777)
        self.assertEqual(self.run_guidance(), 'unsafe')
        with patch.dict(os.environ, CODEX_HOME=str(self.repo)):
            self.assertEqual(self.run_guidance(), 'unsafe')
        self.assertEqual((self.repo / 'AGENTS.md').read_bytes(), b'private repository instructions\r\n')

    def test_foreign_ownership(self):
        if os.geteuid() != 0: self.skipTest('chown requires root')
        self.base.write_bytes(b'user'); os.chown(self.base, 65534, 65534)
        self.assertEqual(self.run_guidance(), 'unsafe')
        self.assertEqual(self.base.read_bytes(), b'user')

    def test_native_operator_owned_private_mount_roots(self):
        if os.geteuid() != 0: self.skipTest('chown requires root')
        os.chown(self.home, 1001, 1001)
        self.base.write_bytes(b'operator user instructions')
        self.base.chmod(0o600)
        os.chown(self.base, 1001, 1001)
        # Only the fixed native root admits this owner; custom homes do not.
        self.assertEqual(self.run_guidance(), 'unsafe')
        with patch.object(g, 'CODEX_NATIVE_HOME', self.home):
            self.assertEqual(self.run_guidance(), 'current')
            self.assertEqual(self.home.stat().st_uid, 1001)
            self.assertEqual(self.base.read_bytes(), self.block + b'operator user instructions')
            self.home.chmod(0o755)
            self.assertEqual(self.run_guidance(), 'unsafe')
        os.chown(self.agy, 1001, 1001)
        self.assertEqual(self.run_guidance('antigravity'), 'current')
        self.assertEqual(self.agy.stat().st_uid, 1001)
        self.target.parent.chmod(0o700)
        os.chown(self.target.parent, 1001, 1001)
        os.chown(self.target, 1001, 1001)
        self.assertEqual(self.run_guidance('antigravity'), 'current')
        os.chown(self.target, 65534, 65534)
        self.assertEqual(self.run_guidance('antigravity'), 'unsafe')

    def test_atomic_replacement_detects_changed_target(self):
        self.base.write_bytes(b'user')
        with g.directory(self.home) as fd:
            old = g.read_file(fd, self.base.name)
            self.base.write_bytes(b'new user')
            with self.assertRaises(g.GuidanceError):
                g.atomic_write(fd, self.base.name, old, self.block)
        self.assertEqual(self.base.read_bytes(), b'new user')
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ['AGENTS.md'])

    def test_canonical_invalid_refused(self):
        for data in (b'', b' \n', b'\xff', g.START, b'x' * (g.MAX_RULE_BYTES + 1)):
            self.canonical.write_bytes(data)
            self.assertEqual(self.run_guidance(), 'unsafe')
            self.assertFalse(self.base.exists())

    def test_antigravity_format_update_and_unrelated_preservation(self):
        self.assertEqual(self.run_guidance('antigravity', False), 'missing')
        self.assertFalse(self.target.parent.exists())
        unrelated = [self.agy / 'settings.json', self.agy.parent / 'GEMINI.md',
                     self.agy.parent / 'AGENTS.md', self.agy / 'rules/user.md']
        self.target.parent.mkdir()
        for p in unrelated: p.write_bytes(b'private unrelated\r\n')
        self.assertEqual(self.run_guidance('antigravity'), 'current')
        self.assertEqual(self.target.relative_to(self.root).as_posix(), '.gemini/config/rules/remote-dev-development-environment.md')
        self.assertEqual(self.target.read_bytes(), g.FRONTMATTER + self.block)
        front = self.target.read_text().split('---\n')[1]
        self.assertEqual(front.splitlines(), ['trigger: always_on', 'description: "Remote Dev development environment guidance"'])
        first = self.target.stat()
        self.run_guidance('antigravity')
        self.assertEqual(self.target.stat(), first)
        self.canonical.write_bytes(b'Updated environment guidance\n')
        self.assertEqual(self.run_guidance('antigravity', False), 'stale')
        self.run_guidance('antigravity')
        self.assertIn(self.canonical.read_bytes(), self.target.read_bytes())
        for p in unrelated: self.assertEqual(p.read_bytes(), b'private unrelated\r\n')
        self.assertFalse(self.base.exists())

    def test_antigravity_unowned_and_malformed_collisions(self):
        self.target.parent.mkdir()
        for data in (b'user', self.block, g.FRONTMATTER + self.block * 2,
                     g.FRONTMATTER + g.START, g.FRONTMATTER + self.block + b'user\n'):
            self.target.write_bytes(data)
            self.assertEqual(self.run_guidance('antigravity'), 'unowned-conflict')
            self.assertEqual(self.target.read_bytes(), data)

    def test_antigravity_unsafe_objects_and_parent(self):
        self.target.parent.mkdir()
        self.target.symlink_to(self.canonical)
        self.assertEqual(self.run_guidance('antigravity'), 'unsafe')
        self.assertTrue(self.target.is_symlink()); self.target.unlink()
        os.mkfifo(self.target)
        self.assertEqual(self.run_guidance('antigravity'), 'unsafe'); self.target.unlink()
        self.target.write_bytes(b'user'); self.target.chmod(0o666)
        self.assertEqual(self.run_guidance('antigravity'), 'unsafe'); self.target.unlink()
        self.target.parent.rmdir(); self.target.parent.symlink_to(self.repo)
        self.assertEqual(self.run_guidance('antigravity'), 'unsafe')

    def test_role_mismatch_launcher_never_reads_provider_state(self):
        with patch.dict(os.environ, REMOTE_DEV_ROLE='launcher'), patch.object(g, 'directory', side_effect=AssertionError('private read')):
            self.assertEqual(g.run('codex', reconcile=True), 'unsupported')
            self.assertEqual(g.run('antigravity', reconcile=False), 'unsupported')
        with patch.dict(os.environ, REMOTE_DEV_ROLE='codex'):
            self.assertEqual(g.run('antigravity', reconcile=True), 'unsupported')
        with patch.dict(os.environ, REMOTE_DEV_ROLE='antigravity'):
            self.assertEqual(g.run('codex', reconcile=True), 'unsupported')


if __name__ == '__main__':
    unittest.main()
