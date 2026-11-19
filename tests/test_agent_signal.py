"""Tests for agent_signal.py using unittest.mock to fake govee functions."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
import agent_signal
import govee


class TestSignalNeedsInput(unittest.TestCase):
    """Test the needs-input command."""

    def setUp(self):
        """Create a temp config and state directory for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.json"
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

        # Mock the state file path
        self.original_state_file = agent_signal.SAVED_STATE_FILE
        agent_signal.SAVED_STATE_FILE = Path(self.temp_dir.name) / "state" / "saved_state.json"

    def tearDown(self):
        """Clean up temp directory."""
        agent_signal.SAVED_STATE_FILE = self.original_state_file
        self.temp_dir.cleanup()

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
        self.assertTrue(agent_signal.SAVED_STATE_FILE.exists())
        saved = json.loads(agent_signal.SAVED_STATE_FILE.read_text())
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
        saved = json.loads(agent_signal.SAVED_STATE_FILE.read_text())
        self.assertEqual(saved[0]["brightness"], 50)

    @mock.patch("agent_signal.govee.status")
    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_status_exception_does_not_crash(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """govee.status raising an exception does not crash needs-input."""
        mock_status.side_effect = [
            Exception("network error"),
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

        saved = json.loads(agent_signal.SAVED_STATE_FILE.read_text())
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

        saved = json.loads(agent_signal.SAVED_STATE_FILE.read_text())
        self.assertEqual(saved[0]["colorTemInKelvin"], 4000)
        self.assertEqual(saved[1]["colorTemInKelvin"], 0)


class TestSignalClear(unittest.TestCase):
    """Test the clear command."""

    def setUp(self):
        """Create a temp config and state directory for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
        }
        self.config_path.write_text(json.dumps(self.config))

        # Mock the state file path
        self.original_state_file = agent_signal.SAVED_STATE_FILE
        agent_signal.SAVED_STATE_FILE = Path(self.temp_dir.name) / "state" / "saved_state.json"

    def tearDown(self):
        """Clean up temp directory."""
        agent_signal.SAVED_STATE_FILE = self.original_state_file
        self.temp_dir.cleanup()

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_restores_and_deletes_file(self, mock_color, mock_brightness, mock_turn):
        """clear restores saved state and deletes the file."""
        # Create a saved state file
        agent_signal.SAVED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
            {"ip": "192.168.1.51", "on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}},
        ]
        agent_signal.SAVED_STATE_FILE.write_text(json.dumps(saved_state))

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
        self.assertFalse(agent_signal.SAVED_STATE_FILE.exists())

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
        args.config = str(Path(self.temp_dir.name) / "nonexistent.json")
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
        agent_signal.SAVED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": False, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
        ]
        agent_signal.SAVED_STATE_FILE.write_text(json.dumps(saved_state))

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # For the off device, turn(False) must be the last call for that IP
        # Check that brightness and color were called before turn(False)
        brightness_calls = [c for c in mock_brightness.call_args_list if c[0][0] == "192.168.1.50"]
        color_calls = [c for c in mock_color.call_args_list if c[0][0] == "192.168.1.50"]
        turn_off_calls = [c for c in mock_turn.call_args_list if c[0][0] == "192.168.1.50" and c[0][1] is False]

        self.assertEqual(len(brightness_calls), 1)
        self.assertEqual(len(color_calls), 1)
        self.assertEqual(len(turn_off_calls), 1)

        # Verify order: brightness and color before turn off
        all_calls = []
        for c in mock_brightness.call_args_list:
            if c[0][0] == "192.168.1.50":
                all_calls.append(("brightness", c))
        for c in mock_color.call_args_list:
            if c[0][0] == "192.168.1.50":
                all_calls.append(("color", c))
        for c in mock_turn.call_args_list:
            if c[0][0] == "192.168.1.50" and c[0][1] is False:
                all_calls.append(("turn_off", c))

        # turn_off should be last
        self.assertEqual(all_calls[-1][0], "turn_off")

    @mock.patch("agent_signal.govee.turn")
    @mock.patch("agent_signal.govee.brightness")
    @mock.patch("agent_signal.govee.color")
    def test_clear_on_device_turn_on_first(
        self, mock_color, mock_brightness, mock_turn
    ):
        """clear with a saved 'on': true device sends turn(ip, True) and never turn(ip, False)."""
        agent_signal.SAVED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
        ]
        agent_signal.SAVED_STATE_FILE.write_text(json.dumps(saved_state))

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        agent_signal.cmd_clear(args)

        # turn(True) should be called
        turn_on_calls = [c for c in mock_turn.call_args_list if c[0][0] == "192.168.1.50" and c[0][1] is True]
        turn_off_calls = [c for c in mock_turn.call_args_list if c[0][0] == "192.168.1.50" and c[0][1] is False]

        self.assertEqual(len(turn_on_calls), 1)
        self.assertEqual(len(turn_off_calls), 0)


class TestSignalDryRun(unittest.TestCase):
    """Test dry-run mode."""

    def setUp(self):
        """Create a temp config for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "signal": {"color": "#ff6a00", "brightness": 100, "blink": False},
        }
        self.config_path.write_text(json.dumps(self.config))

        self.original_state_file = agent_signal.SAVED_STATE_FILE
        agent_signal.SAVED_STATE_FILE = Path(self.temp_dir.name) / "state" / "saved_state.json"

    def tearDown(self):
        """Clean up temp directory."""
        agent_signal.SAVED_STATE_FILE = self.original_state_file
        self.temp_dir.cleanup()

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


if __name__ == "__main__":
    unittest.main()
