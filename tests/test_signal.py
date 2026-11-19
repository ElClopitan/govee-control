"""Tests for signal.py using unittest.mock to fake govee functions."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
import signal
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
        self.original_state_file = signal.SAVED_STATE_FILE
        signal.SAVED_STATE_FILE = Path(self.temp_dir.name) / "state" / "saved_state.json"

    def tearDown(self):
        """Clean up temp directory."""
        signal.SAVED_STATE_FILE = self.original_state_file
        self.temp_dir.cleanup()

    @mock.patch("signal.govee.status")
    @mock.patch("signal.govee.turn")
    @mock.patch("signal.govee.brightness")
    @mock.patch("signal.govee.color")
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

        signal.cmd_needs_input(args)

        # Verify state was saved
        self.assertTrue(signal.SAVED_STATE_FILE.exists())
        saved = json.loads(signal.SAVED_STATE_FILE.read_text())
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]["ip"], "192.168.1.50")
        self.assertEqual(saved[0]["brightness"], 50)

        # Verify signal colour was set
        self.assertEqual(mock_color.call_count, 2)
        # Parse #ff6a00 -> (255, 106, 0)
        self.assertEqual(mock_color.call_args_list[0][0][1:], (255, 106, 0))

    @mock.patch("signal.govee.status")
    @mock.patch("signal.govee.turn")
    @mock.patch("signal.govee.brightness")
    @mock.patch("signal.govee.color")
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
        signal.cmd_needs_input(args1)

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
        signal.cmd_needs_input(args2)

        # Status should not have been called on second invocation
        mock_status.assert_not_called()

        # Saved state should still have original values
        saved = json.loads(signal.SAVED_STATE_FILE.read_text())
        self.assertEqual(saved[0]["brightness"], 50)

    @mock.patch("signal.govee.status")
    @mock.patch("signal.govee.turn")
    @mock.patch("signal.govee.brightness")
    @mock.patch("signal.govee.color")
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
        signal.cmd_needs_input(args)

        # Signal colour should still be set
        self.assertEqual(mock_color.call_count, 2)


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
        self.original_state_file = signal.SAVED_STATE_FILE
        signal.SAVED_STATE_FILE = Path(self.temp_dir.name) / "state" / "saved_state.json"

    def tearDown(self):
        """Clean up temp directory."""
        signal.SAVED_STATE_FILE = self.original_state_file
        self.temp_dir.cleanup()

    @mock.patch("signal.govee.turn")
    @mock.patch("signal.govee.brightness")
    @mock.patch("signal.govee.color")
    def test_clear_restores_and_deletes_file(self, mock_color, mock_brightness, mock_turn):
        """clear restores saved state and deletes the file."""
        # Create a saved state file
        signal.SAVED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        saved_state = [
            {"ip": "192.168.1.50", "on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}},
            {"ip": "192.168.1.51", "on": True, "brightness": 60, "color": {"r": 0, "g": 0, "b": 255}},
        ]
        signal.SAVED_STATE_FILE.write_text(json.dumps(saved_state))

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        signal.cmd_clear(args)

        # Verify state was restored
        self.assertEqual(mock_brightness.call_count, 2)
        self.assertEqual(mock_brightness.call_args_list[0][0][1], 50)
        self.assertEqual(mock_brightness.call_args_list[1][0][1], 60)

        # Verify file was deleted
        self.assertFalse(signal.SAVED_STATE_FILE.exists())

    @mock.patch("signal.govee.turn")
    @mock.patch("signal.govee.brightness")
    @mock.patch("signal.govee.color")
    def test_clear_no_saved_file_no_default_sends_nothing(
        self, mock_color, mock_brightness, mock_turn
    ):
        """clear with no saved file and no default sends nothing (negative test)."""
        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        signal.cmd_clear(args)

        # No govee commands should have been sent
        mock_turn.assert_not_called()
        mock_brightness.assert_not_called()
        mock_color.assert_not_called()

    @mock.patch("signal.govee.turn")
    @mock.patch("signal.govee.brightness")
    @mock.patch("signal.govee.color")
    def test_clear_applies_default_when_no_saved_state(
        self, mock_color, mock_brightness, mock_turn
    ):
        """clear applies default config when no saved state exists."""
        # Add default to config
        self.config["default"] = {"color": "white", "brightness": 40}
        self.config_path.write_text(json.dumps(self.config))

        args = mock.Mock()
        args.command = "clear"
        args.config = str(self.config_path)
        args.dry_run = False

        signal.cmd_clear(args)

        # Default should be applied
        self.assertEqual(mock_brightness.call_count, 2)
        self.assertEqual(mock_brightness.call_args_list[0][0][1], 40)


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

        self.original_state_file = signal.SAVED_STATE_FILE
        signal.SAVED_STATE_FILE = Path(self.temp_dir.name) / "state" / "saved_state.json"

    def tearDown(self):
        """Clean up temp directory."""
        signal.SAVED_STATE_FILE = self.original_state_file
        self.temp_dir.cleanup()

    @mock.patch("signal.govee.status")
    @mock.patch("signal.govee.turn")
    @mock.patch("signal.govee.brightness")
    @mock.patch("signal.govee.color")
    def test_dry_run_does_not_send_commands(
        self, mock_color, mock_brightness, mock_turn, mock_status
    ):
        """dry-run mode prints but does not send commands."""
        mock_status.return_value = {"msg": {"data": {"on": True, "brightness": 50, "color": {"r": 255, "g": 255, "b": 255}}}}

        args = mock.Mock()
        args.command = "needs-input"
        args.config = str(self.config_path)
        args.dry_run = True

        signal.cmd_needs_input(args)

        # No actual commands sent
        mock_turn.assert_not_called()
        mock_brightness.assert_not_called()
        mock_color.assert_not_called()


if __name__ == "__main__":
    unittest.main()
