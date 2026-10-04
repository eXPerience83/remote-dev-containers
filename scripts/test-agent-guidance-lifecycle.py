#!/usr/bin/env python3
"""Run the actual launch/Doctor scripts with synthetic vendor/state boundaries."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.executable_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.executable_temp.cleanup)
        self.bin = Path(self.executable_temp.name) / 'bin'; self.bin.mkdir()
        self.home = self.root / 'codex'; self.home.mkdir(mode=0o700)
        self.config = self.root / '.gemini/config'; self.config.mkdir(parents=True, mode=0o700)
        self.workspace = self.root / 'workspace'; self.project = self.workspace / 'project'
        self.project.mkdir(parents=True)
        (self.project / 'AGENTS.md').write_bytes(b'private project instructions\r\n')
        self.events = self.root / 'events'
        self.rule = ROOT / 'config/agent-rules/development-environment.md'
        # Exact manager CLI, substituting only immutable deployment paths.
        self.manager = self.bin / 'remote-dev-agent-guidance'
        text = (ROOT / 'scripts/remote-dev-agent-guidance.py').read_text()
        text = text.replace("Path('/usr/share/remote-dev/agent-rules/development-environment.md')", f'Path({str(self.rule)!r})')
        text = text.replace("Path('/root/.gemini/config')", f'Path({str(self.config)!r})')
        self.manager.write_text('#!' + sys.executable + '\n' + text.split('\n', 1)[1]); self.manager.chmod(0o755)
        self.stub('vendor', '''printf 'vendor\n' >> "$EVENTS"
if [[ "${EXPECT_GUIDANCE:-0}" == 1 ]]; then
  if [[ "$REMOTE_DEV_ROLE" == codex ]]; then
    grep -q 'BEGIN REMOTE DEV MANAGED' "$CODEX_HOME/AGENTS.md" || exit 91
  else
    grep -q '^trigger: always_on$' "$TEST_CONFIG/rules/remote-dev-development-environment.md" || exit 92
  fi
fi
exit "${VENDOR_STATUS:-0}"
''')
        self.stub('codex-runtime', 'printf "%s\\n" "$TEST_VENDOR"\n')
        self.stub('antigravity-runtime', '''case "$1" in
path) printf '%s\n' "$TEST_VENDOR" ;;
verify) printf 'runtime-verify\n' >> "$EVENTS" ;;
*) exit 0 ;;
esac
''')
        self.stub('validator', 'echo validator >> "$EVENTS"; exit "${VALIDATOR_STATUS:-0}"\n')
        self.stub('context7', 'exit 4\n')
        self.stub('policy', 'echo "Antigravity guarded compatibility: OK"\n')
        self.stub('secure', 'echo harden >> "$EVENTS"\n')
        self.stub('gh', 'exit 1\n')
        for name in ('codex', 'node', 'uv', 'remote-dev-version', 'remote-dev-antigravity', 'remote-dev-antigravity-policy'):
            self.stub(name, 'exit 0\n')
        self.env = dict(os.environ, PATH=f'{self.bin}:{Path(sys.executable).parent}:/usr/bin:/bin',
                        WORKSPACE=str(self.workspace), REMOTE_DEV_PROJECT='project', CODEX_HOME=str(self.home),
                        HOME=str(self.root), GH_CONFIG_DIR=str(self.root / 'gh'), EVENTS=str(self.events),
                        TEST_CONFIG=str(self.config), TEST_VENDOR=str(self.bin / 'vendor'),
                        REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY='1', REMOTE_DEV_ANTIGRAVITY_OAUTH_HELPER='0')
        replacements = {
            "/usr/local/lib/remote-dev/python": sys.executable,
            '/usr/local/bin/remote-dev-agent-guidance': str(self.manager),
            '/usr/local/lib/remote-dev/remote-dev-runtime.sh': str(ROOT / 'scripts/lib/remote-dev-runtime.sh'),
            '/usr/local/bin/codex': str(self.bin / 'vendor'),
            '/usr/local/bin/remote-dev-codex-runtime': str(self.bin / 'codex-runtime'),
            '/usr/local/bin/remote-dev-context7': str(self.bin / 'context7'),
            '/usr/local/bin/validate-codex-project-boundary': str(self.bin / 'validator'),
            '/usr/local/bin/remote-dev-antigravity-policy': str(self.bin / 'policy'),
            '/usr/local/bin/remote-dev-antigravity': str(self.bin / 'antigravity-runtime'),
            '/usr/local/bin/secure-persistent-state': str(self.bin / 'secure'),
            '/usr/local/lib/remote-dev/common-tool-baseline.sh': str(ROOT / 'scripts/common-tool-baseline.sh'),
        }
        paths = self.root / 'antigravity-paths.sh'
        paths.write_text((ROOT / 'scripts/lib/antigravity-paths.sh').read_text().replace('/root', str(self.root)))
        replacements['/usr/local/lib/remote-dev/antigravity-paths.sh'] = str(paths)
        for name in ('run-codex', 'run-antigravity', 'remote-dev-doctor'):
            text = (ROOT / 'scripts' / (name + '.sh')).read_text()
            for old, new in replacements.items(): text = text.replace(old, new)
            (self.bin / name).write_text(text); (self.bin / name).chmod(0o755)

    def stub(self, name, body):
        p = self.bin / name
        p.write_text('#!/bin/bash\nset -eu\n' + body); p.chmod(0o755)

    def run_script(self, name, role, *args, **env):
        return subprocess.run(['bash', str(self.bin / name), *args], cwd=self.project,
                              env=dict(self.env, REMOTE_DEV_ROLE=role, **env),
                              capture_output=True, text=True, timeout=10)

    @unittest.skipUnless(Path('/opt/remote-dev/mise/shims/python3').exists(), 'real mise shims unavailable')
    def test_doctor_from_real_untrusted_mise_project_for_both_roles(self):
        self.stub('context7', 'exit 0\n')
        for name in ('gh', '.local/bin', '.local/share/remote-dev/antigravity', '.gemini/antigravity-cli'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.project / 'mise.toml').write_text('[env]\nPROBE = "{{ exec(command=\'false\') }}"\n')
        context = dict(PATH=f'/opt/remote-dev/mise/shims:{self.bin}:/usr/local/bin:/usr/bin:/bin',
                       MISE_STATE_DIR=str(self.root / 'mise-state'),
                       MISE_CACHE_DIR=str(self.root / 'mise-cache'),
                       MISE_GLOBAL_CONFIG_FILE=str(self.root / 'no-global.toml'))
        env = dict(self.env, **context)
        env.pop('MISE_TRUSTED_CONFIG_PATHS', None)
        env.pop('MISE_TRUSTED_CONFIG_FILES', None)
        ordinary = subprocess.run(['python3', '--version'], cwd=self.project, env=env,
                                  capture_output=True, text=True)
        self.assertNotEqual(ordinary.returncode, 0)
        self.assertIn('not trusted', ordinary.stderr)
        before = self.snapshot()
        for role in ('codex', 'antigravity'):
            result = self.run_script('remote-dev-doctor', role, **context)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('guidance is degraded', result.stdout)
        self.assertEqual(before, self.snapshot())

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for root in (self.home, self.config, self.workspace)
                for p in root.rglob('*') if p.is_file()}

    def test_session_reconciles_before_vendor_and_preserves_exit_status(self):
        for role in ('codex', 'antigravity'):
            with self.subTest(role=role):
                result = self.run_script('run-' + role, role, EXPECT_GUIDANCE='1', VENDOR_STATUS='37')
                self.assertEqual(result.returncode, 37, result.stderr)
                self.assertIn(f'{role.capitalize()} Remote Dev guidance: current', result.stdout)
        self.assertIn('harden', self.events.read_text())
        self.assertEqual((self.project / 'AGENTS.md').read_bytes(), b'private project instructions\r\n')

    def test_resume_and_continue_reconcile(self):
        for role, args in [('codex', ['resume']), ('antigravity', ['--continue'])]:
            result = self.run_script('run-' + role, role, *args, EXPECT_GUIDANCE='1')
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_session_commands_reconcile(self):
        # The supported dispatcher sends these to the session TUI or exec engine.
        for args in ([], ['a prompt'], ['agents'], ['exec', 'a prompt'], ['e', 'a prompt'],
                     ['review'], ['resume'], ['fork'], ['--', 'doctor']):
            with self.subTest(args=args):
                target = self.home / 'AGENTS.md'
                target.unlink(missing_ok=True)
                result = self.run_script('run-codex', 'codex', *args, EXPECT_GUIDANCE='1')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(target.is_file())
                self.assertIn('Codex Remote Dev guidance: current', result.stdout)

    def test_codex_administrative_commands_do_not_reconcile(self):
        # Include hidden commands and aliases, and service modes that may later
        # receive work but do not start an agent session at CLI dispatch.
        commands = ('login', 'logout', 'mcp', 'plugin', 'app-server', 'remote-control',
                    'completion', 'update', 'doctor', 'sandbox', 'debug', 'execpolicy',
                    'apply', 'a', 'queue', 'archive', 'delete', 'migrate-rollouts',
                    'unarchive', 'cloud', 'cloud-tasks', 'responses-api-proxy',
                    'stdio-to-uds', 'exec-server', 'features', 'tcp-tunnel', 'help')
        for command in commands:
            with self.subTest(command=command):
                before = self.snapshot()
                result = self.run_script('run-codex', 'codex', command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.snapshot(), before)
                self.assertNotIn('Remote Dev guidance:', result.stdout)

    def test_codex_global_value_options_preserve_session_classification(self):
        options = (('--config', 'model=fixture'), ('-c', 'model=fixture'),
                   ('--cd', str(self.project)), ('-C', str(self.project)),
                   ('--model', 'fixture'), ('-m', 'fixture'), ('--image', 'fixture'),
                   ('-i', 'fixture'), ('--local-provider', 'ollama'),
                   ('--add-dir', str(self.project)), ('--enable', 'unified_exec'),
                   ('--disable', 'unified_exec'), ('--remote', 'unix://fixture'),
                   ('--remote-auth-token-env', 'FIXTURE_TOKEN'))
        for option, value in options:
            for command, active in (('login', False), ('exec', True)):
                with self.subTest(option=option, command=command):
                    (self.home / 'AGENTS.md').unlink(missing_ok=True)
                    before = self.snapshot()
                    result = self.run_script('run-codex', 'codex', option, value, command)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if active:
                        self.assertIn('Codex Remote Dev guidance: current', result.stdout)
                    else:
                        self.assertEqual(self.snapshot(), before)
                        self.assertNotIn('Remote Dev guidance:', result.stdout)

        for args in (['--disable', 'unified_exec', 'mcp', 'list'],
                     ['plugin', 'list'], ['apply', 'fixture-task'],
                     ['queue', '--thread', 'fixture-thread', '--message', 'fixture'],
                     ['cloud', 'exec', '--env', 'fixture-env', 'fixture'],
                     ['app-server', 'generate-json-schema'], ['remote-control', 'start'],
                     ['exec-server', 'forward', 'fixture'],
                     ['--enable', 'unified_exec', '--disable', 'fixture', 'plugin', 'list'],
                     ['--enable=unified_exec', 'login'],
                     ['--disable=unified_exec', 'mcp', 'list'],
                     ['--help', 'exec'], ['fork', '--help'], ['review', '--version']):
            with self.subTest(args=args):
                before = self.snapshot()
                result = self.run_script('run-codex', 'codex', *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.snapshot(), before)
                self.assertNotIn('Remote Dev guidance:', result.stdout)

    def test_cosmetic_conflict_warns_and_continues(self):
        (self.home / 'AGENTS.md').write_bytes(b'<!-- BEGIN REMOTE DEV MANAGED DEVELOPMENT ENVIRONMENT -->')
        (self.config / 'rules').mkdir()
        target = self.config / 'rules/remote-dev-development-environment.md'; target.write_bytes(b'unowned rule')
        before = self.snapshot()
        for role in ('codex', 'antigravity'):
            result = self.run_script('run-' + role, role, VENDOR_STATUS='37')
            self.assertEqual(result.returncode, 37, result.stderr)
            self.assertIn('WARNING:', result.stderr)
            self.assertIn('unowned-conflict', result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_passive_vendor_commands_and_policy_do_not_write(self):
        for role in ('codex', 'antigravity'):
            args_list = [['--version'], ['--help'], ['--print-policy'], ['help'], ['--continue', '--help']]
            if role == 'codex':
                args_list += [['login', 'status'], ['mcp', 'list'], ['features', 'list'],
                              ['-c', 'model=fixture', 'login', 'status'],
                              ['--model', 'fixture', 'mcp', 'list']]
            for args in args_list:
                with self.subTest(role=role, args=args):
                    before = self.snapshot()
                    result = self.run_script('run-' + role, role, *args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.snapshot(), before)
                    self.assertNotIn('Remote Dev guidance:', result.stdout)

    def test_project_validation_precedes_reconciliation(self):
        before = self.snapshot()
        result = self.run_script('run-codex', 'codex', VALIDATOR_STATUS='2')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn('vendor', self.events.read_text())

    def test_status_doctor_secret_free_and_passive_and_launcher_exempt(self):
        (self.home / 'AGENTS.md').write_bytes(b'SYNTHETIC_PRIVATE_INSTRUCTIONS')
        for role in ('codex', 'antigravity', 'launcher'):
            before = self.snapshot()
            result = self.run_script('remote-dev-doctor', role)
            self.assertEqual(self.snapshot(), before)
            self.assertNotIn('SYNTHETIC_PRIVATE_INSTRUCTIONS', result.stdout + result.stderr)
            if role == 'launcher': self.assertNotIn('Remote Dev guidance:', result.stdout)
            else: self.assertIn(f'{role.capitalize()} Remote Dev guidance: missing', result.stdout)
        (self.home / 'AGENTS.md').write_bytes(b'<!-- BEGIN REMOTE DEV MANAGED DEVELOPMENT ENVIRONMENT -->')
        result = self.run_script('remote-dev-doctor', 'codex')
        self.assertIn('Codex Remote Dev guidance: unowned-conflict', result.stdout)
        self.assertNotEqual(result.returncode, 0)

    def test_guidance_cli_status_and_role_rejection(self):
        before = self.snapshot()
        for role, provider, state in [('codex', 'codex', 'missing'), ('launcher', 'codex', 'unsupported'), ('codex', 'antigravity', 'unsupported')]:
            result = subprocess.run([str(self.manager), 'status', provider], env=dict(self.env, REMOTE_DEV_ROLE=role), capture_output=True, text=True, timeout=5)
            self.assertEqual(result.stdout, f'{provider.capitalize()} Remote Dev guidance: {state}\n')
        self.assertEqual(self.snapshot(), before)

    def test_no_startup_shell_launcher_or_menu_distribution(self):
        # All session routing is through existing wrappers. These entrypoints
        # must never call the manager independently (including Login shell).
        for name in ('start-remote-dev-web.sh', 'attach-remote-dev-tmux.sh', 'run-direct-session.sh',
                     'remote-dev-menu.sh', 'remote-dev-launcher.py', 'remote-dev-healthcheck.sh'):
            self.assertNotIn('remote-dev-agent-guidance', (ROOT / 'scripts' / name).read_text())

    def test_one_source_and_immutable_image_installation(self):
        dockerfile = (ROOT / 'images/codex/Dockerfile').read_text()
        self.assertIn('RUN install -d -o 0 -g 0 -m 0755 /usr/share/remote-dev/agent-rules', dockerfile)
        self.assertIn('COPY --chown=0:0 --chmod=0444 config/agent-rules/development-environment.md /usr/share/remote-dev/agent-rules/development-environment.md', dockerfile)
        self.assertIn('COPY --chown=0:0 --chmod=0555 scripts/remote-dev-agent-guidance.py /usr/local/bin/remote-dev-agent-guidance', dockerfile)
        self.assertEqual(list((ROOT / 'config/agent-rules').glob('*.md')), [self.rule])
        self.assertNotIn('urllib', self.manager.read_text())
        self.assertNotIn('subprocess', self.manager.read_text())


if __name__ == '__main__': unittest.main()
