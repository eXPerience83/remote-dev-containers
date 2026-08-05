#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_HELPER = ROOT / "scripts" / "remote-dev-antigravity-oauth.py"
INSTALLED_HELPER = Path("/usr/local/bin/remote-dev-antigravity-oauth")
MODULE_PATH = Path(
    os.environ.get(
        "REMOTE_DEV_ANTIGRAVITY_OAUTH_HELPER",
        str(INSTALLED_HELPER if INSTALLED_HELPER.is_file() else REPOSITORY_HELPER),
    )
)
SPEC = importlib.util.spec_from_file_location("remote_dev_antigravity_oauth", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load OAuth helper from {MODULE_PATH}")
OAUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OAUTH)

VALID_URL = (
    "https://accounts.google.com/o/oauth2/auth?access_type=offline&client_id=client.example"
    "&code_challenge=abc123&redirect_uri=https%3A%2F%2Fantigravity.google%2Foauth-callback"
    "&response_type=code&scope=openid&state=state123"
)


class OAuthHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        OAUTH.STOP_REQUESTED = False

    def test_extracts_soft_wrapped_google_url(self) -> None:
        capture = f"""
Your browser should open automatically. If not:

{VALID_URL[:82]}
{VALID_URL[82:164]}
{VALID_URL[164:]}

If you aren't automatically redirected, paste the authorization code below:
"""
        self.assertEqual(OAUTH.extract_oauth_url(capture), VALID_URL)

    def test_extracts_latest_url_and_ignores_stale_history(self) -> None:
        newer = VALID_URL.replace("state123", "state456")
        capture = (
            f"{VALID_URL}\nIf you aren't automatically redirected\n"
            f"{newer}\nIf you aren't automatically redirected\n"
        )
        self.assertEqual(OAUTH.extract_oauth_url(capture), newer)

    def test_rejects_non_google_and_host_confusion_urls(self) -> None:
        for url in (
            VALID_URL.replace("https://", "http://", 1),
            VALID_URL.replace("accounts.google.com", "accounts.google.com.evil.example"),
            VALID_URL.replace("accounts.google.com", "evil.example@accounts.google.com"),
            VALID_URL.replace("/o/oauth2/auth", "/not-oauth"),
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    OAUTH.validate_oauth_url(url)

    def test_url_file_must_be_private_regular_file(self) -> None:
        url_file = OAUTH.create_url_file(VALID_URL)
        try:
            self.assertEqual(OAUTH.read_url_file(url_file), VALID_URL)
            self.assertEqual(os.stat(url_file).st_mode & 0o777, 0o600)
        finally:
            url_file.unlink(missing_ok=True)

        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            target = Path(directory) / "target"
            target.write_text(VALID_URL, encoding="utf-8")
            os.chmod(target, 0o600)
            link = Path("/tmp") / f"remote-dev-antigravity-oauth.symlink-{os.getpid()}"
            link.unlink(missing_ok=True)
            link.symlink_to(target)
            try:
                with self.assertRaises(OSError):
                    OAUTH.read_url_file(link)
            finally:
                link.unlink(missing_ok=True)

    def test_popup_uses_one_compact_osc8_link(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            OAUTH.render_popup(VALID_URL, wait_for_enter=False)
        rendered = output.getvalue()
        self.assertIn("OPEN GOOGLE SIGN-IN", rendered)
        self.assertIn(f"\x1b]8;;{VALID_URL}\x1b\\", rendered)
        self.assertIn("paste the code into Antigravity", rendered)

    def test_watcher_baselines_history_before_showing_new_url(self) -> None:
        newer = VALID_URL.replace("state123", "state456")
        baseline = f"{VALID_URL}\nIf you aren't automatically redirected\n"
        changed = f"{newer}\nIf you aren't automatically redirected\n"
        ready = Path("/tmp") / f".remote-dev-antigravity-oauth-ready.{os.getpid()}"
        ready.unlink(missing_ok=True)
        shown_path: Path | None = None

        def fake_popup(path: Path) -> int:
            nonlocal shown_path
            shown_path = path
            self.assertEqual(OAUTH.read_url_file(path), newer)
            return 0

        try:
            with mock.patch.object(
                OAUTH, "capture_pane", side_effect=[baseline, baseline, changed]
            ), mock.patch.object(OAUTH, "show_popup", side_effect=fake_popup), mock.patch.object(
                OAUTH.time, "sleep", return_value=None
            ):
                self.assertEqual(OAUTH.watch("%7", ready), 0)
            self.assertTrue(ready.is_file())
            self.assertIsNotNone(shown_path)
            assert shown_path is not None
            self.assertFalse(shown_path.exists())
        finally:
            ready.unlink(missing_ok=True)

    def test_popup_command_never_places_url_in_process_arguments(self) -> None:
        url_file = OAUTH.create_url_file(VALID_URL)
        try:
            completed = mock.Mock(returncode=0)
            with mock.patch.object(OAUTH.subprocess, "run", return_value=completed) as run:
                self.assertEqual(OAUTH.show_popup(url_file), 0)
            arguments = run.call_args.args[0]
            self.assertNotIn(VALID_URL, " ".join(arguments))
            self.assertIn("display-popup", arguments)
            self.assertIn(str(url_file), arguments[-1])
        finally:
            url_file.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
