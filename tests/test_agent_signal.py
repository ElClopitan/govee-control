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
import game_sync
import govee
import weather_sync
from helpers import StateDirMixin


@mock.patch("agent_signal.time.sleep")
class TestSignalNeedsInput(StateDirMixin, unittest.TestCase):
    """Test the needs-input command."""

    def setUp(self):
        """Create a temp config and state directory for each test."""
        super().setUp()
        arbiter.set_mode("weather")
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
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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


@mock.patch("agent_signal.time.sleep")
class TestNeedsInputOffMode(StateDirMixin, unittest.TestCase):
    """Test that needs-input is skipped when mode is 'off'."""

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
    def test_off_mode_skips(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Mode 'off' skips the signal entirely."""
        arbiter.set_mode("off")

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        # Ensure attended session so the unattended check doesn't skip first
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
            agent_signal.cmd_needs_input(args)

        # No govee calls
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()
        mock_turn.assert_not_called()
        mock_status.assert_not_called()

        # No saved state file
        self.assertFalse(arbiter.signal_file().exists())

        # No session marker
        marker_dir = self.state_dir / "signal_sessions"
        if marker_dir.exists():
            self.assertEqual(len(list(marker_dir.iterdir())), 0)

        # Log should contain skipped-off
        log_path = agent_signal.signal_log_path()
        self.assertTrue(log_path.exists())
        log_content = log_path.read_text()
        self.assertIn("needs-input skipped-off", log_content)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_off_mode_skips_with_force(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Mode 'off' skips even with --force."""
        arbiter.set_mode("off")

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = True

        # Ensure attended session so the unattended check doesn't skip first
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
            agent_signal.cmd_needs_input(args)

        # No govee calls
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()
        mock_turn.assert_not_called()
        mock_status.assert_not_called()

        # No saved state file
        self.assertFalse(arbiter.signal_file().exists())

        # Log should contain skipped-off
        log_path = agent_signal.signal_log_path()
        self.assertTrue(log_path.exists())
        log_content = log_path.read_text()
        self.assertIn("needs-input skipped-off", log_content)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_mode_turns_off_before_lock(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Mode turns off between first check and lock acquisition."""
        # First check returns "weather", second (under lock) returns "off"
        with mock.patch("arbiter.get_mode", side_effect=["weather", "off"]):
            args = mock.Mock()
            args.command = "needs-input"
            args.config = str(self.config_path)
            args.dry_run = False
            args.force = False

            # Ensure attended session so the unattended check doesn't skip first
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # No govee calls
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()
        mock_turn.assert_not_called()
        mock_status.assert_not_called()

        # No saved state file
        self.assertFalse(arbiter.signal_file().exists())

        # Lock should have been released (no exception)
        # If the lock were still held, the test would hang or fail

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_weather_mode_applies(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Mode 'weather' applies the signal normally."""
        arbiter.set_mode("weather")

        mock_status.side_effect = [
            {"msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}},
            {"msg": {"data": {"on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}}}},
        ]

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        # Ensure attended session so the unattended check doesn't skip first
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
            agent_signal.cmd_needs_input(args)

        # Signal colour should be set
        self.assertEqual(mock_color.call_count, 2)

        # Saved state file should exist
        self.assertTrue(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_no_saved_state_does_not_read_mode(
        self, mock_color, mock_brightness, mock_turn, mock_sleep
    ):
        """cmd_clear with no saved state does not read the mode."""
        with mock.patch("arbiter.get_mode") as mock_get_mode:
            args = mock.Mock()
            args.command = "clear"
            args.config = str(self.config_path)
            args.dry_run = False
            args.stale = False

            agent_signal.cmd_clear(args)

        # No govee calls
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()
        mock_turn.assert_not_called()

        # get_mode should not have been called
        mock_get_mode.assert_not_called()


@mock.patch("agent_signal.time.sleep")
class TestRestoreFollowsMode(StateDirMixin, unittest.TestCase):
    """Test that restore follows the current mode (off mode turns strips off)."""

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
        arbiter.set_mode("weather")

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_in_off_mode_turns_off(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """clear in off mode turns all devices off, does not restore saved colour."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Set up needs-input signal in weather mode
        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
            agent_signal.cmd_needs_input(args)

        # Now switch to off mode
        arbiter.set_mode("off")

        # Reset mocks to only track calls after mode change
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()

        # Clear the signal
        args.command = "clear"
        args.stale = False
        agent_signal.cmd_clear(args)

        # Should have turned off both devices
        self.assertEqual(mock_turn.call_count, 2)
        for call in mock_turn.call_args_list:
            self.assertFalse(call[0][1])  # second arg is False (off)

        # Should NOT have restored the saved colour
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()

        # Saved state file should be gone
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_in_game_mode_restores(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """clear in game mode restores saved state as normal."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Set up needs-input signal
        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
            agent_signal.cmd_needs_input(args)

        # Switch to game mode
        arbiter.set_mode("game")

        # Reset mocks to only track calls after mode change
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()

        # Clear the signal
        args.command = "clear"
        args.stale = False
        agent_signal.cmd_clear(args)

        # Should have restored the saved state (brightness and color calls)
        self.assertEqual(mock_brightness.call_count, 2)
        self.assertEqual(mock_color.call_count, 2)

        # Saved state file should be gone
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_sweep_in_off_mode_turns_off(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """sweep_and_restore in off mode turns all devices off."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Create signal file (saved_state.json) but no session markers
        signal_path = arbiter.signal_file()
        signal_path.parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
            {"ip": "192.168.1.51", "on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}},
        ]
        signal_path.write_text(json.dumps(saved_state))

        # Switch to off mode
        arbiter.set_mode("off")

        # Run sweep_and_restore
        result = agent_signal.sweep_and_restore(config_path=str(self.config_path))

        # Should have restored (turned off)
        self.assertTrue(result)

        # Should have turned off both devices
        self.assertEqual(mock_turn.call_count, 2)
        for call in mock_turn.call_args_list:
            self.assertFalse(call[0][1])  # second arg is False (off)

        # Should NOT have restored the saved colour
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()

        # Signal file should be gone
        self.assertFalse(signal_path.exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_off_mode_dry_run_sends_nothing(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """clear in off mode with --dry-run sends nothing."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Set up needs-input signal
        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
            agent_signal.cmd_needs_input(args)

        # Switch to off mode
        arbiter.set_mode("off")

        # Reset mocks to only track calls after mode change
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()

        # Clear with dry-run
        args.command = "clear"
        args.dry_run = True
        args.stale = False
        agent_signal.cmd_clear(args)

        # No govee calls in dry-run
        mock_turn.assert_not_called()
        mock_brightness.assert_not_called()
        mock_color.assert_not_called()


@mock.patch("agent_signal.time.sleep")
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
        arbiter.set_mode("weather")

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_restores_and_deletes_file(self, mock_color, mock_brightness, mock_turn, mock_sleep):
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
        self, mock_color, mock_brightness, mock_turn, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_sleep
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

    def test_clear_no_saved_state_no_config_file(self, mock_sleep):
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
        self, mock_color, mock_brightness, mock_turn, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_sleep
    ):
        """clear with corrupt JSON prints only 'signal cleared' (no 'no active signal' message)."""
        import io
        from contextlib import redirect_stdout, redirect_stderr

        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        arbiter.signal_file().write_text("{")

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        # Capture stdout and stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            agent_signal.cmd_clear(args)

        stdout = stdout_capture.getvalue()
        stderr = stderr_capture.getvalue()
        # Should print "signal cleared" exactly once
        self.assertEqual(stdout.count("signal cleared"), 1)
        # Should NOT print "no active signal; nothing to do"
        self.assertNotIn("no active signal; nothing to do", stdout)
        # Should NOT print "restored saved state"
        self.assertNotIn("restored saved state", stdout)
        # Should NOT print "deleted ..."
        self.assertNotIn("deleted", stdout)
        # stderr should contain the parse warning
        self.assertIn("failed to parse saved state", stderr)

    @mock.patch("agent_signal.sweep_and_restore")
    def test_clear_stale_calls_sweep_and_restore(self, mock_sweep, mock_sleep):
        """clear --stale calls sweep_and_restore."""
        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False
        args.stale = True

        agent_signal.cmd_clear(args)

        # sweep_and_restore should have been called once
        mock_sweep.assert_called_once()


@mock.patch("agent_signal.time.sleep")
class TestOSErrorHandling(StateDirMixin, unittest.TestCase):
    """Test that OSError from govee.send() does not crash the hooks."""

    def setUp(self):
        super().setUp()
        arbiter.set_mode("weather")
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
            ],
            "signal": {
                "color": "#ff6a00",
                "brightness": 100,
                "blink": False,
            },
        }
        self.config_path.write_text(json.dumps(self.config))

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_oserror_does_not_crash(self, mock_color, mock_brightness, mock_turn, mock_sleep):
        """clear with govee.turn raising OSError: no crash, saved state kept, lock released."""
        # Create a saved state file
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        # Make govee.turn raise OSError
        mock_turn.side_effect = OSError("[WinError 10051] network unreachable")

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        # Should not raise
        agent_signal.cmd_clear(args)

        # Saved state should still exist (not deleted on error)
        self.assertTrue(arbiter.signal_file().exists())
        # Lock file should not exist (released)
        self.assertFalse(agent_signal.LOCK_FILE.exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_needs_input_oserror_does_not_crash(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """needs-input with govee.color raising OSError: no crash, saved state kept, lock released."""
        # Mock status to answer
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Make govee.color raise OSError
        mock_color.side_effect = OSError("[WinError 10051] network unreachable")

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        # Should not raise
        agent_signal.cmd_needs_input(args)

        # Saved state should exist
        self.assertTrue(arbiter.signal_file().exists())
        # Lock file should not exist (released)
        self.assertFalse(agent_signal.LOCK_FILE.exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    @mock.patch("agent_signal.acquire_lock")
    def test_needs_input_lock_timeout_skips_signal(
        self, mock_lock, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """needs-input with lock timeout: no signal colour set, no saved state, exit 0."""
        # Lock times out
        mock_lock.return_value = False

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        # Should not raise
        agent_signal.cmd_needs_input(args)

        # No govee calls should have been made
        mock_turn.assert_not_called()
        mock_brightness.assert_not_called()
        mock_color.assert_not_called()

        # No saved state should exist
        self.assertFalse(arbiter.signal_file().exists())

        # Lock file should not exist (lock timed out, never acquired)
        self.assertFalse(agent_signal.LOCK_FILE.exists())


@mock.patch("agent_signal.time.sleep")
class TestSignalDryRun(StateDirMixin, unittest.TestCase):
    """Test dry-run mode."""

    def setUp(self):
        """Create a temp config for each test."""
        super().setUp()
        arbiter.set_mode("weather")
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
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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
        arbiter.set_mode("weather")
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

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        # Patch the timeout to be very short
        with mock.patch.object(agent_signal, "LOCK_TIMEOUT", 0.2):
            # Should exit 0 without calling govee.color
            agent_signal.cmd_clear(args)

        mock_color.assert_not_called()
        # Saved state should still exist
        self.assertTrue(arbiter.signal_file().exists())

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

    @mock.patch("agent_signal.time.sleep")
    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_needs_input_recheck_under_lock(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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

    @mock.patch("agent_signal.time.sleep")
    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    @mock.patch("agent_signal.acquire_lock")
    def test_needs_input_always_acquires_lock(
        self, mock_lock, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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
    def test_needs_input_lock_hold_with_blink_under_timeout(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """With blink on, the lock is held for save_state + set_signal_color.
        Total must stay under LOCK_TIMEOUT with margin."""
        # Fake clock
        clock = [0.0]

        def fake_time():
            return clock[0]

        def fake_sleep(seconds):
            clock[0] += seconds

        def fake_status(ip, timeout=2):
            clock[0] += timeout
            return None

        # Record lock acquire/release times
        lock_times = {"acquired": None, "released": None}

        def fake_acquire_lock(dry_run=False):
            lock_times["acquired"] = clock[0]
            return True

        def fake_release_lock(dry_run=False):
            lock_times["released"] = clock[0]

        with mock.patch("agent_signal.time.time", fake_time):
            with mock.patch("agent_signal.time.sleep", fake_sleep):
                with mock.patch("agent_signal.acquire_lock", fake_acquire_lock):
                    with mock.patch("agent_signal.release_lock", fake_release_lock):
                        mock_status.side_effect = fake_status

                        # Config with blink on
                        self.config["signal"] = {
                            "color": "#ff6a00",
                            "brightness": 80,
                            "blink": True,
                        }
                        self.config_path.write_text(json.dumps(self.config))

                        args = mock.Mock()
                        args.command = "needs-input"
                        args.config = str(self.config_path)
                        args.dry_run = False

                        agent_signal.cmd_needs_input(args)

        hold_time = lock_times["released"] - lock_times["acquired"]
        self.assertLessEqual(
            hold_time,
            agent_signal.LOCK_TIMEOUT - 1.5,
            f"lock held {hold_time}s, exceeding LOCK_TIMEOUT - 1.5 = {agent_signal.LOCK_TIMEOUT - 1.5}s"
        )

    @mock.patch("agent_signal.time.sleep")
    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_status_retry_on_oserror(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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

    @mock.patch("agent_signal.time.sleep")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_restore_fallback_for_missing_device(
        self, mock_color, mock_brightness, mock_turn, mock_sleep
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


@mock.patch("agent_signal.time.sleep")
class TestSignalArbiterIntegration(StateDirMixin, unittest.TestCase):
    """Test that agent_signal and arbiter are tied together via signal_file()."""

    def setUp(self):
        super().setUp()
        arbiter.set_mode("weather")
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
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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
        arbiter.set_mode("weather")
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


@mock.patch("agent_signal.time.sleep")
class TestLoadSavedStateShapeValidation(StateDirMixin, unittest.TestCase):
    """Test that load_saved_state validates the shape of saved state data."""

    def setUp(self):
        super().setUp()
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
        }
        self.config_path.write_text(json.dumps(self.config))
        arbiter.set_mode("weather")

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_object_not_list(self, mock_color, mock_brightness, mock_turn, mock_sleep):
        """clear with a file containing an object (not a list): no crash, fallback applied, file deleted."""
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        arbiter.signal_file().write_text('{"ip": "192.168.1.50"}')

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        # Should not raise
        agent_signal.cmd_clear(args)

        # Not a list -> load_saved_state returns [] -> fallback applied to all devices
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
    def test_clear_mixed_valid_invalid_entries(self, mock_color, mock_brightness, mock_turn, mock_sleep):
        """clear with a list containing invalid and valid entries: valid restored, invalid dropped."""
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        # First entry is invalid (no "ip" field), second is valid
        arbiter.signal_file().write_text(
            '[{"on": true}, {"ip": "192.168.1.50", "on": true, "brightness": 50, "color": {"r": 1, "g": 2, "b": 3}}]'
        )

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        # Should not raise
        agent_signal.cmd_clear(args)

        # Valid entry for .50 should be restored with its color (1, 2, 3)
        mock_color.assert_any_call("192.168.1.50", 1, 2, 3, kelvin=0)
        # .51 has no saved state, gets fallback (white, 40%)
        mock_color.assert_any_call("192.168.1.51", 255, 255, 255, kelvin=0)

        # File should be deleted
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_null_json(self, mock_color, mock_brightness, mock_turn, mock_sleep):
        """clear with a file containing 'null': fallback applied to all devices, file deleted."""
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        arbiter.signal_file().write_text("null")

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        # Should not raise
        agent_signal.cmd_clear(args)

        # null -> json.load returns None -> not a list -> [] -> fallback applied to all devices
        self.assertEqual(mock_color.call_count, 2)
        mock_color.assert_any_call("192.168.1.50", 255, 255, 255, kelvin=0)
        mock_color.assert_any_call("192.168.1.51", 255, 255, 255, kelvin=0)
        mock_brightness.assert_any_call("192.168.1.50", 40)
        mock_brightness.assert_any_call("192.168.1.51", 40)

        # File should be deleted
        self.assertFalse(arbiter.signal_file().exists())


@mock.patch("agent_signal.time.sleep")
class TestSignalStateFiltering(StateDirMixin, unittest.TestCase):
    """Test that signal colour is not saved or restored as previous state."""

    def setUp(self):
        super().setUp()
        arbiter.set_mode("weather")
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
    def test_save_state_skips_signal_color(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """save_state skips devices showing the signal colour."""
        # First device shows signal colour (#ff6a00 = 255, 106, 0)
        # Second device shows a different colour (#b0bec5 = 176, 190, 197)
        mock_status.side_effect = [
            {"msg": {"data": {"onOff": 1, "brightness": 100, "color": {"r": 255, "g": 106, "b": 0}}}},
            {"msg": {"data": {"onOff": 1, "brightness": 50, "color": {"r": 176, "g": 190, "b": 197}}}},
        ]

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_needs_input(args)

        # Only the non-signal device should be saved
        saved = json.loads(arbiter.signal_file().read_text())
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["ip"], "192.168.1.51")
        self.assertEqual(saved[0]["color"]["r"], 176)

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_restore_state_skips_signal_color(
        self, mock_color, mock_brightness, mock_turn, mock_sleep
    ):
        """restore_state skips saved entries matching the signal colour."""
        # Create a saved state where one device has the signal colour
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 100, "color": {"r": 255, "g": 106, "b": 0}},
            {"ip": "192.168.1.51", "on": True, "brightness": 50, "color": {"r": 176, "g": 190, "b": 197}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        # Config has no "default" key, so BUILTIN_DEFAULT (white, 40%) is used
        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # Device 1 (signal colour) should get fallback (white, 40%)
        mock_color.assert_any_call("192.168.1.50", 255, 255, 255, kelvin=0)
        mock_brightness.assert_any_call("192.168.1.50", 40)

        # Device 2 (non-signal colour) should be restored
        mock_color.assert_any_call("192.168.1.51", 176, 190, 197, kelvin=0)
        mock_brightness.assert_any_call("192.168.1.51", 50)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_save_state_all_signal_color_logs_skipped(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """When all strips show the signal colour, log 'already shows the signal colour' for each,
        and do NOT log 'no device answered'."""
        import io
        from contextlib import redirect_stderr

        # Both devices show the signal colour (#ff6a00 = 255, 106, 0)
        mock_status.side_effect = [
            {"msg": {"data": {"onOff": 1, "brightness": 100, "color": {"r": 255, "g": 106, "b": 0}}}},
            {"msg": {"data": {"onOff": 1, "brightness": 100, "color": {"r": 255, "g": 106, "b": 0}}}},
        ]

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False

        stderr_capture = io.StringIO()
        with redirect_stderr(stderr_capture):
            agent_signal.cmd_needs_input(args)

        stderr = stderr_capture.getvalue()

        # Should log "already shows the signal colour" twice
        self.assertEqual(stderr.count("already shows the signal colour"), 2)
        # Should NOT log "no device answered"
        self.assertNotIn("no device answered", stderr)

        # Saved file should be []
        saved = json.loads(arbiter.signal_file().read_text())
        self.assertEqual(saved, [])

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_object_not_list_stderr_warning(
        self, mock_color, mock_brightness, mock_turn, mock_sleep
    ):
        """clear with a file containing an object (not a list): stderr has 'saved state is not a list',
        stdout is exactly 'signal cleared'."""
        import io
        from contextlib import redirect_stdout, redirect_stderr

        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        arbiter.signal_file().write_text('{"ip": "192.168.1.50"}')

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            agent_signal.cmd_clear(args)

        stdout = stdout_capture.getvalue()
        stderr = stderr_capture.getvalue()

        # stderr should contain the warning
        self.assertIn("saved state is not a list", stderr)
        # stdout should be exactly "signal cleared" on one line
        self.assertEqual(stdout.strip(), "signal cleared")
        # No "deleted" in stdout
        self.assertNotIn("deleted", stdout)


@mock.patch("agent_signal.time.sleep")
class TestClearWithNullDefault(StateDirMixin, unittest.TestCase):
    """Test that clear with "default": null uses built-in default."""

    def setUp(self):
        super().setUp()
        arbiter.set_mode("weather")
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
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
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
        # Device 2 should also get white color (built-in default)
        mock_color.assert_any_call("192.168.1.51", 255, 255, 255, kelvin=0)


class TestIsUnattended(unittest.TestCase):
    """Test the is_unattended function."""

    def test_unattended_when_env_is_zero(self):
        """is_unattended returns True when CLAUDE_CODE_SESSION_ATTENDED=0."""
        env = {"CLAUDE_CODE_SESSION_ATTENDED": "0"}
        self.assertTrue(agent_signal.is_unattended(env))

    def test_attended_when_env_is_one(self):
        """is_unattended returns False when CLAUDE_CODE_SESSION_ATTENDED=1."""
        env = {"CLAUDE_CODE_SESSION_ATTENDED": "1"}
        self.assertFalse(agent_signal.is_unattended(env))

    def test_attended_when_env_missing(self):
        """is_unattended returns False when CLAUDE_CODE_SESSION_ATTENDED is not set."""
        env = {}
        self.assertFalse(agent_signal.is_unattended(env))

    def test_attended_when_env_empty_string(self):
        """is_unattended returns False when CLAUDE_CODE_SESSION_ATTENDED is empty."""
        env = {"CLAUDE_CODE_SESSION_ATTENDED": ""}
        self.assertFalse(agent_signal.is_unattended(env))


@mock.patch("agent_signal.time.sleep")
class TestNeedsInputUnattended(StateDirMixin, unittest.TestCase):
    """Test that needs-input skips unattended sessions."""

    def setUp(self):
        super().setUp()
        arbiter.set_mode("weather")
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
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
    def test_unattended_skips_signal(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Unattended session: no govee calls, no saved state, exit 0."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "0"}):
            agent_signal.cmd_needs_input(args)

        # No govee calls
        mock_status.assert_not_called()
        mock_turn.assert_not_called()
        mock_brightness.assert_not_called()
        mock_color.assert_not_called()

        # No saved state
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_attended_applies_signal(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Attended session (env var missing): signal applied as before."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        # No CLAUDE_CODE_SESSION_ATTENDED env var
        with mock.patch.dict(os.environ, {}, clear=True):
            agent_signal.cmd_needs_input(args)

        # Signal applied
        self.assertTrue(arbiter.signal_file().exists())
        self.assertEqual(mock_color.call_count, 1)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_include_unattended_true_applies_signal(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """include_unattended: true -> signal applied even for unattended."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Add include_unattended to config
        self.config["signal"]["include_unattended"] = True
        self.config_path.write_text(json.dumps(self.config))

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "0"}):
            agent_signal.cmd_needs_input(args)

        # Signal applied
        self.assertTrue(arbiter.signal_file().exists())
        self.assertEqual(mock_color.call_count, 1)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_force_flag_applies_signal(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """--force flag -> signal applied even for unattended."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = True

        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "0"}):
            agent_signal.cmd_needs_input(args)

        # Signal applied
        self.assertTrue(arbiter.signal_file().exists())
        self.assertEqual(mock_color.call_count, 1)


@mock.patch("agent_signal.time.sleep")
class TestSignalLogging(StateDirMixin, unittest.TestCase):
    """Test that signal events are logged."""

    def setUp(self):
        super().setUp()
        arbiter.set_mode("weather")
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
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
    def test_needs_input_logs_applied(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """needs-input logs 'applied' when signal is set."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        # Ensure attended session so signal is applied
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
            agent_signal.cmd_needs_input(args)

        # Check log file exists and contains the event
        log_path = agent_signal.signal_log_path()
        self.assertTrue(log_path.exists())
        log_content = log_path.read_text()
        self.assertIn("needs-input applied", log_content)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_unattended_logs_skipped(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Unattended session logs 'skipped-unattended'."""
        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "0"}):
            agent_signal.cmd_needs_input(args)

        # Check log file exists and contains the event
        log_path = agent_signal.signal_log_path()
        self.assertTrue(log_path.exists())
        log_content = log_path.read_text()
        self.assertIn("needs-input skipped-unattended", log_content)

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_logs_applied(
        self, mock_color, mock_brightness, mock_turn, mock_sleep
    ):
        """clear logs 'applied' when signal is cleared."""
        # Create a saved state file
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # Check log file exists and contains the event
        log_path = agent_signal.signal_log_path()
        self.assertTrue(log_path.exists())
        log_content = log_path.read_text()
        self.assertIn("clear applied", log_content)

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_no_signal_logs_no_signal(
        self, mock_color, mock_brightness, mock_turn, mock_sleep
    ):
        """clear with no signal logs 'no-signal'."""
        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # Check log file exists and contains the event
        log_path = agent_signal.signal_log_path()
        self.assertTrue(log_path.exists())
        log_content = log_path.read_text()
        self.assertIn("clear no-signal", log_content)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_log_contains_session_id(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Log contains session_id from hook input."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        # Fake stdin with hook input
        fake_stdin = json.dumps({"session_id": "test-session-123", "message": "waiting for input"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin)):
            agent_signal.cmd_needs_input(args)

        # Check log contains session_id
        log_path = agent_signal.signal_log_path()
        log_content = log_path.read_text()
        self.assertIn("session=test-session-123", log_content)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_bad_stdin_json_no_crash(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Bad stdin JSON does not crash."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        # Fake stdin with bad JSON, and ensure attended env
        fake_stdin = "{bad json}"
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # Should not crash, signal should be applied
        self.assertTrue(arbiter.signal_file().exists())

    def test_log_path_resolved_at_call_time(self, mock_sleep):
        """Log events land in the patched STATE_DIR, not the real one.

        This verifies that signal_log_path() resolves the path at call time
        using the current module value of STATE_DIR, so tests that patch
        STATE_DIR don't pollute the real state/signal.log.
        """
        # Record the real signal log path (before patching)
        real_state_dir = Path(agent_signal.__file__).parent / "state"
        real_log = real_state_dir / "signal.log"

        # Record real log size before
        if real_log.exists():
            real_size_before = real_log.stat().st_size
        else:
            real_size_before = 0

        # Log an event (STATE_DIR is patched by StateDirMixin)
        agent_signal.log_signal_event("test", "log-path-check")

        # The log should be in the test's state directory
        test_log = agent_signal.signal_log_path()
        self.assertTrue(test_log.exists())
        self.assertIn("test log-path-check", test_log.read_text())

        # The real log should be unchanged
        if real_log.exists():
            real_size_after = real_log.stat().st_size
            self.assertEqual(
                real_size_before,
                real_size_after,
                "Real signal.log was modified by test (log path not resolved at call time)"
            )


@mock.patch("agent_signal.time.sleep")
class TestBrightnessCap(StateDirMixin, unittest.TestCase):
    """Test that brightness is capped at max_brightness (default 80)."""

    def setUp(self):
        super().setUp()
        arbiter.set_mode("weather")
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
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
    def test_signal_brightness_capped_at_80(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Signal brightness of 100 is capped to 80 (default max_brightness)."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        # Ensure attended session so the signal is applied
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
            agent_signal.cmd_needs_input(args)

        # Brightness should be capped at 80, not 100
        self.assertEqual(mock_brightness.call_count, 1)
        self.assertEqual(mock_brightness.call_args[0][1], 80)


@mock.patch("agent_signal.time.sleep")
class TestPerSessionMarkers(StateDirMixin, unittest.TestCase):
    """Test per-session signal markers."""

    def setUp(self):
        super().setUp()
        arbiter.set_mode("weather")
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
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
    def test_needs_input_writes_session_marker(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """needs-input writes a session marker file."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        fake_stdin = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # Session marker should exist
        sessions_dir = agent_signal.signal_sessions_dir()
        self.assertTrue(sessions_dir.exists())
        marker = sessions_dir / "session-A"
        self.assertTrue(marker.exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_needs_input_no_session_id_uses_manual(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """needs-input with no session_id writes 'manual' marker."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        # No stdin (manual CLI run)
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: True)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # Manual marker should exist
        sessions_dir = agent_signal.signal_sessions_dir()
        marker = sessions_dir / "manual"
        self.assertTrue(marker.exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_two_sessions_clear_one_keeps_signal(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Two sessions set signal; one clears -> signal stays (no restore)."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_a)

        # Session B sets signal (should not overwrite saved state)
        mock_status.reset_mock()
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_b)

        # Both markers should exist
        sessions_dir = agent_signal.signal_sessions_dir()
        self.assertTrue((sessions_dir / "session-A").exists())
        self.assertTrue((sessions_dir / "session-B").exists())

        # Session A clears
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear_a = mock.Mock()
        args_clear_a.command = "clear"
        args_clear_a.config = str(self.config_path)
        args_clear_a.dry_run = False
        args_clear_a.all = False
        fake_stdin_clear_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear_a)):
            agent_signal.cmd_clear(args_clear_a)

        # Signal should NOT be restored (session B still waiting)
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()
        mock_turn.assert_not_called()
        # Saved state should still exist
        self.assertTrue(arbiter.signal_file().exists())
        # Session A's marker should be gone
        self.assertFalse((sessions_dir / "session-A").exists())
        # Session B's marker should still exist
        self.assertTrue((sessions_dir / "session-B").exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_sessionend_hook_clears_marker(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """SessionEnd hook input clears only that session's marker."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_a)

        # Session B sets signal
        mock_status.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_b)

        sessions_dir = agent_signal.signal_sessions_dir()
        self.assertTrue((sessions_dir / "session-A").exists())
        self.assertTrue((sessions_dir / "session-B").exists())

        # Session A ends (SessionEnd hook) — no message field, has reason
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear = mock.Mock()
        args_clear.command = "clear"
        args_clear.config = str(self.config_path)
        args_clear.dry_run = False
        args_clear.all = False
        fake_stdin_sessionend = json.dumps({
            "session_id": "session-A",
            "hook_event_name": "SessionEnd",
            "reason": "user closed session"
        })
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_sessionend)):
            agent_signal.cmd_clear(args_clear)

        # Session A's marker should be gone
        self.assertFalse((sessions_dir / "session-A").exists())
        # Session B's marker should still exist
        self.assertTrue((sessions_dir / "session-B").exists())
        # Signal should NOT be restored (session B still waiting)
        mock_color.assert_not_called()
        self.assertTrue(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_last_session_clear_restores(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Last session to clear restores the lights."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_a)

        # Session B sets signal
        mock_status.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_b)

        # Session A clears
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear_a = mock.Mock()
        args_clear_a.command = "clear"
        args_clear_a.config = str(self.config_path)
        args_clear_a.dry_run = False
        args_clear_a.all = False
        fake_stdin_clear_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear_a)):
            agent_signal.cmd_clear(args_clear_a)

        # Signal should NOT be restored yet
        mock_color.assert_not_called()

        # Session B clears (last one)
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear_b = mock.Mock()
        args_clear_b.command = "clear"
        args_clear_b.config = str(self.config_path)
        args_clear_b.dry_run = False
        args_clear_b.all = False
        fake_stdin_clear_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear_b)):
            agent_signal.cmd_clear(args_clear_b)

        # Signal should be restored now
        self.assertEqual(mock_color.call_count, 1)
        # Saved state should be deleted
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_unknown_session_with_marker_present_no_restore(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Clear from unknown session with another session's marker present -> no restore."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_a)

        # Unknown session tries to clear
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear = mock.Mock()
        args_clear.command = "clear"
        args_clear.config = str(self.config_path)
        args_clear.dry_run = False
        args_clear.all = False
        fake_stdin_clear = json.dumps({"session_id": "session-unknown"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear)):
            agent_signal.cmd_clear(args_clear)

        # Signal should NOT be restored (session A still waiting)
        mock_color.assert_not_called()
        self.assertTrue(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_stale_marker_ignored_and_deleted(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Stale marker (older than max_age_hours) is ignored and deleted."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_a)

        # Make session A's marker stale (older than 2 hours)
        sessions_dir = agent_signal.signal_sessions_dir()
        marker = sessions_dir / "session-A"
        old_time = time.time() - (3 * 3600)  # 3 hours ago
        os.utime(str(marker), (old_time, old_time))

        # Clear from session A (marker is stale)
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear = mock.Mock()
        args_clear.command = "clear"
        args_clear.config = str(self.config_path)
        args_clear.dry_run = False
        args_clear.all = False
        fake_stdin_clear = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear)):
            agent_signal.cmd_clear(args_clear)

        # Signal should be restored (stale marker ignored)
        self.assertEqual(mock_color.call_count, 1)
        self.assertFalse(arbiter.signal_file().exists())
        # Stale marker should be deleted
        self.assertFalse(marker.exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_legacy_no_marker_dir_restores(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Legacy: saved_state.json exists but no marker dir -> clear restores."""
        # Create saved state directly (no marker dir)
        arbiter.signal_file().parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
        ]
        arbiter.signal_file().write_text(json.dumps(saved_state))

        # Clear (no session marker)
        args_clear = mock.Mock()
        args_clear.command = "clear"
        args_clear.config = str(self.config_path)
        args_clear.dry_run = False
        args_clear.all = False
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: True)):
            agent_signal.cmd_clear(args_clear)

        # Signal should be restored
        self.assertEqual(mock_color.call_count, 1)
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_all_restores_regardless_of_markers(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """clear --all restores regardless of remaining markers."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_a)

        # Session B sets signal
        mock_status.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_b)

        # Clear --all from session A
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear = mock.Mock()
        args_clear.command = "clear"
        args_clear.config = str(self.config_path)
        args_clear.dry_run = False
        args_clear.all = True
        fake_stdin_clear = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear)):
            agent_signal.cmd_clear(args_clear)

        # Signal should be restored despite session B's marker
        self.assertEqual(mock_color.call_count, 1)
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_all_deletes_all_session_markers(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """clear --all deletes all session marker files after restoring."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_a)

        # Session B sets signal
        mock_status.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_b)

        # Both markers should exist
        sessions_dir = agent_signal.signal_sessions_dir()
        self.assertTrue((sessions_dir / "session-A").exists())
        self.assertTrue((sessions_dir / "session-B").exists())

        # Clear --all
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear = mock.Mock()
        args_clear.command = "clear"
        args_clear.config = str(self.config_path)
        args_clear.dry_run = False
        args_clear.all = True
        fake_stdin_clear = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear)):
            agent_signal.cmd_clear(args_clear)

        # Signal should be restored
        self.assertEqual(mock_color.call_count, 1)
        # All session markers should be deleted
        self.assertFalse((sessions_dir / "session-A").exists())
        self.assertFalse((sessions_dir / "session-B").exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_all_then_new_session_clears_correctly(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """After clear --all, a new session's clear should restore (not be blocked by leftover markers)."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_a)

        # Session B sets signal
        mock_status.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_b)

        # Clear --all
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear_all = mock.Mock()
        args_clear_all.command = "clear"
        args_clear_all.config = str(self.config_path)
        args_clear_all.dry_run = False
        args_clear_all.all = True
        fake_stdin_clear_all = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear_all)):
            agent_signal.cmd_clear(args_clear_all)

        # Signal should be restored
        self.assertEqual(mock_color.call_count, 1)
        self.assertFalse(arbiter.signal_file().exists())

        # Now session C sets signal
        mock_status.reset_mock()
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_c = mock.Mock()
        args_c.command = "needs-input"
        args_c.config = str(self.config_path)
        args_c.dry_run = False
        args_c.force = False
        fake_stdin_c = json.dumps({"session_id": "session-C"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_c)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_c)

        # Session C clears
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear_c = mock.Mock()
        args_clear_c.command = "clear"
        args_clear_c.config = str(self.config_path)
        args_clear_c.dry_run = False
        args_clear_c.all = False
        fake_stdin_clear_c = json.dumps({"session_id": "session-C"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear_c)):
            agent_signal.cmd_clear(args_clear_c)

        # Signal should be restored (not blocked by leftover markers from A/B)
        self.assertEqual(mock_color.call_count, 1)
        self.assertFalse(arbiter.signal_file().exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_last_session_clear_deletes_all_markers(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """When the last session clears, all session markers should be deleted."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_a)

        # Session B sets signal
        mock_status.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args_b)

        # Session A clears (not last)
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear_a = mock.Mock()
        args_clear_a.command = "clear"
        args_clear_a.config = str(self.config_path)
        args_clear_a.dry_run = False
        args_clear_a.all = False
        fake_stdin_clear_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear_a)):
            agent_signal.cmd_clear(args_clear_a)

        # Signal should NOT be restored yet
        mock_color.assert_not_called()
        # Session A's marker should be gone, B's should remain
        sessions_dir = agent_signal.signal_sessions_dir()
        self.assertFalse((sessions_dir / "session-A").exists())
        self.assertTrue((sessions_dir / "session-B").exists())

        # Session B clears (last one)
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear_b = mock.Mock()
        args_clear_b.command = "clear"
        args_clear_b.config = str(self.config_path)
        args_clear_b.dry_run = False
        args_clear_b.all = False
        fake_stdin_clear_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear_b)):
            agent_signal.cmd_clear(args_clear_b)

        # Signal should be restored
        self.assertEqual(mock_color.call_count, 1)
        # All markers should be gone
        self.assertFalse((sessions_dir / "session-B").exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_session_id_sanitised_for_filename(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """A session_id with path separators or '..' is sanitised before use as a filename."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session with a malicious session_id
        evil_id = "..\\..\\evil"
        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False
        fake_stdin = json.dumps({"session_id": evil_id})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # The marker should be inside signal_sessions/, not escaped
        sessions_dir = agent_signal.signal_sessions_dir()
        self.assertTrue(sessions_dir.exists())

        # Count files in signal_sessions/ — should be exactly 1
        files_in_sessions = list(sessions_dir.iterdir())
        self.assertEqual(len(files_in_sessions), 1)

        # The file should be inside signal_sessions/
        marker = files_in_sessions[0]
        self.assertTrue(marker.is_file())
        self.assertEqual(marker.parent, sessions_dir)

        # The filename should be sanitised (backslashes replaced with underscores)
        self.assertEqual(marker.name, "______evil")

        # No files should have been created in parent directories
        parent_files = list(sessions_dir.parent.iterdir())
        # Should only contain signal_sessions/ and possibly other test artifacts,
        # but not "evil" or ".."
        for f in parent_files:
            self.assertNotEqual(f.name, "evil")

        # Clear with the same id should remove it
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear = mock.Mock()
        args_clear.command = "clear"
        args_clear.config = str(self.config_path)
        args_clear.dry_run = False
        args_clear.all = False
        fake_stdin_clear = json.dumps({"session_id": evil_id})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear)):
            agent_signal.cmd_clear(args_clear)

        # Marker should be gone
        self.assertFalse(marker.exists())

    def test_marker_name_function(self, mock_sleep):
        """marker_name sanitises various inputs correctly."""
        # Empty -> manual
        self.assertEqual(agent_signal.marker_name(""), "manual")
        # Normal UUID -> unchanged
        self.assertEqual(
            agent_signal.marker_name("550e8400-e29b-41d4-a716-446655440000"),
            "550e8400-e29b-41d4-a716-446655440000"
        )
        # Path separators -> underscores
        self.assertEqual(agent_signal.marker_name("..\\..\\evil"), "______evil")
        self.assertEqual(agent_signal.marker_name("../evil"), "___evil")
        self.assertEqual(agent_signal.marker_name("./evil"), "__evil")
        # Special characters -> underscores
        self.assertEqual(agent_signal.marker_name("a/b/c"), "a_b_c")
        self.assertEqual(agent_signal.marker_name("a:b:c"), "a_b_c")
        self.assertEqual(agent_signal.marker_name("a b c"), "a_b_c")
        # Long string -> truncated to 100
        long_id = "a" * 200
        self.assertEqual(len(agent_signal.marker_name(long_id)), 100)
        # Alphanumeric, underscore, hyphen -> unchanged
        self.assertEqual(agent_signal.marker_name("abc-123_def"), "abc-123_def")


@mock.patch("agent_signal.time.sleep")
class TestIgnoreMessagePatterns(StateDirMixin, unittest.TestCase):
    """Test that background-job 'finished' notifications are ignored."""

    def setUp(self):
        super().setUp()
        arbiter.set_mode("weather")
        self.config_path = self.state_dir / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
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
    def test_finished_message_ignored(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Message ending in ' finished' is ignored (no signal)."""
        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        fake_stdin = json.dumps({
            "session_id": "test-session",
            "message": "X12 Some ticket finished"
        })
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # No govee calls
        mock_status.assert_not_called()
        mock_turn.assert_not_called()
        mock_brightness.assert_not_called()
        mock_color.assert_not_called()

        # No saved state
        self.assertFalse(arbiter.signal_file().exists())

        # Log should contain skipped-ignored
        log_path = agent_signal.signal_log_path()
        self.assertTrue(log_path.exists())
        log_content = log_path.read_text()
        self.assertIn("needs-input skipped-ignored", log_content)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_needs_input_message_applied(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Message with 'needs your input' is NOT ignored (signal applied)."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        fake_stdin = json.dumps({
            "session_id": "test-session",
            "message": "X12 Some ticket needs your input: which?"
        })
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # Signal applied
        self.assertTrue(arbiter.signal_file().exists())
        self.assertEqual(mock_color.call_count, 1)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_permission_message_applied(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """'Claude needs your permission' is NOT ignored (signal applied)."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        fake_stdin = json.dumps({
            "session_id": "test-session",
            "message": "Claude needs your permission"
        })
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # Signal applied
        self.assertTrue(arbiter.signal_file().exists())
        self.assertEqual(mock_color.call_count, 1)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_invalid_regex_pattern_no_crash(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Invalid regex in ignore_message_patterns is skipped with warning, no crash."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Add invalid regex pattern
        self.config["signal"]["ignore_message_patterns"] = ["([", " finished$"]
        self.config_path.write_text(json.dumps(self.config))

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        fake_stdin = json.dumps({
            "session_id": "test-session",
            "message": "Claude needs your permission"
        })
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # Signal applied (invalid pattern skipped, valid pattern didn't match)
        self.assertTrue(arbiter.signal_file().exists())
        self.assertEqual(mock_color.call_count, 1)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_notification_type_in_log(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """notification_type appears in the log line when present."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        fake_stdin = json.dumps({
            "session_id": "test-session",
            "message": "Claude needs your permission",
            "notification_type": "idle_prompt"
        })
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # Log should contain notification_type
        log_path = agent_signal.signal_log_path()
        self.assertTrue(log_path.exists())
        log_content = log_path.read_text()
        self.assertIn("type=idle_prompt", log_content)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_completed_message_ignored(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """Message ending in ' completed' is ignored (no signal)."""
        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = False
        args.force = False

        fake_stdin = json.dumps({
            "session_id": "test-session",
            "message": "Task ABC completed"
        })
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                agent_signal.cmd_needs_input(args)

        # No govee calls
        mock_color.assert_not_called()

        # Log should contain skipped-ignored
        log_path = agent_signal.signal_log_path()
        self.assertTrue(log_path.exists())
        log_content = log_path.read_text()
        self.assertIn("needs-input skipped-ignored", log_content)


@mock.patch("agent_signal.time.sleep")
class TestStaleMarkers(StateDirMixin, unittest.TestCase):
    """Test stale marker detection based on dead PIDs."""

    def setUp(self):
        """Create a temp config and state directory for each test."""
        super().setUp()
        arbiter.set_mode("weather")
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
    def test_dead_pid_marker_does_not_block_clear(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """A marker with a dead pid does not keep other sessions' clear from restoring."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                with mock.patch("agent_signal.find_claude_pid", return_value=12345):
                    agent_signal.cmd_needs_input(args_a)

        # Session B sets signal
        mock_status.reset_mock()
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                with mock.patch("agent_signal.find_claude_pid", return_value=67890):
                    agent_signal.cmd_needs_input(args_b)

        # Both markers should exist
        sessions_dir = agent_signal.signal_sessions_dir()
        self.assertTrue((sessions_dir / "session-A").exists())
        self.assertTrue((sessions_dir / "session-B").exists())

        # Simulate session A's process dying (pid 12345 is dead)
        def pid_alive_side_effect(pid):
            if pid == 12345:
                return False  # dead
            return True  # alive

        with mock.patch("agent_signal.pid_alive", side_effect=pid_alive_side_effect):
            # Session B clears - should restore because session A's marker is stale
            mock_color.reset_mock()
            mock_brightness.reset_mock()
            mock_turn.reset_mock()
            args_clear_b = mock.Mock()
            args_clear_b.command = "clear"
            args_clear_b.config = str(self.config_path)
            args_clear_b.dry_run = False
            args_clear_b.all = False
            args_clear_b.stale = False
            fake_stdin_clear_b = json.dumps({"session_id": "session-B"})
            with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear_b)):
                agent_signal.cmd_clear(args_clear_b)

        # Signal should be restored (session A's marker was stale)
        mock_color.assert_called()

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_live_pid_marker_blocks_clear(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """A live pid does keep the signal."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                with mock.patch("agent_signal.find_claude_pid", return_value=12345):
                    agent_signal.cmd_needs_input(args_a)

        # Session B sets signal
        mock_status.reset_mock()
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                with mock.patch("agent_signal.find_claude_pid", return_value=67890):
                    agent_signal.cmd_needs_input(args_b)

        # Both markers should exist
        sessions_dir = agent_signal.signal_sessions_dir()
        self.assertTrue((sessions_dir / "session-A").exists())
        self.assertTrue((sessions_dir / "session-B").exists())

        # Both pids are alive
        with mock.patch("agent_signal.pid_alive", return_value=True):
            # Session B clears - should NOT restore because session A's marker is still active
            mock_color.reset_mock()
            mock_brightness.reset_mock()
            mock_turn.reset_mock()
            args_clear_b = mock.Mock()
            args_clear_b.command = "clear"
            args_clear_b.config = str(self.config_path)
            args_clear_b.dry_run = False
            args_clear_b.all = False
            args_clear_b.stale = False
            fake_stdin_clear_b = json.dumps({"session_id": "session-B"})
            with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear_b)):
                agent_signal.cmd_clear(args_clear_b)

        # Signal should NOT be restored (session A's marker is still active)
        mock_color.assert_not_called()

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_pidless_old_marker_uses_max_age(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """A pid-less old marker uses the max age."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                with mock.patch("agent_signal.find_claude_pid", return_value=12345):
                    agent_signal.cmd_needs_input(args_a)

        # Session B sets signal
        mock_status.reset_mock()
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                with mock.patch("agent_signal.find_claude_pid", return_value=67890):
                    agent_signal.cmd_needs_input(args_b)

        # Both markers should exist
        sessions_dir = agent_signal.signal_sessions_dir()
        self.assertTrue((sessions_dir / "session-A").exists())
        self.assertTrue((sessions_dir / "session-B").exists())

        # Make session A's marker old (3 hours) and pid-less
        from datetime import datetime, timezone, timedelta
        old_time = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        (sessions_dir / "session-A").write_text(old_time)

        # Session B clears - should restore because session A's marker is old
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_clear_b = mock.Mock()
        args_clear_b.command = "clear"
        args_clear_b.config = str(self.config_path)
        args_clear_b.dry_run = False
        args_clear_b.all = False
        args_clear_b.stale = False
        fake_stdin_clear_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_clear_b)):
            agent_signal.cmd_clear(args_clear_b)

        # Signal should be restored (session A's marker was old)
        mock_color.assert_called()

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_stale_restores_when_only_dead_markers(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """clear --stale restores when only dead markers are left."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                with mock.patch("agent_signal.find_claude_pid", return_value=12345):
                    agent_signal.cmd_needs_input(args_a)

        # Simulate session A's process dying
        def pid_alive_side_effect(pid):
            if pid == 12345:
                return False  # dead
            return True  # alive

        with mock.patch("agent_signal.pid_alive", side_effect=pid_alive_side_effect):
            # Run clear --stale
            mock_color.reset_mock()
            mock_brightness.reset_mock()
            mock_turn.reset_mock()
            args_stale = mock.Mock()
            args_stale.command = "clear"
            args_stale.config = str(self.config_path)
            args_stale.dry_run = False
            args_stale.all = False
            args_stale.stale = True
            with mock.patch("sys.stdin", mock.Mock(isatty=lambda: True)):
                agent_signal.cmd_clear(args_stale)

        # Signal should be restored
        mock_color.assert_called()

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_stale_noop_when_live_marker_remains(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """clear --stale does nothing (no govee calls) when a live one remains."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Session A sets signal
        args_a = mock.Mock()
        args_a.command = "needs-input"
        args_a.config = str(self.config_path)
        args_a.dry_run = False
        args_a.force = False
        fake_stdin_a = json.dumps({"session_id": "session-A"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_a)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                with mock.patch("agent_signal.find_claude_pid", return_value=12345):
                    agent_signal.cmd_needs_input(args_a)

        # Session B sets signal
        mock_status.reset_mock()
        mock_color.reset_mock()
        mock_brightness.reset_mock()
        mock_turn.reset_mock()
        args_b = mock.Mock()
        args_b.command = "needs-input"
        args_b.config = str(self.config_path)
        args_b.dry_run = False
        args_b.force = False
        fake_stdin_b = json.dumps({"session_id": "session-B"})
        with mock.patch("sys.stdin", mock.Mock(isatty=lambda: False, read=lambda: fake_stdin_b)):
            with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ATTENDED": "1"}):
                with mock.patch("agent_signal.find_claude_pid", return_value=67890):
                    agent_signal.cmd_needs_input(args_b)

        # Session A's process dies, session B's is alive
        def pid_alive_side_effect(pid):
            if pid == 12345:
                return False  # dead
            return True  # alive

        with mock.patch("agent_signal.pid_alive", side_effect=pid_alive_side_effect):
            # Run clear --stale
            mock_color.reset_mock()
            mock_brightness.reset_mock()
            mock_turn.reset_mock()
            args_stale = mock.Mock()
            args_stale.command = "clear"
            args_stale.config = str(self.config_path)
            args_stale.dry_run = False
            args_stale.all = False
            args_stale.stale = True
            with mock.patch("sys.stdin", mock.Mock(isatty=lambda: True)):
                agent_signal.cmd_clear(args_stale)

        # Signal should NOT be restored (session B's marker is still active)
        mock_color.assert_not_called()

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_find_claude_pid_returns_none_on_error(
        self, mock_color, mock_brightness, mock_turn, mock_status, mock_sleep
    ):
        """find_claude_pid returns None when the toolhelp call raises."""
        import platform

        # Mock platform to be Windows
        with mock.patch("platform.system", return_value="Windows"):
            # Mock ctypes to raise an exception
            with mock.patch("ctypes.WinDLL", side_effect=Exception("test error")):
                result = agent_signal.find_claude_pid()
                self.assertIsNone(result)


class TestSweepAndRestore(StateDirMixin, unittest.TestCase):
    """Test sweep_and_restore() behavior."""

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
        arbiter.set_mode("weather")

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_sweep_and_restore_zero_markers_restores(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """signal active + zero markers -> sweep_and_restore() restores."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Create signal file (saved_state.json) but no session markers
        signal_path = arbiter.signal_file()
        signal_path.parent.mkdir(parents=True, exist_ok=True)
        signal_path.write_text("[]")

        # Run sweep_and_restore
        result = agent_signal.sweep_and_restore(config_path=str(self.config_path))

        # Should have restored
        self.assertTrue(result)
        mock_color.assert_called()
        # Signal file should be gone
        self.assertFalse(signal_path.exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    @mock.patch("agent_signal.pid_alive", return_value=True)
    def test_sweep_and_restore_live_marker_no_restore(
        self, mock_pid_alive, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """signal active + one live marker -> no govee calls, returns False."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Create signal file and a live session marker
        signal_path = arbiter.signal_file()
        signal_path.parent.mkdir(parents=True, exist_ok=True)
        signal_path.write_text("[]")

        sessions_dir = agent_signal.signal_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        (sessions_dir / "test-session").write_text(
            json.dumps({"pid": os.getpid(), "created": now})
        )

        # Run sweep_and_restore
        result = agent_signal.sweep_and_restore(config_path=str(self.config_path))

        # Should NOT have restored
        self.assertFalse(result)
        mock_color.assert_not_called()
        # Signal file should still be there
        self.assertTrue(signal_path.exists())

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    @mock.patch("agent_signal.pid_alive", return_value=False)
    def test_sweep_and_restore_dead_pid_restores(
        self, mock_pid_alive, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """signal active + one marker with a dead pid -> marker deleted, restore happens."""
        mock_status.return_value = {
            "msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}
        }

        # Create signal file and a session marker with a dead pid
        signal_path = arbiter.signal_file()
        signal_path.parent.mkdir(parents=True, exist_ok=True)
        signal_path.write_text("[]")

        sessions_dir = agent_signal.signal_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        (sessions_dir / "test-session").write_text(
            json.dumps({"pid": 99999, "created": now})
        )

        # Run sweep_and_restore
        result = agent_signal.sweep_and_restore(config_path=str(self.config_path))

        # Should have restored
        self.assertTrue(result)
        mock_color.assert_called()
        # Marker should be deleted
        self.assertFalse((sessions_dir / "test-session").exists())
        # Signal file should be gone
        self.assertFalse(signal_path.exists())

    @mock.patch("agent_signal._marker_is_stale")
    def test_get_active_session_markers_calls_marker_is_stale(self, mock_is_stale):
        """get_active_session_markers calls _marker_is_stale."""
        mock_is_stale.return_value = False

        sessions_dir = agent_signal.signal_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        (sessions_dir / "test-session").write_text(now)

        agent_signal.get_active_session_markers()

        mock_is_stale.assert_called()

    @mock.patch("agent_signal._marker_is_stale")
    def test_sweep_stale_markers_calls_marker_is_stale(self, mock_is_stale):
        """sweep_stale_markers calls _marker_is_stale."""
        mock_is_stale.return_value = True

        sessions_dir = agent_signal.signal_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        (sessions_dir / "test-session").write_text(now)

        agent_signal.sweep_stale_markers()

        mock_is_stale.assert_called()

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_sweep_and_restore_no_devices_returns_false(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """sweep_and_restore with no devices returns False (no SystemExit)."""
        # Create config with no devices
        no_devices_config = {
            "signal": {
                "color": "#ff6a00",
                "brightness": 100,
                "blink": False,
            },
        }
        no_devices_path = self.state_dir / "config_no_devices.json"
        no_devices_path.write_text(json.dumps(no_devices_config))

        # Create signal file
        signal_path = arbiter.signal_file()
        signal_path.parent.mkdir(parents=True, exist_ok=True)
        signal_path.write_text("[]")

        # Run sweep_and_restore - should return False, not raise SystemExit
        result = agent_signal.sweep_and_restore(config_path=str(no_devices_path))
        self.assertFalse(result)

    @mock.patch("agent_signal.govee.color")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.turn")
    def test_sweep_and_restore_race_with_needs_input(
        self, mock_turn, mock_brightness, mock_color
    ):
        """sweep_and_restore does not clear a signal being set right now.

        Simulates the race: needs-input has written saved_state.json but not
        yet its session marker. sweep_and_restore acquires the lock, sees the
        signal, and would restore — but the re-check under the lock catches
        the marker that needs-input writes while holding the lock.
        """
        # Create signal file (saved_state.json) but no session markers yet
        signal_path = arbiter.signal_file()
        signal_path.parent.mkdir(parents=True, exist_ok=True)
        signal_path.write_text("[]")

        # Patch acquire_lock to write a marker (simulating needs-input writing
        # its marker while sweep is waiting for the lock)
        def fake_acquire_lock(dry_run=False):
            sessions_dir = agent_signal.signal_sessions_dir()
            sessions_dir.mkdir(parents=True, exist_ok=True)
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            (sessions_dir / "live-session").write_text(
                json.dumps({"pid": os.getpid(), "created": now})
            )
            return True

        with mock.patch("agent_signal.acquire_lock", side_effect=fake_acquire_lock):
            with mock.patch("agent_signal.pid_alive", return_value=True):
                result = agent_signal.sweep_and_restore(config_path=str(self.config_path))

        # Should NOT have restored (live marker was detected under the lock)
        self.assertFalse(result)
        mock_color.assert_not_called()
        # Signal file should still be there
        self.assertTrue(signal_path.exists())
        # Marker should still be there
        sessions_dir = agent_signal.signal_sessions_dir()
        self.assertTrue((sessions_dir / "live-session").exists())

    def test_marker_is_stale_handles_corrupt_json(self):
        """_marker_is_stale handles null, number, and naive timestamp markers."""
        sessions_dir = agent_signal.signal_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        # null JSON -> AttributeError on .get -> stale
        null_marker = sessions_dir / "null-marker"
        null_marker.write_text("null")
        self.assertTrue(agent_signal._marker_is_stale(null_marker, now, 2))

        # Number JSON -> AttributeError on .get -> stale
        num_marker = sessions_dir / "num-marker"
        num_marker.write_text("42")
        self.assertTrue(agent_signal._marker_is_stale(num_marker, now, 2))

        # Naive ISO timestamp (no offset) -> TypeError on aware - naive -> stale
        naive_marker = sessions_dir / "naive-marker"
        naive_marker.write_text("2026-01-01T00:00:00")
        self.assertTrue(agent_signal._marker_is_stale(naive_marker, now, 2))

    def test_get_active_session_markers_handles_corrupt_markers(self):
        """get_active_session_markers does not raise on corrupt markers."""
        sessions_dir = agent_signal.signal_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        # Write corrupt markers
        (sessions_dir / "null-marker").write_text("null")
        (sessions_dir / "num-marker").write_text("42")
        (sessions_dir / "naive-marker").write_text("2026-01-01T00:00:00")

        # Should not raise
        active = agent_signal.get_active_session_markers()

        # All corrupt markers should be treated as stale and deleted
        self.assertEqual(active, [])
        self.assertFalse((sessions_dir / "null-marker").exists())
        self.assertFalse((sessions_dir / "num-marker").exists())
        self.assertFalse((sessions_dir / "naive-marker").exists())


class TestSweepThrottle(unittest.TestCase):
    """Test sweep_and_restore throttle in game_sync and weather_sync loops."""

    @mock.patch("agent_signal.sweep_and_restore")
    @mock.patch("game_sync.running_processes")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.monotonic")
    @mock.patch("time.sleep")
    def test_game_sync_sweep_throttle(
        self, mock_sleep, mock_monotonic, mock_brightness, mock_color, mock_processes, mock_sweep
    ):
        """game_sync loop calls sweep_and_restore once while blocked < 60s, again after 60s."""
        import arbiter

        # Create a temp state dir
        import tempfile
        from pathlib import Path
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        state_dir = Path(tmpdir.name)

        with mock.patch.object(arbiter, "STATE_DIR", state_dir):
            # Create signal file
            signal_path = arbiter.signal_file()
            signal_path.parent.mkdir(parents=True, exist_ok=True)
            signal_path.write_text("[]")

            mock_processes.return_value = {"testgame.exe"}
            config = {
                "devices": [{"name": "left", "ip": "192.168.1.50"}],
                "games": [
                    {"name": "Test Game", "exe": "testgame.exe", "color": "red", "brightness": 80},
                ],
                "default": {"color": "white", "brightness": 40},
            }

            # Simulate time: 0, 10, 20, 30, 40, 50, 60, 70
            mock_monotonic.side_effect = [0, 10, 20, 30, 40, 50, 60, 70]

            call_count = [0]
            def sleep_side_effect(seconds):
                call_count[0] += 1
                if call_count[0] >= 7:
                    raise KeyboardInterrupt()
            mock_sleep.side_effect = sleep_side_effect

            try:
                game_sync.run(config, interval=1)
            except KeyboardInterrupt:
                pass

            # sweep_and_restore should be called twice: at t=0 and t=60
            self.assertEqual(mock_sweep.call_count, 2)

    @mock.patch("agent_signal.sweep_and_restore")
    @mock.patch("arbiter.weather_blocked")
    @mock.patch("time.sleep")
    def test_weather_sync_sweep_throttle(
        self, mock_sleep, mock_weather_blocked, mock_sweep
    ):
        """weather_sync loop calls sweep_and_restore once while blocked < 60s, again after 60s."""
        import arbiter

        # Create a temp state dir
        import tempfile
        from pathlib import Path
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        state_dir = Path(tmpdir.name)

        with mock.patch.object(arbiter, "STATE_DIR", state_dir):
            # Create signal file
            signal_path = arbiter.signal_file()
            signal_path.parent.mkdir(parents=True, exist_ok=True)
            signal_path.write_text("[]")

            # Make weather_blocked return True so the loop takes the blocked branch
            mock_weather_blocked.return_value = True

            config = {
                "devices": [{"name": "left", "ip": "192.168.1.50"}],
                "default": {"color": "white", "brightness": 40},
                "weather": {"latitude": 40.0, "longitude": -74.0},
            }

            # Fake clock: 0, 10, 20, 30, 40, 50, 60, 70
            clock_values = [0, 10, 20, 30, 40, 50, 60, 70]
            clock_idx = [0]
            def fake_clock():
                val = clock_values[clock_idx[0]]
                clock_idx[0] += 1
                return val

            call_count = [0]
            def sleep_side_effect(seconds):
                call_count[0] += 1
                if call_count[0] >= 7:
                    raise KeyboardInterrupt()
            mock_sleep.side_effect = sleep_side_effect

            try:
                weather_sync.run(config, once=False, interval=1, time_fn=fake_clock)
            except KeyboardInterrupt:
                pass

            # sweep_and_restore should be called twice: at t=0 and t=60
            self.assertEqual(mock_sweep.call_count, 2)

    @mock.patch("agent_signal.sweep_and_restore")
    @mock.patch("game_sync.running_processes")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.monotonic")
    @mock.patch("time.sleep")
    def test_game_sync_logs_sweep_failure(
        self, mock_sleep, mock_monotonic, mock_brightness, mock_color, mock_processes, mock_sweep
    ):
        """game_sync logs a warning when sweep_and_restore raises."""
        import arbiter

        # Create a temp state dir
        import tempfile
        from pathlib import Path
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        state_dir = Path(tmpdir.name)

        with mock.patch.object(arbiter, "STATE_DIR", state_dir):
            # Create signal file
            signal_path = arbiter.signal_file()
            signal_path.parent.mkdir(parents=True, exist_ok=True)
            signal_path.write_text("[]")

            mock_processes.return_value = {"testgame.exe"}
            config = {
                "devices": [{"name": "left", "ip": "192.168.1.50"}],
                "games": [
                    {"name": "Test Game", "exe": "testgame.exe", "color": "red", "brightness": 80},
                ],
                "default": {"color": "white", "brightness": 40},
            }

            # Make sweep_and_restore raise
            mock_sweep.side_effect = RuntimeError("test sweep failure")

            mock_monotonic.return_value = 0

            call_count = [0]
            def sleep_side_effect(seconds):
                call_count[0] += 1
                if call_count[0] >= 2:
                    raise KeyboardInterrupt()
            mock_sleep.side_effect = sleep_side_effect

            with self.assertLogs("game_sync", level="WARNING") as log_ctx:
                try:
                    game_sync.run(config, interval=1)
                except KeyboardInterrupt:
                    pass

            # Should have logged the warning
            self.assertTrue(any("sweep_and_restore failed" in record.message for record in log_ctx.records))


if __name__ == "__main__":
    unittest.main()
