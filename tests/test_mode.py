"""Tests for mode.py CLI."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import arbiter
from helpers import StateDirMixin


class TestSwitchOff(StateDirMixin, unittest.TestCase):
    """Test switch("off") behaviour."""

    def test_off_sends_turn_off_per_device(self):
        """switch("off") sends turn off once per device."""
        config = {"devices": [{"ip": "192.168.1.1"}, {"ip": "192.168.1.2"}]}
        with mock.patch("govee.turn") as mock_turn:
            import mode
            mode.switch("off", config)
        self.assertEqual(mock_turn.call_count, 2)
        mock_turn.assert_any_call("192.168.1.1", False)
        mock_turn.assert_any_call("192.168.1.2", False)

    def test_off_with_signal_active_sends_nothing(self):
        """switch("off") with signal active sends nothing."""
        config = {"devices": [{"ip": "192.168.1.1"}]}
        # Create saved_state.json to simulate active signal
        (arbiter.STATE_DIR / "saved_state.json").write_text("[]")
        with mock.patch("govee.turn") as mock_turn:
            import mode
            mode.switch("off", config)
        mock_turn.assert_not_called()

    def test_off_dry_run_sends_nothing(self):
        """switch("off") with dry_run sends nothing and doesn't change mode.json."""
        config = {"devices": [{"ip": "192.168.1.1"}]}
        with mock.patch("govee.turn") as mock_turn:
            import mode
            mode.switch("off", config, dry_run=True)
        mock_turn.assert_not_called()
        self.assertEqual(arbiter.get_mode(), "off")  # unchanged (default)

    def test_off_catches_oserror_per_device(self):
        """switch("off") catches OSError per device and continues."""
        config = {"devices": [{"ip": "192.168.1.1"}, {"ip": "192.168.1.2"}]}
        import mode
        with mock.patch("govee.turn", side_effect=[OSError("fail"), None]) as mock_turn:
            mode.switch("off", config)
        self.assertEqual(mock_turn.call_count, 2)


class TestSwitchWeather(StateDirMixin, unittest.TestCase):
    """Test switch("weather") behaviour."""

    def test_weather_sends_nothing(self):
        """switch("weather") sends nothing to devices."""
        config = {"devices": [{"ip": "192.168.1.1"}]}
        with mock.patch("govee.turn") as mock_turn:
            import mode
            mode.switch("weather", config)
        mock_turn.assert_not_called()
        self.assertEqual(arbiter.get_mode(), "weather")


class TestSwitchGame(StateDirMixin, unittest.TestCase):
    """Test switch("game") behaviour."""

    def test_game_sends_nothing(self):
        """switch("game") sends nothing to devices."""
        config = {"devices": [{"ip": "192.168.1.1"}]}
        with mock.patch("govee.turn") as mock_turn:
            import mode
            mode.switch("game", config)
        mock_turn.assert_not_called()
        self.assertEqual(arbiter.get_mode(), "game")


class TestSwitchMusic(StateDirMixin, unittest.TestCase):
    """Test switch("music") behaviour."""

    def test_music_sends_nothing(self):
        """switch("music") sends nothing to devices."""
        config = {"devices": [{"ip": "192.168.1.1"}]}
        with mock.patch("govee.turn") as mock_turn:
            import mode
            mode.switch("music", config)
        mock_turn.assert_not_called()
        self.assertEqual(arbiter.get_mode(), "music")


class TestCliGet(StateDirMixin, unittest.TestCase):
    """Test CLI 'get' command."""

    def test_get_prints_mode(self):
        """mode.py get prints the current mode."""
        arbiter.set_mode("weather")
        import mode
        with mock.patch("sys.argv", ["mode.py", "get"]):
            with mock.patch("builtins.print") as mock_print:
                try:
                    mode.main()
                except SystemExit:
                    pass
        # Check that "weather" was printed
        calls = [str(call) for call in mock_print.call_args_list]
        self.assertTrue(any("weather" in c for c in calls))


class TestCliSet(StateDirMixin, unittest.TestCase):
    """Test CLI 'set' command."""

    def test_set_unknown_mode_exits_2(self):
        """mode.py set disco exits 2 and doesn't change mode.json."""
        import mode
        with mock.patch("sys.argv", ["mode.py", "set", "disco"]):
            with mock.patch("sys.stderr"):
                try:
                    mode.main()
                except SystemExit as e:
                    self.assertEqual(e.code, 2)
        self.assertEqual(arbiter.get_mode(), "off")  # unchanged

    def test_set_valid_mode_exits_0(self):
        """mode.py set weather exits 0 and sets the mode."""
        import mode
        with mock.patch("sys.argv", ["mode.py", "set", "weather"]):
            with mock.patch("sys.stdout"):
                try:
                    mode.main()
                except SystemExit as e:
                    self.assertEqual(e.code, 0)
        self.assertEqual(arbiter.get_mode(), "weather")


if __name__ == "__main__":
    unittest.main()
