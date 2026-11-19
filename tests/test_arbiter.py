"""Tests for arbiter.py."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
import arbiter


class TestSignalActive(unittest.TestCase):
    """Test signal_active() function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        arbiter.STATE_DIR = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_false_when_no_file(self):
        """signal_active returns False when saved_state.json doesn't exist."""
        self.assertFalse(arbiter.signal_active())

    def test_true_when_file_exists(self):
        """signal_active returns True when saved_state.json exists."""
        (arbiter.STATE_DIR / "saved_state.json").write_text("[]")
        self.assertTrue(arbiter.signal_active())


class TestGameActive(unittest.TestCase):
    """Test game_active() function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        arbiter.STATE_DIR = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_false_when_no_file(self):
        """game_active returns False when game_active.json doesn't exist."""
        self.assertFalse(arbiter.game_active())

    def test_true_when_file_exists(self):
        """game_active returns True when game_active.json exists."""
        (arbiter.STATE_DIR / "game_active.json").write_text('{"profile": "test"}')
        self.assertTrue(arbiter.game_active())


class TestSetGameActive(unittest.TestCase):
    """Test set_game_active() function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        arbiter.STATE_DIR = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

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
        shutil.rmtree(self.tmpdir)
        arbiter.set_game_active("Test Game")
        self.assertTrue(arbiter.game_active())


class TestClearGameActive(unittest.TestCase):
    """Test clear_game_active() function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        arbiter.STATE_DIR = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_removes_file(self):
        """clear_game_active removes game_active.json."""
        arbiter.set_game_active("Test Game")
        self.assertTrue(arbiter.game_active())
        arbiter.clear_game_active()
        self.assertFalse(arbiter.game_active())

    def test_no_error_when_missing(self):
        """clear_game_active raises nothing when file is missing."""
        arbiter.clear_game_active()  # Should not raise


class TestRoundTrip(unittest.TestCase):
    """Test set/clear round trip."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        arbiter.STATE_DIR = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def test_set_then_clear(self):
        """set_game_active then clear_game_active returns to inactive."""
        self.assertFalse(arbiter.game_active())
        arbiter.set_game_active("Test")
        self.assertTrue(arbiter.game_active())
        arbiter.clear_game_active()
        self.assertFalse(arbiter.game_active())


if __name__ == "__main__":
    unittest.main()
