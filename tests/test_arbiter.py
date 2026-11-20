"""Tests for arbiter.py."""

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import arbiter
from helpers import StateDirMixin


class TestSignalActive(StateDirMixin, unittest.TestCase):
    """Test signal_active() function."""

    def test_false_when_no_file(self):
        """signal_active returns False when saved_state.json doesn't exist."""
        self.assertFalse(arbiter.signal_active())

    def test_true_when_file_exists(self):
        """signal_active returns True when saved_state.json exists."""
        (arbiter.STATE_DIR / "saved_state.json").write_text("[]")
        self.assertTrue(arbiter.signal_active())


class TestGameActive(StateDirMixin, unittest.TestCase):
    """Test game_active() function."""

    def test_false_when_no_file(self):
        """game_active returns False when game_active.json doesn't exist."""
        self.assertFalse(arbiter.game_active())

    def test_true_when_file_exists(self):
        """game_active returns True when game_active.json exists."""
        (arbiter.STATE_DIR / "game_active.json").write_text('{"profile": "test"}')
        self.assertTrue(arbiter.game_active())


class TestSetGameActive(StateDirMixin, unittest.TestCase):
    """Test set_game_active() function."""

    def test_creates_file(self):
        """set_game_active creates game_active.json with profile name."""
        arbiter.set_game_active("Cyberpunk 2077")
        self.assertTrue(arbiter.game_active())
        with open(arbiter.STATE_DIR / "game_active.json") as f:
            data = json.load(f)
        self.assertEqual(data["profile"], "Cyberpunk 2077")

    def test_creates_state_dir(self):
        """set_game_active creates state directory if needed."""
        # Remove the state dir
        import shutil
        shutil.rmtree(self.state_dir)
        arbiter.set_game_active("Test Game")
        self.assertTrue(arbiter.game_active())


class TestClearGameActive(StateDirMixin, unittest.TestCase):
    """Test clear_game_active() function."""

    def test_removes_file(self):
        """clear_game_active removes game_active.json."""
        arbiter.set_game_active("Test Game")
        self.assertTrue(arbiter.game_active())
        arbiter.clear_game_active()
        self.assertFalse(arbiter.game_active())

    def test_no_error_when_missing(self):
        """clear_game_active raises nothing when file is missing."""
        arbiter.clear_game_active()  # Should not raise


class TestRoundTrip(StateDirMixin, unittest.TestCase):
    """Test set/clear round trip."""

    def test_set_then_clear(self):
        """set_game_active then clear_game_active returns to inactive."""
        self.assertFalse(arbiter.game_active())
        arbiter.set_game_active("Test")
        self.assertTrue(arbiter.game_active())
        arbiter.clear_game_active()
        self.assertFalse(arbiter.game_active())


class TestGameActiveStaleness(StateDirMixin, unittest.TestCase):
    """Test that stale game_active.json is ignored (mtime heartbeat)."""

    def test_fresh_file_is_active(self):
        """A game_active.json with recent mtime is considered active."""
        arbiter.set_game_active("Test Game")
        self.assertTrue(arbiter.game_active())

    def test_stale_file_is_inactive(self):
        """A game_active.json with mtime > 60s old is considered inactive."""
        arbiter.set_game_active("Test Game")
        path = arbiter.STATE_DIR / "game_active.json"
        # Set mtime to 120 seconds ago
        old_time = time.time() - 120
        os.utime(path, (old_time, old_time))
        self.assertFalse(arbiter.game_active())

    def test_boundary_just_within_stale(self):
        """A game_active.json with mtime 10s old is active."""
        arbiter.set_game_active("Test Game")
        path = arbiter.STATE_DIR / "game_active.json"
        recent_time = time.time() - 10
        os.utime(path, (recent_time, recent_time))
        self.assertTrue(arbiter.game_active())


class TestMusicActive(StateDirMixin, unittest.TestCase):
    """Test music_active() function."""

    def test_false_when_no_file(self):
        """music_active returns False when music_active.json doesn't exist."""
        self.assertFalse(arbiter.music_active())

    def test_true_when_file_exists(self):
        """music_active returns True when music_active.json exists."""
        arbiter.set_music_active()
        self.assertTrue(arbiter.music_active())


class TestSetMusicActive(StateDirMixin, unittest.TestCase):
    """Test set_music_active() function."""

    def test_creates_file(self):
        """set_music_active creates music_active.json with pid and since."""
        arbiter.set_music_active()
        self.assertTrue(arbiter.music_active())
        with open(arbiter.STATE_DIR / "music_active.json") as f:
            data = json.load(f)
        self.assertIn("pid", data)
        self.assertIn("since", data)

    def test_creates_state_dir(self):
        """set_music_active creates state directory if needed."""
        import shutil
        shutil.rmtree(self.state_dir)
        arbiter.set_music_active()
        self.assertTrue(arbiter.music_active())


class TestClearMusicActive(StateDirMixin, unittest.TestCase):
    """Test clear_music_active() function."""

    def test_removes_file(self):
        """clear_music_active removes music_active.json."""
        arbiter.set_music_active()
        self.assertTrue(arbiter.music_active())
        arbiter.clear_music_active()
        self.assertFalse(arbiter.music_active())

    def test_no_error_when_missing(self):
        """clear_music_active raises nothing when file is missing."""
        arbiter.clear_music_active()  # Should not raise


class TestMusicActiveStaleness(StateDirMixin, unittest.TestCase):
    """Test that stale music_active.json is ignored (mtime heartbeat)."""

    def test_fresh_file_is_active(self):
        """A music_active.json with recent mtime is considered active."""
        arbiter.set_music_active()
        self.assertTrue(arbiter.music_active())

    def test_stale_file_is_inactive(self):
        """A music_active.json with mtime > 15s old is considered inactive."""
        arbiter.set_music_active()
        path = arbiter.STATE_DIR / "music_active.json"
        # Set mtime to 30 seconds ago
        old_time = time.time() - 30
        os.utime(path, (old_time, old_time))
        self.assertFalse(arbiter.music_active())

    def test_boundary_just_within_stale(self):
        """A music_active.json with mtime 5s old is active."""
        arbiter.set_music_active()
        path = arbiter.STATE_DIR / "music_active.json"
        recent_time = time.time() - 5
        os.utime(path, (recent_time, recent_time))
        self.assertTrue(arbiter.music_active())


class TestWeatherBlocked(StateDirMixin, unittest.TestCase):
    """Test weather_blocked() function with music priority."""

    def test_blocked_by_signal(self):
        """weather_blocked returns True when signal is active."""
        (arbiter.STATE_DIR / "saved_state.json").write_text("[]")
        self.assertTrue(arbiter.weather_blocked())

    def test_blocked_by_music(self):
        """weather_blocked returns True when music is active."""
        arbiter.set_music_active()
        self.assertTrue(arbiter.weather_blocked())

    def test_blocked_by_game(self):
        """weather_blocked returns True when game is active."""
        arbiter.set_game_active("Test Game")
        self.assertTrue(arbiter.weather_blocked())

    def test_not_blocked_when_none_active(self):
        """weather_blocked returns False when no higher priority is active."""
        self.assertFalse(arbiter.weather_blocked())


class TestGetMode(StateDirMixin, unittest.TestCase):
    """Test get_mode() function."""

    def test_missing_file_returns_off(self):
        """get_mode returns 'off' when mode.json doesn't exist."""
        self.assertEqual(arbiter.get_mode(), "off")

    def test_empty_file_returns_off(self):
        """get_mode returns 'off' when mode.json is empty."""
        (arbiter.STATE_DIR / "mode.json").write_text("")
        self.assertEqual(arbiter.get_mode(), "off")

    def test_bad_json_returns_off(self):
        """get_mode returns 'off' when mode.json has bad JSON."""
        (arbiter.STATE_DIR / "mode.json").write_text("not json")
        self.assertEqual(arbiter.get_mode(), "off")

    def test_wrong_shape_returns_off(self):
        """get_mode returns 'off' when mode.json is not an object."""
        (arbiter.STATE_DIR / "mode.json").write_text("[]")
        self.assertEqual(arbiter.get_mode(), "off")

    def test_unknown_mode_returns_off(self):
        """get_mode returns 'off' for unknown mode."""
        (arbiter.STATE_DIR / "mode.json").write_text('{"mode": "disco"}')
        self.assertEqual(arbiter.get_mode(), "off")

    def test_valid_mode_returns_mode(self):
        """get_mode returns the mode for valid mode.json."""
        (arbiter.STATE_DIR / "mode.json").write_text('{"mode": "weather"}')
        self.assertEqual(arbiter.get_mode(), "weather")

    def test_all_modes_valid(self):
        """get_mode returns each valid mode."""
        for mode in arbiter.MODES:
            (arbiter.STATE_DIR / "mode.json").write_text(json.dumps({"mode": mode}))
            self.assertEqual(arbiter.get_mode(), mode)


class TestSetMode(StateDirMixin, unittest.TestCase):
    """Test set_mode() function."""

    def test_round_trip_all_modes(self):
        """set_mode then get_mode returns the same mode for all modes."""
        for mode in arbiter.MODES:
            arbiter.set_mode(mode)
            self.assertEqual(arbiter.get_mode(), mode)

    def test_unknown_mode_raises(self):
        """set_mode raises ValueError for unknown mode."""
        with self.assertRaises(ValueError):
            arbiter.set_mode("disco")

    def test_unknown_mode_leaves_file_unchanged(self):
        """set_mode with unknown mode doesn't change mode.json."""
        arbiter.set_mode("weather")
        try:
            arbiter.set_mode("disco")
        except ValueError:
            pass
        self.assertEqual(arbiter.get_mode(), "weather")

    def test_creates_state_dir(self):
        """set_mode creates state directory if needed."""
        import shutil
        shutil.rmtree(self.state_dir)
        arbiter.set_mode("game")
        self.assertEqual(arbiter.get_mode(), "game")

    def test_no_temp_file_left(self):
        """set_mode doesn't leave temp files behind."""
        arbiter.set_mode("music")
        tmp_files = list(self.state_dir.glob("mode.json.tmp.*"))
        self.assertEqual(len(tmp_files), 0)


class TestCapBrightness(unittest.TestCase):
    """Test cap_brightness() function."""

    def test_below_cap(self):
        """Brightness below cap is unchanged."""
        cfg = {"max_brightness": 80}
        self.assertEqual(arbiter.cap_brightness(50, cfg), 50)

    def test_at_cap(self):
        """Brightness at cap is unchanged."""
        cfg = {"max_brightness": 80}
        self.assertEqual(arbiter.cap_brightness(80, cfg), 80)

    def test_above_cap(self):
        """Brightness above cap is reduced to cap."""
        cfg = {"max_brightness": 80}
        self.assertEqual(arbiter.cap_brightness(100, cfg), 80)

    def test_custom_max_brightness(self):
        """Custom max_brightness of 60 caps at 60."""
        cfg = {"max_brightness": 60}
        self.assertEqual(arbiter.cap_brightness(100, cfg), 60)
        self.assertEqual(arbiter.cap_brightness(50, cfg), 50)

    def test_bad_max_brightness_value(self):
        """Non-int max_brightness falls back to default 80."""
        cfg = {"max_brightness": "high"}
        self.assertEqual(arbiter.cap_brightness(100, cfg), 80)

    def test_allow_flash_passes_through(self):
        """allow_flash=True passes 100 through even with cap."""
        cfg = {"max_brightness": 80}
        self.assertEqual(arbiter.cap_brightness(100, cfg, allow_flash=True), 100)

    def test_clamp_zero_to_one(self):
        """Brightness 0 is clamped to 1."""
        cfg = {"max_brightness": 80}
        self.assertEqual(arbiter.cap_brightness(0, cfg), 1)

    def test_clamp_above_100(self):
        """Brightness 150 is clamped to 100."""
        cfg = {"max_brightness": 80}
        self.assertEqual(arbiter.cap_brightness(150, cfg), 80)

    def test_no_max_brightness_in_config(self):
        """Missing max_brightness uses default 80."""
        cfg = {}
        self.assertEqual(arbiter.cap_brightness(100, cfg), 80)


if __name__ == "__main__":
    unittest.main()
