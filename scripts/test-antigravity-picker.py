#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

SOURCE = Path(
    os.environ.get(
        "REMOTE_DEV_ANTIGRAVITY_PICKER",
        Path(__file__).with_name("remote-dev-antigravity-picker.py"),
    )
)
LOADER = SourceFileLoader("antigravity_picker", str(SOURCE))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(MODULE)


class PickerTests(unittest.TestCase):
    def test_prompt_marker_accepts_wrapped_prompt_prefix(self) -> None:
        self.assertIsNotNone(
            MODULE._PROMPT_PATTERN.search(
                "Antigravity CLI\n> Describe your next engineering task here...\n"
            )
        )
        self.assertIsNone(MODULE._PROMPT_PATTERN.search("Authorization code: "))

    @mock.patch.object(MODULE, "_capture_pane", return_value="menu screen")
    def test_snapshot_returns_visible_screen_digest(self, capture) -> None:
        digest = MODULE.snapshot("%2")
        self.assertEqual(digest, MODULE._screen_digest("menu screen"))
        capture.assert_called_once_with("%2")

    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE, "_send_resume", return_value=True)
    @mock.patch.object(MODULE, "_capture_pane")
    @mock.patch.object(MODULE, "_process_alive", return_value=True)
    def test_watch_ignores_stale_prompt_then_sends_resume(
        self, alive, capture, send, sleep
    ) -> None:
        stale_screen = "> Describe an earlier task"
        fresh_screen = "Antigravity CLI ready\n> Describe your next engineering task here..."
        capture.side_effect = (stale_screen, fresh_screen)

        self.assertEqual(
            MODULE.watch("%7", 1234, MODULE._screen_digest(stale_screen)), 0
        )
        self.assertEqual(capture.call_count, 2)
        sleep.assert_called_once_with(MODULE._POLL_SECONDS)
        send.assert_called_once_with("%7")
        alive.assert_called_with(1234)

    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE, "_send_resume")
    @mock.patch.object(MODULE, "_capture_pane")
    @mock.patch.object(MODULE, "_process_alive", return_value=False)
    def test_watch_stops_without_input_when_child_exits(
        self, alive, capture, send, sleep
    ) -> None:
        self.assertEqual(MODULE.watch("%1", 99, "0" * 64), 0)
        capture.assert_not_called()
        send.assert_not_called()
        sleep.assert_not_called()

    @mock.patch.object(MODULE.subprocess, "run")
    def test_send_resume_uses_literal_tmux_arguments(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0)
        self.assertTrue(MODULE._send_resume("%3"))
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [
                ["tmux", "send-keys", "-t", "%3", "-l", "/resume"],
                ["tmux", "send-keys", "-t", "%3", "Enter"],
            ],
        )

    def test_main_rejects_untrusted_or_incomplete_arguments(self) -> None:
        with mock.patch.object(sys, "stderr"):
            self.assertEqual(
                MODULE.main(["watch", "--pane", "name;id", "--pid", "1"]), 2
            )
            self.assertEqual(
                MODULE.main(["watch", "--pane", "%1", "--pid", "0"]), 2
            )
            self.assertEqual(
                MODULE.main(["watch", "--pane", "%1", "--pid", "1"]), 2
            )
            self.assertEqual(
                MODULE.main(
                    [
                        "watch",
                        "--pane",
                        "%1",
                        "--pid",
                        "1",
                        "--baseline-sha256",
                        "NOT-A-DIGEST",
                    ]
                ),
                2,
            )
            self.assertEqual(
                MODULE.main(["snapshot", "--pane", "%1", "--pid", "1"]), 2
            )


if __name__ == "__main__":
    unittest.main()
