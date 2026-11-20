"""Tests for mode.py CLI."""

import json
import sys
import tempfile
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
            with mock.patch("music_sync.cmd_start"):
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
                with self.assertRaises(SystemExit) as cm:
                    mode.main()
                self.assertEqual(cm.exception.code, 0)
        # Check that "weather" was printed
        calls = [str(call) for call in mock_print.call_args_list]
        self.assertTrue(any("weather" in c for c in calls))


class TestCliSet(StateDirMixin, unittest.TestCase):
    """Test CLI 'set' command."""

    def setUp(self):
        super().setUp()
        # Create a temp config file for CLI tests
        self._config_tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump({"devices": [{"ip": "192.168.1.50"}]}, self._config_tmp)
        self._config_tmp.close()
        self.config_path = self._config_tmp.name
        self.addCleanup(Path(self.config_path).unlink)

    def test_set_unknown_mode_exits_2(self):
        """mode.py set disco exits 2 and doesn't change mode.json."""
        import mode
        with mock.patch("sys.argv", ["mode.py", "set", "disco"]):
            with mock.patch("sys.stderr"):
                with self.assertRaises(SystemExit) as cm:
                    mode.main()
                self.assertEqual(cm.exception.code, 2)
        self.assertEqual(arbiter.get_mode(), "off")  # unchanged

    def test_set_valid_mode_exits_0(self):
        """mode.py set weather exits 0 and sets the mode."""
        import mode
        with mock.patch("sys.argv", ["mode.py", "set", "weather", "--config", self.config_path]):
            with mock.patch("govee.turn"):
                with mock.patch("sys.stdout"):
                    with self.assertRaises(SystemExit) as cm:
                        mode.main()
                    self.assertEqual(cm.exception.code, 0)
        self.assertEqual(arbiter.get_mode(), "weather")

    def test_set_missing_config_exits_1(self):
        """mode.py set weather --config <missing> exits 1 and leaves mode unchanged."""
        import mode
        missing = str(Path(self.state_dir) / "does_not_exist.json")
        with mock.patch("sys.argv", ["mode.py", "set", "weather", "--config", missing]):
            with mock.patch("sys.stderr"):
                with self.assertRaises(SystemExit) as cm:
                    mode.main()
                self.assertEqual(cm.exception.code, 1)
        self.assertEqual(arbiter.get_mode(), "off")  # unchanged

    def test_set_off_dry_run_exits_0_no_turn(self):
        """mode.py set off --dry-run exits 0, govee.turn not called, mode unchanged."""
        import mode
        with mock.patch("sys.argv", ["mode.py", "set", "off", "--dry-run", "--config", self.config_path]):
            with mock.patch("govee.turn") as mock_turn:
                with mock.patch("sys.stdout"):
                    with self.assertRaises(SystemExit) as cm:
                        mode.main()
                    self.assertEqual(cm.exception.code, 0)
                mock_turn.assert_not_called()
        self.assertEqual(arbiter.get_mode(), "off")  # unchanged (dry-run)


class TestSetModePermissionError(StateDirMixin, unittest.TestCase):
    """Test set_mode() raises PermissionError after 3 retries."""

    def setUp(self):
        super().setUp()
        # Create a temp config file for CLI tests
        self._config_tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump({"devices": [{"ip": "192.168.1.50"}]}, self._config_tmp)
        self._config_tmp.close()
        self.config_path = self._config_tmp.name
        self.addCleanup(Path(self.config_path).unlink)

    def test_set_mode_raises_on_persistent_permission_error(self):
        """set_mode raises PermissionError when os.replace always fails."""
        # First set a mode successfully (no patch)
        arbiter.set_mode("weather")
        self.assertEqual(arbiter.get_mode(), "weather")

        # Now patch os.replace to always fail
        with mock.patch("arbiter.time.sleep"):
            with mock.patch("arbiter.os.replace", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    arbiter.set_mode("game")

        # Mode should still be "weather"
        self.assertEqual(arbiter.get_mode(), "weather")

        # No temp file should be left behind
        tmp_files = list(self.state_dir.glob("mode.json.tmp.*"))
        self.assertEqual(len(tmp_files), 0)

    def test_cli_exits_1_on_set_mode_failure(self):
        """CLI exits 1 when set_mode raises PermissionError."""
        import mode

        # First set a mode successfully
        arbiter.set_mode("weather")

        with mock.patch("arbiter.time.sleep"):
            with mock.patch("arbiter.os.replace", side_effect=PermissionError("locked")):
                with mock.patch("sys.argv", ["mode.py", "set", "game", "--config", self.config_path]):
                    with mock.patch("sys.stderr") as mock_stderr:
                        with self.assertRaises(SystemExit) as cm:
                            mode.main()
                        self.assertEqual(cm.exception.code, 1)
                    # Check error message was printed to stderr
                    stderr_output = "".join(
                        call[0][0] for call in mock_stderr.write.call_args_list
                        if call[0]
                    )
                    self.assertIn("could not set mode", stderr_output)

        # Mode should still be "weather"
        self.assertEqual(arbiter.get_mode(), "weather")


class TestNoRealPopen(unittest.TestCase):
    """Test that the Popen guard in tests/__init__.py works."""

    def test_popen_guard_raises(self):
        """Calling subprocess.Popen without a mock raises AssertionError."""
        import subprocess
        with self.assertRaises(AssertionError) as cm:
            subprocess.Popen(["python", "--version"])
        self.assertIn("real subprocess.Popen", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
