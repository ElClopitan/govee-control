"""Tests for game_sync.py."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
import game_sync
import govee


class TestPickProfile(unittest.TestCase):
    """Test the pure pick_profile function."""

    def test_match(self):
        """Matching exe returns the game profile."""
        games = [
            {"name": "Game A", "exe": "gamea.exe", "color": "red", "brightness": 50},
        ]
        processes = {"chrome.exe", "gamea.exe"}
        result = game_sync.pick_profile(processes, games)
        self.assertEqual(result["name"], "Game A")

    def test_case_insensitive(self):
        """Exe matching is case-insensitive."""
        games = [
            {"name": "Game A", "exe": "GameA.EXE", "color": "red", "brightness": 50},
        ]
        processes = {"gamea.exe"}
        result = game_sync.pick_profile(processes, games)
        self.assertEqual(result["name"], "Game A")

    def test_first_wins(self):
        """When multiple games match, first in config order wins."""
        games = [
            {"name": "Game A", "exe": "shared.exe", "color": "red", "brightness": 50},
            {"name": "Game B", "exe": "shared.exe", "color": "blue", "brightness": 50},
        ]
        processes = {"shared.exe"}
        result = game_sync.pick_profile(processes, games)
        self.assertEqual(result["name"], "Game A")

    def test_no_match(self):
        """No matching exe returns None."""
        games = [
            {"name": "Game A", "exe": "gamea.exe", "color": "red", "brightness": 50},
        ]
        processes = {"chrome.exe", "notepad.exe"}
        result = game_sync.pick_profile(processes, games)
        self.assertIsNone(result)

    def test_empty_games(self):
        """Empty games list returns None."""
        result = game_sync.pick_profile({"game.exe"}, [])
        self.assertIsNone(result)

    def test_cyberpunk_profile_from_config(self):
        """Loading config.example.json and matching Cyberpunk 2077."""
        config_path = Path(__file__).parent.parent / "config.example.json"
        with open(config_path) as f:
            config = json.load(f)
        games = config["games"]
        result = game_sync.pick_profile({"cyberpunk2077.exe"}, games)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Cyberpunk 2077")
        self.assertEqual(result["color"], "#ff00aa")
        self.assertEqual(result["brightness"], 80)

    def test_ghost_profile_from_config(self):
        """Loading config.example.json and matching Ghost of Tsushima."""
        config_path = Path(__file__).parent.parent / "config.example.json"
        with open(config_path) as f:
            config = json.load(f)
        games = config["games"]
        result = game_sync.pick_profile({"ghostoftsushima.exe"}, games)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Ghost of Tsushima")
        self.assertEqual(result["color"], "#ff4500")
        self.assertEqual(result["brightness"], 70)

    def test_no_match_notepad(self):
        """notepad.exe does not match any game profile."""
        config_path = Path(__file__).parent.parent / "config.example.json"
        with open(config_path) as f:
            config = json.load(f)
        games = config["games"]
        result = game_sync.pick_profile({"notepad.exe"}, games)
        self.assertIsNone(result)

    def test_case_insensitive_config_games(self):
        """Game exe matching from config is case-insensitive."""
        config_path = Path(__file__).parent.parent / "config.example.json"
        with open(config_path) as f:
            config = json.load(f)
        games = config["games"]
        # running_processes() returns lowercase names; pick_profile lowercases config exe
        result = game_sync.pick_profile({"cyberpunk2077.exe"}, games)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Cyberpunk 2077")
        result2 = game_sync.pick_profile({"ghostoftsushima.exe"}, games)
        self.assertIsNotNone(result2)
        self.assertEqual(result2["name"], "Ghost of Tsushima")


class TestRunOnce(unittest.TestCase):
    """Test run() with once=True and mocked dependencies."""

    def _make_config(self, games=None, default=None):
        if games is None:
            games = [
                {"name": "Test Game", "exe": "testgame.exe", "color": "red", "brightness": 80},
            ]
        if default is None:
            default = {"color": "white", "brightness": 40}
        return {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "games": games,
            "default": default,
        }

    @mock.patch("game_sync.running_processes")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_game_detected(self, mock_brightness, mock_color, mock_processes):
        """When a game is running, its profile is applied."""
        mock_processes.return_value = {"testgame.exe", "chrome.exe"}
        config = self._make_config()

        game_sync.run(config, once=True)

        # Should have called color and brightness for the game profile
        self.assertEqual(mock_color.call_count, 1)
        self.assertEqual(mock_brightness.call_count, 1)
        # Red = (255, 0, 0)
        mock_color.assert_called_with("192.168.1.50", 255, 0, 0)
        mock_brightness.assert_called_with("192.168.1.50", 80)

    @mock.patch("game_sync.running_processes")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_no_game_default(self, mock_brightness, mock_color, mock_processes):
        """When no game is running, default profile is applied."""
        mock_processes.return_value = {"chrome.exe"}
        config = self._make_config()

        game_sync.run(config, once=True)

        # Should have called color and brightness for the default profile
        self.assertEqual(mock_color.call_count, 1)
        self.assertEqual(mock_brightness.call_count, 1)
        # White = (255, 255, 255)
        mock_color.assert_called_with("192.168.1.50", 255, 255, 255)
        mock_brightness.assert_called_with("192.168.1.50", 40)

    @mock.patch("game_sync.running_processes")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_same_game_no_spam(self, mock_sleep, mock_brightness, mock_color, mock_processes):
        """Two iterations with the same game send commands only once."""
        mock_processes.return_value = {"testgame.exe"}
        config = self._make_config()

        # Run two iterations (once=False, but we mock sleep to exit after 2 calls)
        call_count = [0]
        def sleep_side_effect(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise KeyboardInterrupt()
        mock_sleep.side_effect = sleep_side_effect

        try:
            game_sync.run(config, interval=1)
        except KeyboardInterrupt:
            pass

        # Should have sent commands only once (first iteration)
        self.assertEqual(mock_color.call_count, 1)
        self.assertEqual(mock_brightness.call_count, 1)

    @mock.patch("game_sync.running_processes")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_profile_change_resends(self, mock_sleep, mock_brightness, mock_color, mock_processes):
        """When profile changes, commands are resent."""
        # First iteration: game running
        # Second iteration: no game (default)
        mock_processes.side_effect = [
            {"testgame.exe"},
            {"chrome.exe"},
        ]
        config = self._make_config()

        call_count = [0]
        def sleep_side_effect(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise KeyboardInterrupt()
        mock_sleep.side_effect = sleep_side_effect

        try:
            game_sync.run(config, interval=1)
        except KeyboardInterrupt:
            pass

        # Should have sent commands twice (once for game, once for default)
        self.assertEqual(mock_color.call_count, 2)
        self.assertEqual(mock_brightness.call_count, 2)


class TestConfigValidation(unittest.TestCase):
    """Test config validation."""

    def test_missing_games_key(self):
        """Config missing 'games' key produces clear error."""
        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "default": {"color": "white", "brightness": 40},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", ["game_sync.py", "--once", "--config", config_path]):
                with self.assertRaises(SystemExit) as ctx:
                    game_sync.main()
                self.assertEqual(ctx.exception.code, 1)
        finally:
            Path(config_path).unlink()


class TestDryRun(unittest.TestCase):
    """Test dry-run mode."""

    @mock.patch("game_sync.running_processes")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_dry_run_no_send(self, mock_brightness, mock_color, mock_processes):
        """Dry-run mode prints instead of sending."""
        mock_processes.return_value = {"testgame.exe"}
        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "games": [
                {"name": "Test Game", "exe": "testgame.exe", "color": "red", "brightness": 80},
            ],
            "default": {"color": "white", "brightness": 40},
        }

        game_sync.run(config, once=True, dry_run=True)

        # Should NOT have called govee functions
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
