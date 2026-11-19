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


if __name__ == "__main__":
    unittest.main()
