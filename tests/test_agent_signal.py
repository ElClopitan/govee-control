"""Tests for agent_signal.py using unittest.mock to fake govee functions."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import agent_signal
import arbiter
import govee
from helpers import StateDirMixin


class TestSignalNeedsInput(StateDirMixin, unittest.TestCase):
    """Test the needs-input command."""

    def setUp(self):
        """Create a temp config and state directory for each test."""
        super().setUp()
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "signal": {
                "color": "#ff6a00",
                "brightness": 100,
                "blink": False,
            },
        }
        self.config_path.write_text(json.dumps(self.config))

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_needs_input_saves_state_and_sets_color(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """needs-input saves current state and sets signal colour."""
        # Mock status responses
        mock_status.side_effect = [
            {"msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}},
            {"msg": {"data": {"on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}}}},
        ]

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_needs_input(args)

        # Verify state was saved
        self.assertTrue(arbiter.signal_file().exists())
        saved = json.loads(arbiter.signal_file().read_text())
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]["ip"], "192.168.1.50")
        self.assertEqual(saved[0]["brightness"], 50)

        # Verify signal colour was set
        self.assertEqual(mock_color.call_count, 2)
        # Parse #ff6a00 -> (255, 106, 0)
        self.assertEqual(mock_color.call_args_list[0][0][1:], (255, 106, 0))

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_second_needs_input_keeps_first_saved_state(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """Calling needs-input twice does not overwrite the saved original state."""
        # First call: save state
        mock_status.side_effect = [
            {"msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}},
            {"msg": {"data": {"on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}}}},
        ]

        args1 = mock.Mock()
        args1.command = "needs-input"
        args1.config = str(self.config_path)
        args1.dry_run = False
        agent_signal.cmd_needs_input(args1)

        # Reset mocks
        mock_status.reset_mock()
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()

        # Second call: should NOT call status again (no saved file overwrite)
        args2 = mock.Mock()
        args2.command = "needs-input"
        args2.config = str(self.config_path)
        args2.dry_run = False
        agent_signal.cmd_needs_input(args2)

        # Status should not have been called on second invocation
        mock_status.assert_not_called()

        # Saved state should still have original values
        saved = json.loads(arbiter.signal_file().read_text())
        self.assertEqual(saved[0]["brightness"], 50)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_status_exception_does_not_crash(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """govee.status raising an exception does not crash needs-input."""
        # With retry logic, first device gets 3 OSError attempts, then succeeds
        mock_status.side_effect = [
            OSError("network error"),
            OSError("network error"),
            OSError("network error"),
            {"msg": {"data": {"on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}}}},
        ]

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        # Should not raise
        agent_signal.cmd_needs_input(args)

        # Signal colour should still be set
        self.assertEqual(mock_color.call_count, 2)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_needs_input_saves_onoff_false(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """needs-input with onOff: 0 saves 'on': false."""
        mock_status.side_effect = [
            {"msg": {"data": {"onOff": 0, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}},
            {"msg": {"data": {"onOff": 1, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}}}},
        ]

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_needs_input(args)

        saved = json.loads(arbiter.signal_file().read_text())
        self.assertEqual(saved[0]["on"], False)
        self.assertEqual(saved[1]["on"], True)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_needs_input_saves_color_tem_in_kelvin(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """needs-input saves colorTemInKelvin from status."""
        mock_status.side_effect = [
            {"msg": {"data": {"onOff": 1, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}, "colorTemInKelvin": 4000}}},
            {"msg": {"data": {"onOff": 1, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}}}},
        ]

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_needs_input(args)

        saved = json.loads(arbiter.signal_file().read_text())
        self.assertEqual(saved[0]["colorTemInKelvin"], 4000)
        self.assertEqual(saved[1]["colorTemInKelvin"], 0)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_needs_input_all_status_none_writes_empty_marker(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """needs-input where all devices return None: writes [] marker, signal still sent."""
        # With retry logic, each device gets 3 attempts
        mock_status.side_effect = [None, None, None, None, None, None]

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_needs_input(args)

        # Saved state file should exist with empty array
        self.assertTrue(arbiter.signal_file().exists())
        saved = json.loads(arbiter.signal_file().read_text())
        self.assertEqual(saved, [])

        # Signal colour should still be set
        self.assertEqual(mock_color.call_count, 2)


class TestSignalClear(StateDirMixin, unittest.TestCase):
    """Test the clear command."""

    def setUp(self):
        """Create a temp config and state directory for each test."""
        super().setUp()
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
        }
        self.config_path.write_text(json.dumps(self.config))

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_restores_and_deletes_file(self, mock_color, mock_brightness, mock_turn):
        """clear restores saved state and deletes the file."""
        # Create a saved state file
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
            {"ip": "192.168.1.51", "on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # Verify state was restored
        self.assertEqual(mock_brightness.call_count, 2)
        self.assertEqual(mock_brightness.call_args_list[0][0][1], 50)
        self.assertEqual(mock_brightness.call_args_list[1][0][1], 60)

        # Verify file was deleted
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_no_saved_file_no_default_sends_nothing(
        self, mock_color, mock_brightness, mock_turn
    ):
        """clear with no saved file and no default sends nothing (negative test)."""
        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # No govee commands should have been sent
        mock_turn.assert_not_called()
        mock_brightness.assert_not_called()
        mock_color.assert_not_called()

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_no_saved_state_with_default_config_sends_nothing(
        self, mock_color, mock_brightness, mock_turn
    ):
        """clear with no saved state and a config that HAS a default key sends nothing."""
        # Add default to config
        self.config["default"] = {"color": "white", "brightness": 40}
        self.config_path.write_text(json.dumps(self.config))

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # No govee commands should have been sent (default fallback removed)
        mock_turn.assert_not_called()
        mock_brightness.assert_not_called()
        mock_color.assert_not_called()

    def test_clear_no_saved_state_no_config_file(self):
        """clear with no saved state and a non-existent config path exits normally."""
        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.state_dir / "nonexistent.json")
        args.dry_run = False

        # Should not raise an exception
        agent_signal.cmd_clear(args)

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_off_device_turn_off_last(
        self, mock_color, mock_brightness, mock_turn
    ):
        """clear with a saved 'on': false device sends turn(ip, False) LAST."""
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": False, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        # Use attach_mock to track actual call order
        parent = mock.Mock()
        parent.attach_mock(mock_turn, "turn")
        parent.attach_mock(mock_brightness, "brightness")
        parent.attach_mock(mock_color, "color")

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # Check actual call order for this IP
        names = [c[0] for c in parent.mock_calls if c[1] and c[1][0] == "192.168.1.50"]
        self.assertEqual(names, ["brightness", "color", "turn"])
        # Find the turn call for this specific IP
        turn_calls = [c for c in mock_turn.call_args_list if c[0][0] == "192.168.1.50"]
        self.assertEqual(len(turn_calls), 1)
        self.assertEqual(turn_calls[0], mock.call("192.168.1.50", False))

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_on_device_turn_on_first(
        self, mock_color, mock_brightness, mock_turn
    ):
        """clear with a saved 'on': true device sends turn(ip, True) FIRST."""
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        # Use attach_mock to track actual call order
        parent = mock.Mock()
        parent.attach_mock(mock_turn, "turn")
        parent.attach_mock(mock_brightness, "brightness")
        parent.attach_mock(mock_color, "color")

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # Check actual call order for this IP
        names = [c[0] for c in parent.mock_calls if c[1] and c[1][0] == "192.168.1.50"]
        self.assertEqual(names, ["turn", "brightness", "color"])
        # Find the turn call for this specific IP
        turn_calls = [c for c in mock_turn.call_args_list if c[0][0] == "192.168.1.50"]
        self.assertEqual(len(turn_calls), 1)
        self.assertEqual(turn_calls[0], mock.call("192.168.1.50", True))

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_empty_array_applies_default_to_all(
        self, mock_color, mock_brightness, mock_turn
    ):
        """clear with a file containing []: applies default config to all devices, file is deleted."""
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        arbiter.signal_file().write_text("[]")

        # Add default to config
        self.config["default"] = {"color": "white", "brightness": 40}
        self.config_path.write_text(json.dumps(self.config))

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # Should have called govee.color for both devices with default color (white = 255,255,255)
        self.assertEqual(mock_color.call_count, 2)
        mock_color.assert_any_call("192.168.1.50", 255, 255, 255, kelvin=0)
        mock_color.assert_any_call("192.168.1.51", 255, 255, 255, kelvin=0)
        # Brightness should be 40 for both devices
        mock_brightness.assert_any_call("192.168.1.50", 40)
        mock_brightness.assert_any_call("192.168.1.51", 40)

        # File should be deleted
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_invalid_json_file_deleted(
        self, mock_color, mock_brightness, mock_turn
    ):
        """clear with a file containing invalid JSON: no exception, fallback applied, file deleted."""
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        arbiter.signal_file().write_text("{")

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        # Should not raise
        agent_signal.cmd_clear(args)

        # Invalid JSON -> load_saved_state returns [] -> fallback applied to all devices
        # Config has no "default" key, so BUILTIN_DEFAULT (white, 40%) is used
        self.assertEqual(mock_color.call_count, 2)
        mock_color.assert_any_call("192.168.1.50", 255, 255, 255, kelvin=0)
        mock_color.assert_any_call("192.168.1.51", 255, 255, 255, kelvin=0)
        mock_brightness.assert_any_call("192.168.1.50", 40)
        mock_brightness.assert_any_call("192.168.1.51", 40)

        # File should be deleted
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_corrupt_json_prints_only_signal_cleared(
        self, mock_color, mock_brightness, mock_turn
    ):
        """clear with corrupt JSON prints only 'signal cleared' (no 'no active signal' message)."""
        import io
        from contextlib import redirect_stdout

        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        arbiter.signal_file().write_text("{")

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        # Capture stdout
        output = io.StringIO()
        with redirect_stdout(output):
            agent_signal.cmd_clear(args)

        stdout = output.getvalue()
        # Should print "signal cleared" exactly once
        self.assertEqual(stdout.count("signal cleared"), 1)
        # Should NOT print "no active signal; nothing to do"
        self.assertNotIn("no active signal; nothing to do", stdout)
        # Should NOT print "restored saved state"
        self.assertNotIn("restored saved state", stdout)
        # Should NOT print "deleted ..."
        self.assertNotIn("deleted", stdout)


class TestSignalDryRun(StateDirMixin, unittest.TestCase):
    """Test dry-run mode."""

    def setUp(self):
        """Create a temp config for each test."""
        super().setUp()
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "signal": {"color": "#ff6a00", "brightness": 100, "blink": False},
        }
        self.config_path.write_text(json.dumps(self.config))

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_dry_run_does_not_send_commands(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """dry-run mode prints but does not send commands."""
        mock_status.return_value = {"msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}}

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = True

        agent_signal.cmd_needs_input(args)

        # No actual commands sent
        mock_turn.assert_not_called()
        mock_brightness.assert_not_called()
        mock_color.assert_not_called()


class TestNoStdlibShadow(unittest.TestCase):
    """Regression test: ensure no signal.py in repo root that shadows stdlib."""

    def test_no_signal_py_in_repo_root(self):
        """There should be no signal.py in the repo root."""
        repo_root = Path(__file__).parent.parent
        signal_py = repo_root / "signal.py"
        self.assertFalse(
            signal_py.exists(),
            f"signal.py exists in repo root and shadows stdlib signal module: {signal_py}"
        )

    def test_stdlib_signal_importable_from_repo_dir(self):
        """import signal should resolve to stdlib, not a local file."""
        repo_root = Path(__file__).parent.parent
        result = subprocess.run(
            [sys.executable, "-c", "import signal,sys; assert 'Govee' not in signal.__file__, signal.__file__"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode, 0,
            f"stdlib signal import failed from repo dir: {result.stderr}"
        )


class TestLocking(StateDirMixin, unittest.TestCase):
    """Test the locking mechanism for concurrent hooks."""

    def setUp(self):
        """Create a temp config and state directory for each test."""
        super().setUp()
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
        }
        self.config_path.write_text(json.dumps(self.config))

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_lock_timeout_exits_0(self, mock_color, mock_brightness, mock_turn):
        """Lock timeout exits 0 without calling govee.color."""
        # Create a saved state file
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        # Create a fresh lock file
        agent_signal.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        agent_signal.LOCK_FILE.touch()

        # Patch the timeout to be very short
        original_timeout = agent_signal.LOCK_TIMEOUT
        agent_signal.LOCK_TIMEOUT = 0.2

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        # Should exit 0 without calling govee.color
        agent_signal.cmd_clear(args)

        mock_color.assert_not_called()
        # Saved state should still exist
        self.assertTrue(arbiter.signal_file().exists())

        agent_signal.LOCK_TIMEOUT = original_timeout

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_stale_lock_is_removed(self, mock_color, mock_brightness, mock_turn):
        """Stale lock file (older than 30s) is removed and clear proceeds."""
        # Create a saved state file
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        # Create a stale lock file (60s old)
        agent_signal.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        agent_signal.LOCK_FILE.touch()
        old_time = time.time() - 60
        os.utime(str(agent_signal.LOCK_FILE), (old_time, old_time))

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # Should have called govee.color for the saved device and the fallback device
        self.assertEqual(mock_color.call_count, 2)
        # Lock file should be gone
        self.assertFalse(agent_signal.LOCK_FILE.exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_needs_input_recheck_under_lock(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """needs-input re-checks for saved state under the lock."""
        # Mock status responses
        mock_status.side_effect = [
            {"msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}},
            {"msg": {"data": {"on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}}}},
        ]

        # Create saved state file before calling needs-input
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
            {"ip": "192.168.1.51", "on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_needs_input(args)

        # Status should not have been called (saved state already exists)
        mock_status.assert_not_called()

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    @mock.patch("agent_signal.acquire_lock")
    def test_needs_input_always_acquires_lock(
        self, mock_lock, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """needs-input always acquires the lock, even when saved state already exists."""
        mock_lock.return_value = True
        mock_status.side_effect = [
            {"msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}},
            {"msg": {"data": {"on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}}}},
        ]

        # Create saved state file before calling needs-input
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
            {"ip": "192.168.1.51", "on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_needs_input(args)

        # Lock should have been acquired
        mock_lock.assert_called_once()

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_status_retry_on_oserror(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """save_state retries govee.status on OSError up to 3 times."""
        # First two calls raise OSError, third succeeds
        mock_status.side_effect = [
            OSError("port in use"),
            OSError("port in use"),
            {"msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}},
            {"msg": {"data": {"on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}}}},
        ]

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_needs_input(args)

        # Status should have been called 4 times (3 for first device, 1 for second)
        self.assertEqual(mock_status.call_count, 4)
        # Saved state should have both devices
        saved = json.loads(arbiter.signal_file().read_text())
        self.assertEqual(len(saved), 2)

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_restore_fallback_for_missing_device(
        self, mock_color, mock_brightness, mock_turn
    ):
        """restore_state applies default config for devices missing from saved state."""
        # Create a saved state file with only one device
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        # Config has default
        self.config["default"] = {"color": "white", "brightness": 40}
        self.config_path.write_text(json.dumps(self.config))

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # Should have called govee.color for both devices
        self.assertEqual(mock_color.call_count, 2)
        # Second call should be for the missing device with default color (white = 255,255,255)
        mock_color.assert_any_call("192.168.1.51", 255, 255, 255, kelvin=0)
        # Brightness should be 40 for the missing device
        mock_brightness.assert_any_call("192.168.1.51", 40)


class TestSignalArbiterIntegration(StateDirMixin, unittest.TestCase):
    """Test that agent_signal and arbiter are tied together via signal_file()."""

    def setUp(self):
        super().setUp()
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "signal": {"color": "#ff6a00", "brightness": 100, "blink": False},
        }
        self.config_path.write_text(json.dumps(self.config))

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_needs_input_makes_arbiter_signal_active(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """needs-input creates the signal file that arbiter.signal_active() checks."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Before: arbiter should not see signal as active
        self.assertFalse(arbiter.signal_active())

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_needs_input(args)

        # After needs-input: arbiter should see signal as active
        self.assertTrue(arbiter.signal_active())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_makes_arbiter_signal_inactive(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """clear deletes the signal file that arbiter.signal_active() checks."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Create signal state
        args1 = mock.Mock()
        args1.command = "needs-input"
        args1.config = str(self.config_path)
        args1.dry_run = False
        agent_signal.cmd_needs_input(args1)

        self.assertTrue(arbiter.signal_active())

        # Clear signal
        args2 = mock.Mock()
        args2.command = "clear"
        args2.config = str(self.config_path)
        args2.dry_run = False
        agent_signal.cmd_clear(args2)

        # After clear: arbiter should not see signal as active
        self.assertFalse(arbiter.signal_active())


class TestSaveStateTimeout(StateDirMixin, unittest.TestCase):
    """Test that save_state respects the SAVE_STATE_BUDGET deadline."""

    def setUp(self):
        super().setUp()
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "signal": {
                "color": "#ff6a00",
                "brightness": 100,
                "blink": False,
            },
        }
        self.config_path.write_text(json.dumps(self.config))

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_save_state_respects_budget(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """save_state stops trying when SAVE_STATE_BUDGET is exceeded."""
        # Fake clock: track elapsed time
        elapsed = [0.0]

        def fake_time():
            return elapsed[0]

        def fake_sleep(seconds):
            elapsed[0] += seconds

        def fake_status(ip, timeout=2):
            # Simulate a slow device that takes the full timeout
            elapsed[0] += timeout
            return None

        with mock.patch("agent_signal.time.time", fake_time):
            with mock.patch("agent_signal.time.sleep", fake_sleep):
                mock_status.side_effect = fake_status

                args = mock.Mock()
                args.command = "needs-input"
                args.config = str(self.config_path)
                args.dry_run = False

                agent_signal.cmd_needs_input(args)

        # Elapsed time should be within budget (plus small tolerance)
        self.assertLessEqual(
            elapsed[0],
            agent_signal.SAVE_STATE_BUDGET + 0.5,
            f"save_state took {elapsed[0]}s, exceeding budget of {agent_signal.SAVE_STATE_BUDGET}s"
        )

        # Every status call should have had timeout <= STATUS_TIMEOUT
        for call in mock_status.call_args_list:
            timeout = call[1].get("timeout", 2)
            self.assertLessEqual(
                timeout,
                agent_signal.STATUS_TIMEOUT,
                f"status call had timeout {timeout}s, exceeding STATUS_TIMEOUT of {agent_signal.STATUS_TIMEOUT}s"
            )

        # Saved state should be empty (no devices responded)
        saved = json.loads(arbiter.signal_file().read_text())
        self.assertEqual(saved, [])


class TestClearWithNullDefault(StateDirMixin, unittest.TestCase):
    """Test that clear with "default": null uses built-in default."""

    def setUp(self):
        super().setUp()
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "default": None,  # Explicitly null
            "signal": {
                "color": "#ff6a00",
                "brightness": 100,
                "blink": False,
            },
        }
        self.config_path.write_text(json.dumps(self.config))

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_with_null_default_uses_builtin(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """With "default": null, clear uses built-in white/40 for devices without saved state."""
        # First, create a signal with saved state for only one device
        mock_status.side_effect = [
            {"msg": {"data": {"onOff": 1, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}},
            None,  # Second device doesn't respond
            None,  # retry
            None,  # retry
        ]

        args1 = mock.Mock()
        args1.command = "needs-input"
        args1.config = str(self.config_path)
        args1.dry_run = False
        agent_signal.cmd_needs_input(args1)

        # Reset mocks for clear
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()

        # Now clear
        args2 = mock.Mock()
        args2.command = "clear"
        args2.config = str(self.config_path)
        args2.dry_run = False
        agent_signal.cmd_clear(args2)

        # Device 1 should be restored from saved state (white, 50%)
        # Device 2 should get built-in default (white, 40%)
        # Check that govee.color was called for both devices
        self.assertEqual(mock_color.call_count, 2)
        # Device 2 (no saved state) should get built-in default brightness 40
        # Find the call for device 2
        device2_calls = [c for c in mock_brightness.call_args_list if c[0][0] == "192.168.1.51"]
        self.assertEqual(len(device2_calls), 1)
        self.assertEqual(device2_calls[0][0][1], 40)


if __name__ == "__main__":
    unittest.main()
