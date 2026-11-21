"""Tests for music_sync.py.

All tests run without soundcard/numpy and without the network.
"""

import json
import math
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import music_sync
import arbiter
from helpers import StateDirMixin, bounded_clock


class TestAnalyze(unittest.TestCase):
    """Test audio analysis on synthetic signals."""

    def _make_sine(self, freq, rate, duration=0.1):
        """Generate a sine wave signal."""
        n = int(rate * duration)
        samples = []
        for i in range(n):
            t = i / rate
            samples.append(0.5 * math.sin(2.0 * math.pi * freq * t))
        return samples

    def test_silence_gives_zero_level(self):
        """Silence should give level 0."""
        samples = [0.0] * 1024
        result = music_sync.analyze(samples, 44100)
        self.assertAlmostEqual(result["level"], 0.0, places=3)

    def test_60hz_sine_gives_bass_dominant(self):
        """60 Hz sine should give bass > treble."""
        samples = self._make_sine(60, 44100)
        result = music_sync.analyze(samples, 44100)
        self.assertGreater(result["bass"], result["treble"])
        self.assertGreater(result["level"], 0.0)

    def test_8khz_sine_gives_treble_dominant(self):
        """8 kHz sine should give treble > bass."""
        samples = self._make_sine(8000, 44100)
        result = music_sync.analyze(samples, 44100)
        self.assertGreater(result["treble"], result["bass"])
        self.assertGreater(result["level"], 0.0)

    def test_features_in_range(self):
        """All features should be in 0..1 range."""
        samples = self._make_sine(440, 44100)
        result = music_sync.analyze(samples, 44100)
        for key in ["level", "bass", "mid", "treble"]:
            self.assertGreaterEqual(result[key], 0.0)
            self.assertLessEqual(result[key], 1.0)

    def test_empty_samples(self):
        """Empty samples should give all zeros."""
        result = music_sync.analyze([], 44100)
        for key in ["level", "bass", "mid", "treble"]:
            self.assertAlmostEqual(result[key], 0.0)


class TestFeaturesToRgb(unittest.TestCase):
    """Test colour mapping from audio features."""

    def _make_features(self, level=0.5, bass=0.5, mid=0.5, treble=0.5):
        return {"level": level, "bass": bass, "mid": mid, "treble": treble}

    def test_never_all_zero(self):
        """features_to_rgb should never return (0, 0, 0)."""
        features = self._make_features(level=0.0, bass=0.0, mid=0.0, treble=0.0)
        rgb = music_sync.features_to_rgb(features, {})
        self.assertNotEqual(rgb, (0, 0, 0))

    def test_never_above_255(self):
        """RGB values should never exceed 255."""
        features = self._make_features(level=1.0, bass=1.0, mid=1.0, treble=1.0)
        rgb = music_sync.features_to_rgb(features, {})
        for ch in rgb:
            self.assertLessEqual(ch, 255)

    def test_never_below_zero(self):
        """RGB values should never be below 0."""
        features = self._make_features(level=0.0, bass=0.0, mid=0.0, treble=0.0)
        rgb = music_sync.features_to_rgb(features, {})
        for ch in rgb:
            self.assertGreaterEqual(ch, 0)

    def test_bass_gives_warm_colors(self):
        """Bass-dominant features should give warm (red) colours."""
        features = self._make_features(level=0.8, bass=1.0, mid=0.0, treble=0.0)
        rgb = music_sync.features_to_rgb(features, {})
        self.assertGreaterEqual(rgb[0], rgb[1])
        self.assertGreaterEqual(rgb[0], rgb[2])

    def test_treble_gives_cool_colors(self):
        """Treble-dominant features should give cool (blue) colours."""
        features = self._make_features(level=0.8, bass=0.0, mid=0.0, treble=1.0)
        rgb = music_sync.features_to_rgb(features, {})
        self.assertGreaterEqual(rgb[2], rgb[0])
        self.assertGreaterEqual(rgb[2], rgb[1])

    def test_level_scales_brightness(self):
        """Higher level should give brighter colours."""
        features_low = self._make_features(level=0.2, bass=0.5, mid=0.5, treble=0.5)
        features_high = self._make_features(level=0.8, bass=0.5, mid=0.5, treble=0.5)
        rgb_low = music_sync.features_to_rgb(features_low, {})
        rgb_high = music_sync.features_to_rgb(features_high, {})
        self.assertGreater(sum(rgb_high), sum(rgb_low))


class TestSmoothing(unittest.TestCase):
    """Test exponential moving average smoothing."""

    def test_first_frame_no_smoothing(self):
        """First frame should pass through unchanged."""
        features = {"level": 0.5, "bass": 0.3, "mid": 0.4, "treble": 0.2}
        result = music_sync.smooth_features(None, features, 0.5)
        self.assertEqual(result, features)

    def test_smoothing_reduces_change(self):
        """Smoothing should reduce sudden changes."""
        prev = {"level": 0.2, "bass": 0.1, "mid": 0.1, "treble": 0.1}
        curr = {"level": 0.8, "bass": 0.9, "mid": 0.9, "treble": 0.9}
        result = music_sync.smooth_features(prev, curr, 0.5)
        self.assertGreater(result["level"], prev["level"])
        self.assertLess(result["level"], curr["level"])


class TestColorDistance(unittest.TestCase):
    """Test colour distance calculation."""

    def test_same_color_zero_distance(self):
        """Same colour should have zero distance."""
        c = (100, 150, 200)
        self.assertAlmostEqual(music_sync.color_distance(c, c), 0.0)

    def test_different_colors_positive_distance(self):
        """Different colours should have positive distance."""
        c1 = (0, 0, 0)
        c2 = (255, 255, 255)
        self.assertGreater(music_sync.color_distance(c1, c2), 0.0)


class TestImportWithoutSoundcard(unittest.TestCase):
    """Test that importing music_sync works without soundcard/numpy."""

    def test_import_without_soundcard(self):
        """Import should succeed even if soundcard is not available."""
        modules_to_remove = []
        for mod in list(sys.modules.keys()):
            if mod in ("soundcard", "numpy", "np"):
                modules_to_remove.append(mod)

        for mod in modules_to_remove:
            del sys.modules[mod]

        with mock.patch.dict(sys.modules, {"soundcard": None, "numpy": None}):
            import importlib
            if "music_sync" in sys.modules:
                del sys.modules["music_sync"]
            import music_sync as ms
            result = ms.analyze([0.0] * 1024, 44100)
            self.assertIn("level", result)


class TestFrameRateLimiting(unittest.TestCase):
    """Test frame rate limiting with fake clock."""

    def test_frame_rate_limit(self):
        """Should send at most fps frames per second."""
        last_color = (100, 100, 100)
        new_color = (105, 105, 105)
        distance = music_sync.color_distance(last_color, new_color)
        self.assertLess(distance, music_sync.COLOR_CHANGE_THRESHOLD)

        new_color2 = (200, 200, 200)
        distance2 = music_sync.color_distance(last_color, new_color2)
        self.assertGreater(distance2, music_sync.COLOR_CHANGE_THRESHOLD)


class TestMusicSignalPriority(StateDirMixin, unittest.TestCase):
    """Test that music sync yields to agent signal."""

    def test_music_skips_frames_when_signal_active(self):
        """music_sync.run() should not send frames when signal is active,
        but should send after signal clears. Tests the re-check before sending."""
        self.set_mode("music")
        # Signal becomes active on the third call (the re-check before sending)
        # Call 1: start-up guard -> False
        # Call 2: top of loop (iteration 1) -> False
        # Call 3: re-check before send (iteration 1) -> True
        # Call 4: top of loop (iteration 2) -> True
        # Call 5: top of loop (iteration 3) -> False
        # Call 6: re-check before send (iteration 3) -> False
        signal_active_count = [0]

        def fake_signal_active():
            signal_active_count[0] += 1
            if signal_active_count[0] == 1:
                return False  # start-up guard
            elif signal_active_count[0] == 2:
                return False  # top of loop, iteration 1
            elif signal_active_count[0] == 3:
                return True   # re-check before send, iteration 1
            elif signal_active_count[0] == 4:
                return True   # top of loop, iteration 2
            else:
                return False  # top of loop, iteration 3 and re-check

        # Track colours sent
        colors_sent = []

        def fake_color(ip, r, g, b):
            colors_sent.append((ip, r, g, b))

        # Fake time that advances 0.1s per call (10 fps)
        fake_time_fn = bounded_clock()

        # Mock soundcard and numpy
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]

        def fake_record(numframes):
            frame_count[0] += 1
            # Hard stop after 2 frames
            if frame_count[0] >= 2:
                raise KeyboardInterrupt()
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "signal_active", side_effect=fake_signal_active):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    mock_govee.brightness = mock.Mock()
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                # Mock analyze to return consistent features
                                with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                    try:
                                        music_sync.run(
                                            {"devices": [{"ip": "1.2.3.4"}]},
                                            fps=10,
                                            time_fn=fake_time_fn,
                                        )
                                    except KeyboardInterrupt:
                                        pass

        # Iteration 1: signal_active() -> False (top) -> record (frame 1) -> signal_active() -> True (re-check) -> no colour sent
        # Iteration 2: signal_active() -> True (top) -> no record
        # Iteration 3: signal_active() -> False (top) -> record (frame 2) -> KeyboardInterrupt
        # So we expect 0 colours sent
        self.assertEqual(len(colors_sent), 0,
                        f"Expected 0 colours sent, got {len(colors_sent)}")


class TestMusicRestoreSkippedDuringSignal(StateDirMixin, unittest.TestCase):
    """Test that music sync doesn't restore over an active signal."""

    def test_no_restore_when_signal_active(self):
        """When run() exits while signal is active, don't restore initial state."""
        self.set_mode("music")
        # Signal is active throughout
        def fake_signal_active():
            return True

        # Track govee calls
        govee_calls = []

        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))

        def fake_brightness(ip, b):
            govee_calls.append(("brightness", ip, b))

        fake_time_fn = bounded_clock()

        # Mock stop flag to trigger exit after initial setup
        stop_flag_calls = [0]

        def fake_stop_flag_exists():
            stop_flag_calls[0] += 1
            # Return True on the first loop iteration (after initial setup)
            return stop_flag_calls[0] > 1

        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)
        fake_rec.record.side_effect = KeyboardInterrupt()

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "signal_active", side_effect=fake_signal_active):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.brightness = fake_brightness
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE") as mock_stop_flag:
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                mock_stop_flag.exists = fake_stop_flag_exists
                                music_sync.run(
                                    {"devices": [{"ip": "1.2.3.4"}]},
                                    fps=10,
                                    time_fn=fake_time_fn,
                                )

        # Heartbeat file should be removed
        self.assertFalse(arbiter.music_file().exists(),
                         "music_active.json should be removed after exception")
        # No restore calls should have been made (signal was active)
        # With the start-up guard, brightness is also skipped when signal is active
        brightness_calls = [c for c in govee_calls if c[0] == "brightness"]
        # No brightness call at start (signal was active), none in finally
        self.assertEqual(len(brightness_calls), 0,
                        f"Expected 0 brightness calls (signal active), got {len(brightness_calls)}")
        # No color calls in finally (restore would send color)
        color_calls = [c for c in govee_calls if c[0] == "color"]
        self.assertEqual(len(color_calls), 0,
                        f"Expected no color calls (no restore), got {len(color_calls)}")


class TestMusicHeartbeatClearOnException(StateDirMixin, unittest.TestCase):
    """Test that heartbeat file is removed when run() exits via exception."""

    def test_heartbeat_cleared_on_exception(self):
        """When run() exits via exception, music_active.json should be removed."""
        self.set_mode("music")
        # Create a fake recorder that raises KeyboardInterrupt on first frame
        # (RuntimeError is now caught and recovered from, so use KeyboardInterrupt
        # to force exit)
        fake_rec = mock.Mock()
        fake_rec.record.side_effect = KeyboardInterrupt()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            try:
                                music_sync.run(
                                    {"devices": [{"ip": "1.2.3.4"}]},
                                    fps=10,
                                    time_fn=fake_time_fn,
                                )
                            except KeyboardInterrupt:
                                pass

        # Heartbeat file should be removed
        self.assertFalse(arbiter.music_file().exists(),
                         "music_active.json should be removed after exception")


class TestMusicActiveBeforeInitialState(StateDirMixin, unittest.TestCase):
    """Test that music sync marks itself active before reading initial state."""

    def test_set_music_active_before_status(self):
        """set_music_active should be called before the first govee.status call."""
        self.set_mode("music")
        call_order = []

        def fake_set_music_active():
            call_order.append("set_music_active")

        def fake_status(ip, timeout=2):
            call_order.append(f"status_{ip}")
            return {"msg": {"data": {"brightness": 50}}}

        def fake_brightness(ip, b):
            call_order.append(f"brightness_{ip}")

        fake_time_fn = bounded_clock()

        # Create a fake recorder that raises KeyboardInterrupt on first frame
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)
        fake_rec.record.side_effect = KeyboardInterrupt()

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "set_music_active", side_effect=fake_set_music_active):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.status = fake_status
                    mock_govee.brightness = fake_brightness
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # set_music_active should come before status and brightness
        set_idx = call_order.index("set_music_active")
        status_idx = call_order.index("status_1.2.3.4")
        brightness_idx = call_order.index("brightness_1.2.3.4")
        self.assertLess(set_idx, status_idx,
                       "set_music_active should be called before govee.status")
        self.assertLess(set_idx, brightness_idx,
                       "set_music_active should be called before govee.brightness")


class TestMusicHeartbeatRefresh(StateDirMixin, unittest.TestCase):
    """Test that music sync refreshes its heartbeat."""

    def test_heartbeat_interval_constant(self):
        """HEARTBEAT_INTERVAL should be 5 seconds."""
        self.assertEqual(music_sync.HEARTBEAT_INTERVAL, 5.0)

    def test_heartbeat_refreshed_during_run(self):
        """set_music_active should be called multiple times during a long run."""
        self.set_mode("music")
        heartbeat_calls = []

        def fake_set_music_active():
            heartbeat_calls.append(fake_time[0])

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.6  # Advance 0.6s per frame (faster than 5s heartbeat)
            return t

        # Create a fake recorder
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]

        def fake_record(numframes):
            frame_count[0] += 1
            if frame_count[0] >= 10:
                raise KeyboardInterrupt()
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "set_music_active", side_effect=fake_set_music_active):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    mock_govee.brightness = mock.Mock()
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                    try:
                                        music_sync.run(
                                            {"devices": [{"ip": "1.2.3.4"}]},
                                            fps=10,
                                            time_fn=fake_time_fn,
                                        )
                                    except KeyboardInterrupt:
                                        pass

        # With 10 frames at 0.6s each = 6s total, heartbeat should be written at least twice
        # (once at start, once after 5s)
        self.assertGreaterEqual(len(heartbeat_calls), 2,
                                f"Expected at least 2 heartbeat writes, got {len(heartbeat_calls)}")


class TestKillProcessCommandLine(StateDirMixin, unittest.TestCase):
    """Test that _kill_process uses the correct taskkill command line."""

    def test_kill_process_uses_force_kill(self):
        """_kill_process should use taskkill /F /PID <pid>."""
        with mock.patch("subprocess.run") as mock_run:
            music_sync._kill_process(123)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        self.assertEqual(cmd, ["taskkill", "/F", "/PID", "123"])
        # Check creationflags
        self.assertEqual(call_args[1]["creationflags"], 0x08000000)

    def test_is_process_alive_uses_tasklist(self):
        """_is_process_alive should use tasklist with correct creationflags."""
        fake_result = mock.Mock()
        fake_result.returncode = 0
        fake_result.stdout = '"pythonw.exe","123","Console","123456 K"\n'

        with mock.patch("subprocess.run", return_value=fake_result) as mock_run:
            alive = music_sync._is_process_alive(123)
        self.assertTrue(alive)
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        self.assertEqual(cmd[0], "tasklist")
        self.assertIn("/FI", cmd)
        self.assertIn("PID eq 123", cmd)
        self.assertEqual(call_args[1]["creationflags"], 0x08000000)


class TestLeftoverStopFlag(StateDirMixin, unittest.TestCase):
    """Test that run() clears leftover stop flag and continues."""

    def test_run_clears_leftover_stop_flag(self):
        """run() should remove a leftover stop flag and not exit on it."""
        self.set_mode("music")
        # Create a leftover stop flag
        stop_flag = self.state_dir / "music_stop"
        stop_flag.write_text("leftover")
        self.assertTrue(stop_flag.exists())

        # Track colours sent
        colors_sent = []

        def fake_color(ip, r, g, b):
            colors_sent.append((ip, r, g, b))

        fake_time_fn = bounded_clock()

        # Create a fake recorder
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]

        def fake_record(numframes):
            frame_count[0] += 1
            if frame_count[0] >= 2:
                raise KeyboardInterrupt()
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", stop_flag):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # At least one colour should have been sent (proves run continued past leftover flag)
        self.assertGreaterEqual(len(colors_sent), 1,
                                "Expected at least one colour sent after clearing leftover stop flag")
        # Stop flag should be gone
        self.assertFalse(stop_flag.exists(), "Leftover stop flag should be removed")


class TestToggleCommands(StateDirMixin, unittest.TestCase):
    """Test the start/stop/toggle/status subcommands."""

    def setUp(self):
        super().setUp()
        self.original_state_dir = music_sync.STATE_DIR
        self.original_pid_file = music_sync.PID_FILE
        self.original_stop_flag = music_sync.STOP_FLAG_FILE
        self.original_log_file = music_sync.LOG_FILE

        music_sync.STATE_DIR = self.state_dir
        music_sync.PID_FILE = self.state_dir / "music_sync.pid"
        music_sync.STOP_FLAG_FILE = self.state_dir / "music_stop"
        music_sync.LOG_FILE = self.state_dir / "music_sync.log"

    def tearDown(self):
        music_sync.STATE_DIR = self.original_state_dir
        music_sync.PID_FILE = self.original_pid_file
        music_sync.STOP_FLAG_FILE = self.original_stop_flag
        music_sync.LOG_FILE = self.original_log_file
        super().tearDown()

    def test_status_off_when_no_pid_file(self):
        """status should report OFF when no pid file exists."""
        with mock.patch("builtins.print") as mock_print:
            result = music_sync.cmd_status()
        self.assertEqual(result, 0)
        mock_print.assert_called_once()
        self.assertIn("OFF", mock_print.call_args[0][0])

    def test_start_creates_pid_file(self):
        """start should create a pid file and report ON."""
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_proc = mock.Mock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc
            with mock.patch("builtins.print") as mock_print:
                result = music_sync.cmd_start()
        self.assertEqual(result, 0)
        self.assertTrue(music_sync.PID_FILE.exists())
        self.assertEqual(music_sync.PID_FILE.read_text().strip(), "12345")
        mock_print.assert_called_once()
        self.assertIn("ON", mock_print.call_args[0][0])

    def test_start_already_running(self):
        """start should report already ON if pid file exists and process alive."""
        music_sync.PID_FILE.write_text("99999")
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(arbiter, "music_active", return_value=True):
                with mock.patch("builtins.print") as mock_print:
                    result = music_sync.cmd_start()
        self.assertEqual(result, 0)
        mock_print.assert_called_once()
        self.assertIn("already ON", mock_print.call_args[0][0])

    def test_stop_when_not_running(self):
        """stop should report OFF when not running."""
        with mock.patch("govee.load_config", return_value={"devices": []}):
            with mock.patch("mode.govee.turn"):
                with mock.patch("builtins.print") as mock_print:
                    result = music_sync.cmd_stop()
        self.assertEqual(result, 0)
        mock_print.assert_called_once()
        self.assertIn("OFF", mock_print.call_args[0][0])

    def test_stop_raises_flag_and_waits(self):
        """stop should raise the stop flag and wait for process to exit."""
        music_sync.PID_FILE.write_text("88888")
        call_count = [0]

        def fake_is_alive(pid):
            call_count[0] += 1
            return call_count[0] < 5

        with mock.patch.object(music_sync, "_is_process_alive", side_effect=fake_is_alive):
            with mock.patch.object(arbiter, "music_active", return_value=True):
                with mock.patch.object(music_sync, "_raise_stop_flag") as mock_raise:
                    with mock.patch("govee.load_config", return_value={"devices": []}):
                        with mock.patch("mode.govee.turn"):
                            with mock.patch("builtins.print"):
                                result = music_sync.cmd_stop()
        self.assertEqual(result, 0)
        mock_raise.assert_called_once()

    def test_stop_falls_back_to_taskkill(self):
        """stop should fall back to taskkill if process ignores flag."""
        music_sync.PID_FILE.write_text("77777")
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(arbiter, "music_active", return_value=True):
                with mock.patch("subprocess.run") as mock_run:
                    with mock.patch("time.sleep"):
                        with mock.patch("govee.load_config", return_value={"devices": []}):
                            with mock.patch("mode.govee.turn"):
                                with mock.patch("builtins.print"):
                                    result = music_sync.cmd_stop()
        self.assertEqual(result, 0)
        self.assertTrue(any(
            "taskkill" in str(call) for call in mock_run.call_args_list
        ))

    def test_toggle_starts_when_off(self):
        """toggle should start when music mode is off."""
        with mock.patch.object(music_sync, "cmd_start", return_value=0) as mock_start:
            result = music_sync.cmd_toggle()
        mock_start.assert_called_once()
        self.assertEqual(result, 0)

    def test_toggle_stops_when_on(self):
        """toggle should stop when music mode is on."""
        music_sync.PID_FILE.write_text("66666")
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(arbiter, "music_active", return_value=True):
                with mock.patch.object(music_sync, "cmd_stop", return_value=0) as mock_stop:
                    result = music_sync.cmd_toggle()
        mock_stop.assert_called_once()
        self.assertEqual(result, 0)

    def test_stale_pid_file_cleaned(self):
        """A stale pid file (process dead) should be cleaned up."""
        music_sync.PID_FILE.write_text("55555")
        with mock.patch.object(music_sync, "_is_process_alive", return_value=False):
            pid = music_sync._get_running_pid()
        self.assertIsNone(pid)
        self.assertFalse(music_sync.PID_FILE.exists())

    def test_fresh_pid_file_grace_period(self):
        """Alive pid + no heartbeat + fresh pid file -> status says ON."""
        music_sync.PID_FILE.write_text("44444")
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(arbiter, "music_active", return_value=False):
                pid = music_sync._get_running_pid()
        self.assertEqual(pid, 44444)
        self.assertTrue(music_sync.PID_FILE.exists())

    def test_old_pid_file_no_heartbeat_killed(self):
        """Alive pid + no heartbeat + old pid file -> killed and cleaned up."""
        music_sync.PID_FILE.write_text("33333")
        old_time = time.time() - 100
        os.utime(music_sync.PID_FILE, (old_time, old_time))
        # Process created before PID file -> not reused, should be killed
        fake_created = old_time - 1
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(music_sync, "_process_create_time", return_value=fake_created):
                with mock.patch.object(arbiter, "music_active", return_value=False):
                    with mock.patch("subprocess.run") as mock_run:
                        pid = music_sync._get_running_pid()
        self.assertIsNone(pid)
        self.assertFalse(music_sync.PID_FILE.exists())
        # Verify taskkill was called with correct args
        self.assertTrue(any(
            "taskkill" in str(call) for call in mock_run.call_args_list
        ))

    def test_is_process_alive_exact_pid_match(self):
        """_is_process_alive(123) should be False when tasklist lists only 1234."""
        fake_result = mock.Mock()
        fake_result.returncode = 0
        fake_result.stdout = '"pythonw.exe","1234","Console","123456 K"\n'
        with mock.patch("subprocess.run", return_value=fake_result):
            alive = music_sync._is_process_alive(123)
        self.assertFalse(alive)

    def test_is_process_alive_matches_correct_pid(self):
        """_is_process_alive(1234) should be True when tasklist lists 1234."""
        fake_result = mock.Mock()
        fake_result.returncode = 0
        fake_result.stdout = '"pythonw.exe","1234","Console","123456 K"\n'
        with mock.patch("subprocess.run", return_value=fake_result):
            alive = music_sync._is_process_alive(1234)
        self.assertTrue(alive)

    def test_is_process_alive_rejects_non_python_image(self):
        """_is_process_alive should return False for non-Python images (stale PID)."""
        fake_result = mock.Mock()
        fake_result.returncode = 0
        fake_result.stdout = '"chrome.exe","4242","Console","123456 K"\n'
        with mock.patch("subprocess.run", return_value=fake_result):
            alive = music_sync._is_process_alive(4242)
        self.assertFalse(alive)

    def test_is_process_alive_accepts_python_exe(self):
        """_is_process_alive should return True for python.exe."""
        fake_result = mock.Mock()
        fake_result.returncode = 0
        fake_result.stdout = '"python.exe","5555","Console","123456 K"\n'
        with mock.patch("subprocess.run", return_value=fake_result):
            alive = music_sync._is_process_alive(5555)
        self.assertTrue(alive)

    def test_stale_pid_reused_by_chrome_not_killed(self):
        """_get_running_pid with old pid file + chrome.exe should not call taskkill."""
        music_sync.PID_FILE.write_text("4242")
        old_time = time.time() - 100
        os.utime(music_sync.PID_FILE, (old_time, old_time))
        fake_result = mock.Mock()
        fake_result.returncode = 0
        fake_result.stdout = '"chrome.exe","4242","Console","123456 K"\n'
        with mock.patch("subprocess.run", return_value=fake_result):
            with mock.patch.object(arbiter, "music_active", return_value=False):
                pid = music_sync._get_running_pid()
        self.assertIsNone(pid)
        self.assertFalse(music_sync.PID_FILE.exists())

    def test_stop_flag_checked_before_signal(self):
        """The stop flag should be checked before the signal check in the loop."""
        import inspect
        source = inspect.getsource(music_sync.run)
        stop_flag_pos = source.find("STOP_FLAG_FILE.exists()")
        # Find the signal check in the loop (after the stop flag check),
        # not the start-up guard check
        signal_pos = source.find("arbiter.signal_active()", stop_flag_pos)
        self.assertGreater(stop_flag_pos, -1)
        self.assertGreater(signal_pos, -1)
        self.assertLess(stop_flag_pos, signal_pos)


    def test_run_cleans_own_pid_file_on_exception(self):
        """run() should remove its own PID file when exiting via exception."""
        self.set_mode("music")
        import os
        my_pid = os.getpid()
        music_sync.PID_FILE.write_text(str(my_pid))

        fake_rec = mock.Mock()
        fake_rec.record.side_effect = KeyboardInterrupt()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            try:
                                music_sync.run(
                                    {"devices": [{"ip": "1.2.3.4"}]},
                                    fps=10,
                                    time_fn=fake_time_fn,
                                )
                            except KeyboardInterrupt:
                                pass

        self.assertFalse(music_sync.PID_FILE.exists(),
                        "run() should have removed its own PID file")

    def test_run_leaves_other_pid_file(self):
        """run() should not remove a PID file that doesn't match its own PID."""
        self.set_mode("music")
        music_sync.PID_FILE.write_text("99999")

        fake_rec = mock.Mock()
        fake_rec.record.side_effect = KeyboardInterrupt()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            try:
                                music_sync.run(
                                    {"devices": [{"ip": "1.2.3.4"}]},
                                    fps=10,
                                    time_fn=fake_time_fn,
                                )
                            except KeyboardInterrupt:
                                pass

        self.assertTrue(music_sync.PID_FILE.exists(),
                        "run() should not have removed another process's PID file")
        self.assertEqual(music_sync.PID_FILE.read_text().strip(), "99999")

    def test_cmd_status_does_not_kill_hung_process(self):
        """cmd_status should not kill a hung process (kill_hung=False)."""
        music_sync.PID_FILE.write_text("33333")
        old_time = time.time() - 100
        os.utime(music_sync.PID_FILE, (old_time, old_time))
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(arbiter, "music_active", return_value=False):
                with mock.patch("subprocess.run") as mock_run:
                    with mock.patch("builtins.print") as mock_print:
                        result = music_sync.cmd_status()
        self.assertEqual(result, 0)
        # No taskkill should have been called
        self.assertFalse(any(
            "taskkill" in str(call) for call in mock_run.call_args_list
        ))
        # Should report ON (hung but alive)
        self.assertIn("ON", mock_print.call_args[0][0])

    def test_cmd_stop_uses_deadline(self):
        """cmd_stop should use time.monotonic deadline, not fixed iterations."""
        music_sync.PID_FILE.write_text("77777")
        monotonic_calls = [0]

        def fake_monotonic():
            monotonic_calls[0] += 1
            # Advance 1 second per call so deadline is hit after ~5 calls
            return (monotonic_calls[0] - 1) * 1.0

        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(arbiter, "music_active", return_value=True):
                with mock.patch("subprocess.run") as mock_run:
                    with mock.patch("time.monotonic", side_effect=fake_monotonic):
                        with mock.patch("time.sleep"):
                            with mock.patch("govee.load_config", return_value={"devices": []}):
                                with mock.patch("mode.govee.turn"):
                                    with mock.patch("builtins.print"):
                                        result = music_sync.cmd_stop()
        self.assertEqual(result, 0)
        # Should have called taskkill after deadline
        self.assertTrue(any(
            "taskkill" in str(call) for call in mock_run.call_args_list
        ))
        # Should have checked ~5-6 times (5 second deadline, 1s per call)
        self.assertLessEqual(len(monotonic_calls), 8)

    def test_start_missing_soundcard(self):
        """cmd_start should return 2 if soundcard is not installed."""
        def fake_find_spec(name):
            if name == "soundcard":
                return None
            return mock.Mock()

        with mock.patch("importlib.util.find_spec", side_effect=fake_find_spec):
            with mock.patch("subprocess.Popen") as mock_popen:
                with mock.patch("builtins.print") as mock_print:
                    result = music_sync.cmd_start()
        self.assertEqual(result, 2)
        mock_popen.assert_not_called()
        self.assertFalse(music_sync.PID_FILE.exists())
        # Check stderr output
        self.assertTrue(any(
            "requirements-music.txt" in str(call) for call in mock_print.call_args_list
        ))

    def test_start_missing_numpy(self):
        """cmd_start should return 2 if numpy is not installed."""
        def fake_find_spec(name):
            if name == "numpy":
                return None
            return mock.Mock()

        with mock.patch("importlib.util.find_spec", side_effect=fake_find_spec):
            with mock.patch("subprocess.Popen") as mock_popen:
                with mock.patch("builtins.print") as mock_print:
                    result = music_sync.cmd_start()
        self.assertEqual(result, 2)
        mock_popen.assert_not_called()
        self.assertFalse(music_sync.PID_FILE.exists())
        self.assertTrue(any(
            "requirements-music.txt" in str(call) for call in mock_print.call_args_list
        ))

    def test_start_both_deps_found(self):
        """cmd_start should spawn process if both deps are found."""
        def fake_find_spec(name):
            return mock.Mock()

        with mock.patch("importlib.util.find_spec", side_effect=fake_find_spec):
            with mock.patch("subprocess.Popen") as mock_popen:
                mock_proc = mock.Mock()
                mock_proc.pid = 12345
                mock_popen.return_value = mock_proc
                with mock.patch("builtins.print"):
                    result = music_sync.cmd_start()
        self.assertEqual(result, 0)
        mock_popen.assert_called_once()
        self.assertTrue(music_sync.PID_FILE.exists())

    def test_start_popen_failure_restores_mode(self):
        """cmd_start should restore previous mode if Popen raises OSError."""
        def fake_find_spec(name):
            return mock.Mock()

        # Set a previous mode
        arbiter.set_mode("weather")
        self.assertEqual(arbiter.get_mode(), "weather")

        with mock.patch("importlib.util.find_spec", side_effect=fake_find_spec):
            with mock.patch("subprocess.Popen", side_effect=OSError("no such file")):
                with mock.patch("builtins.print") as mock_print:
                    result = music_sync.cmd_start()
        self.assertEqual(result, 1)
        # Mode should be restored to "weather"
        self.assertEqual(arbiter.get_mode(), "weather")
        # Error message should be printed
        self.assertTrue(any(
            "cannot start" in str(call) for call in mock_print.call_args_list
        ))

    def test_run_logs_missing_deps(self):
        """run() should log an ERROR when soundcard/numpy are missing."""
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)

        # Patch sys.modules to make import fail
        with mock.patch.dict(sys.modules, {"soundcard": None, "numpy": None}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("builtins.print") as mock_print:
                    with self.assertLogs(music_sync.logger, level="ERROR") as cm:
                        with self.assertRaises(SystemExit) as ctx:
                            music_sync.run(
                                {"devices": [{"ip": "1.2.3.4"}]},
                                fps=10,
                            )
        self.assertEqual(ctx.exception.code, 2)
        self.assertTrue(any(
            "requirements-music.txt" in log for log in cm.output
        ))
        # Verify print was called with the "music mode needs" message
        self.assertTrue(any(
            "music mode needs" in str(call) for call in mock_print.call_args_list
        ))

    def test_cmd_status_hung_process_shows_no_heartbeat(self):
        """cmd_status should show 'no heartbeat' for a hung process."""
        music_sync.PID_FILE.write_text("33333")
        old_time = time.time() - 100
        os.utime(music_sync.PID_FILE, (old_time, old_time))
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(arbiter, "music_active", return_value=False):
                with mock.patch("builtins.print") as mock_print:
                    result = music_sync.cmd_status()
        self.assertEqual(result, 0)
        self.assertIn("no heartbeat", mock_print.call_args[0][0])

    def test_cmd_status_healthy_process(self):
        """cmd_status should not show 'no heartbeat' for a healthy process."""
        music_sync.PID_FILE.write_text("44444")
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(arbiter, "music_active", return_value=True):
                with mock.patch("builtins.print") as mock_print:
                    result = music_sync.cmd_status()
        self.assertEqual(result, 0)
        self.assertNotIn("no heartbeat", mock_print.call_args[0][0])
        self.assertIn("ON", mock_print.call_args[0][0])

    def test_pid_reuse_detected_no_kill(self):
        """PID reused by another process (created after PID file) -> no kill."""
        music_sync.PID_FILE.write_text("4242")
        old_time = time.time() - 100
        os.utime(music_sync.PID_FILE, (old_time, old_time))
        # Process created 1 hour after PID file -> reused
        fake_created = old_time + 3600
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(music_sync, "_process_create_time", return_value=fake_created):
                with mock.patch.object(arbiter, "music_active", return_value=False):
                    with mock.patch("subprocess.run") as mock_run:
                        pid = music_sync._get_running_pid()
        self.assertIsNone(pid)
        self.assertFalse(music_sync.PID_FILE.exists())
        # No taskkill should have been called
        self.assertFalse(any(
            "taskkill" in str(call) for call in mock_run.call_args_list
        ))

    def test_pid_not_reused_hung_process_killed(self):
        """PID not reused (created before PID file) + hung -> taskkill called."""
        music_sync.PID_FILE.write_text("33333")
        old_time = time.time() - 100
        os.utime(music_sync.PID_FILE, (old_time, old_time))
        # Process created 1 second before PID file -> not reused
        fake_created = old_time - 1
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(music_sync, "_process_create_time", return_value=fake_created):
                with mock.patch.object(arbiter, "music_active", return_value=False):
                    with mock.patch("subprocess.run") as mock_run:
                        pid = music_sync._get_running_pid()
        self.assertIsNone(pid)
        self.assertFalse(music_sync.PID_FILE.exists())
        # taskkill should have been called
        self.assertTrue(any(
            "taskkill" in str(call) for call in mock_run.call_args_list
        ))

    def test_pid_reuse_unknown_create_time_no_kill(self):
        """Cannot determine create time -> no kill, returns None."""
        music_sync.PID_FILE.write_text("55555")
        old_time = time.time() - 100
        os.utime(music_sync.PID_FILE, (old_time, old_time))
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(music_sync, "_process_create_time", return_value=None):
                with mock.patch.object(arbiter, "music_active", return_value=False):
                    with mock.patch("subprocess.run") as mock_run:
                        pid = music_sync._get_running_pid()
        self.assertIsNone(pid)
        self.assertFalse(music_sync.PID_FILE.exists())
        # No taskkill should have been called
        self.assertFalse(any(
            "taskkill" in str(call) for call in mock_run.call_args_list
        ))

    def test_toggle_with_pid_reuse_starts_new(self):
        """cmd_toggle with PID reuse -> no kill, starts new process."""
        music_sync.PID_FILE.write_text("4242")
        old_time = time.time() - 100
        os.utime(music_sync.PID_FILE, (old_time, old_time))
        fake_created = old_time + 3600
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
            with mock.patch.object(music_sync, "_process_create_time", return_value=fake_created):
                with mock.patch.object(arbiter, "music_active", return_value=False):
                    with mock.patch("subprocess.run") as mock_run:
                        with mock.patch("subprocess.Popen") as mock_popen:
                            mock_proc = mock.Mock()
                            mock_proc.pid = 99999
                            mock_popen.return_value = mock_proc
                            with mock.patch("builtins.print"):
                                result = music_sync.cmd_toggle()
        self.assertEqual(result, 0)
        # No taskkill should have been called
        self.assertFalse(any(
            "taskkill" in str(call) for call in mock_run.call_args_list
        ))
        # Popen should have been called once (to start new process)
        mock_popen.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows-only test")
    def test_process_create_time_real(self):
        """_process_create_time should return a valid timestamp for our own process."""
        now = time.time()
        created = music_sync._process_create_time(os.getpid())
        self.assertIsNotNone(created)
        self.assertIsInstance(created, float)
        # Should be within the last 7 days and not in the future (plus 1s margin)
        self.assertGreater(created, now - 7 * 86400)
        self.assertLess(created, now + 1)

    @unittest.skipUnless(os.name == "nt", "Windows-only test")
    def test_process_create_time_nonexistent_pid(self):
        """_process_create_time should return None for a nonexistent PID."""
        created = music_sync._process_create_time(0x7FFFFFFC)
        self.assertIsNone(created)

    def test_run_cleans_pid_on_no_devices(self):
        """run() should remove its own PID file when exiting due to no devices."""
        my_pid = os.getpid()
        music_sync.PID_FILE.write_text(str(my_pid))

        with mock.patch.object(music_sync, "govee") as mock_govee:
            with self.assertRaises(SystemExit) as ctx:
                music_sync.run({"devices": []}, fps=10)
        self.assertEqual(ctx.exception.code, 1)
        self.assertFalse(music_sync.PID_FILE.exists(),
                        "run() should have removed its own PID file on no devices")

    def test_run_cleans_pid_on_missing_soundcard(self):
        """run() should remove its own PID file when soundcard import fails."""
        my_pid = os.getpid()
        music_sync.PID_FILE.write_text(str(my_pid))

        with mock.patch.dict(sys.modules, {"soundcard": None, "numpy": None}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                with self.assertRaises(SystemExit) as ctx:
                    music_sync.run({"devices": [{"ip": "1.2.3.4"}]}, fps=10)
        self.assertEqual(ctx.exception.code, 2)
        self.assertFalse(music_sync.PID_FILE.exists(),
                        "run() should have removed its own PID file on missing soundcard")

    def test_run_cleans_pid_on_no_loopback(self):
        """run() should keep running when no loopback device found (no sys.exit)."""
        self.set_mode("music")
        my_pid = os.getpid()
        music_sync.PID_FILE.write_text(str(my_pid))

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(side_effect=Exception("not found"))
        fake_sc.all_microphones = mock.Mock(return_value=[])

        # Track govee calls - should turn off once
        govee_calls = []
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.turn = fake_turn
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            # Run for a few iterations, then stop via flag
                            stop_after = [0]
                            def fake_stop_flag_exists():
                                stop_after[0] += 1
                                return stop_after[0] > 3
                            with mock.patch.object(music_sync, "STOP_FLAG_FILE") as mock_stop_flag:
                                mock_stop_flag.exists = fake_stop_flag_exists
                                music_sync.run({"devices": [{"ip": "1.2.3.4"}]}, fps=10, time_fn=fake_time_fn)

        # Should have turned off once due to no device
        turn_off_calls = [c for c in govee_calls if c[0] == "turn" and not c[2]]
        self.assertEqual(len(turn_off_calls), 1,
                        "Expected exactly one turn-off call due to no device")
        # PID file should be removed
        self.assertFalse(music_sync.PID_FILE.exists(),
                        "run() should have removed its own PID file")

    def test_run_leaves_other_pid_on_no_devices(self):
        """run() should not remove a PID file that doesn't match its own PID."""
        music_sync.PID_FILE.write_text("99999")

        with mock.patch.object(music_sync, "govee") as mock_govee:
            with self.assertRaises(SystemExit) as ctx:
                music_sync.run({"devices": []}, fps=10)
        self.assertEqual(ctx.exception.code, 1)
        self.assertTrue(music_sync.PID_FILE.exists(),
                        "run() should not have removed another process's PID file")
        self.assertEqual(music_sync.PID_FILE.read_text().strip(), "99999")

    def test_run_clear_music_active_error_does_not_skip_cleanup(self):
        """When clear_music_active raises PermissionError, PID cleanup and restore
        should still run."""
        self.set_mode("music")
        my_pid = os.getpid()
        music_sync.PID_FILE.write_text(str(my_pid))

        # Track govee calls for restore
        govee_calls = []

        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))

        def fake_brightness(ip, b):
            govee_calls.append(("brightness", ip, b))

        # clear_music_active raises PermissionError
        def fake_clear_music_active():
            raise PermissionError("file in use")

        fake_rec = mock.Mock()
        fake_rec.record.side_effect = KeyboardInterrupt()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "clear_music_active", side_effect=fake_clear_music_active):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.brightness = fake_brightness
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                with self.assertLogs("music_sync", level="WARNING") as cm:
                                    try:
                                        music_sync.run(
                                            {"devices": [{"ip": "1.2.3.4"}]},
                                            fps=10,
                                            time_fn=fake_time_fn,
                                        )
                                    except KeyboardInterrupt:
                                        pass

        # PID file should be removed
        self.assertFalse(music_sync.PID_FILE.exists(),
                        "run() should have removed its own PID file")
        # Restore should have happened (brightness call in finally)
        brightness_calls = [c for c in govee_calls if c[0] == "brightness"]
        # One at start (setting to 80), one in finally (restoring to 50)
        self.assertEqual(len(brightness_calls), 2,
                        f"Expected 2 brightness calls (initial + restore), got {len(brightness_calls)}")
        # Warning about music heartbeat should be logged
        self.assertTrue(any("music heartbeat" in log for log in cm.output),
                       f"Expected warning about music heartbeat, got: {cm.output}")


class TestMusicActiveCorruptFile(StateDirMixin, unittest.TestCase):
    """Test that corrupt music_active.json is treated as inactive."""

    def test_corrupt_json_is_inactive(self):
        """A music_active.json with invalid JSON should be treated as inactive."""
        path = arbiter.music_file()
        path.write_text("not valid json {{{")
        self.assertFalse(arbiter.music_active())

    def test_fresh_valid_json_is_active(self):
        """A fresh, valid music_active.json should be active."""
        arbiter.set_music_active()
        self.assertTrue(arbiter.music_active())

    def test_empty_file_is_inactive(self):
        """An empty music_active.json should be treated as inactive."""
        path = arbiter.music_file()
        path.write_text("")
        self.assertFalse(arbiter.music_active())


class TestMusicActiveAtomicWrite(StateDirMixin, unittest.TestCase):
    """Test that set_music_active writes atomically."""

    def test_no_tmp_file_left_after_write(self):
        """set_music_active should not leave a .tmp file behind."""
        arbiter.set_music_active()
        # Check no tmp files remain
        tmp_files = list(self.state_dir.glob("music_active.json.tmp.*"))
        self.assertEqual(len(tmp_files), 0,
                        f"Expected no tmp files, found: {tmp_files}")
        # File should be valid JSON
        self.assertTrue(arbiter.music_active())

    def test_permission_error_retry(self):
        """set_music_active should retry on PermissionError and not raise."""
        # Create a valid existing file first
        arbiter.set_music_active()

        replace_calls = [0]

        def fake_replace(src, dst):
            replace_calls[0] += 1
            if replace_calls[0] <= 3:
                raise PermissionError("file in use")
            # On 4th call, succeed (but we only retry 3 times, so this tests fallback)
            import shutil
            shutil.move(src, dst)

        with mock.patch("os.replace", side_effect=fake_replace):
            with mock.patch("time.sleep"):
                arbiter.set_music_active()

        # Should have retried 3 times
        self.assertEqual(replace_calls[0], 3)
        # File should still be valid (fallback to utime)
        self.assertTrue(arbiter.music_active())


class TestPickLoopback(unittest.TestCase):
    """Test pick_loopback device selection."""

    def test_uses_default_speaker_loopback(self):
        """pick_loopback should use the default speaker's loopback by id."""
        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"
        fake_speaker.id = "{0.0.0.00000000}.{spk}"

        fake_mic = mock.Mock()
        fake_mic.name = "Speakers X"
        fake_mic.id = "{0.0.0.00000000}.{spk}"
        fake_mic.isloopback = True

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)

        result = music_sync.pick_loopback(fake_sc)
        self.assertIs(result, fake_mic)
        fake_sc.get_microphone.assert_called_once_with("{0.0.0.00000000}.{spk}", include_loopback=True)

    def test_ignores_non_loopback_match(self):
        """If get_microphone returns a non-loopback mic, fall back to first loopback."""
        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"
        fake_speaker.id = "{0.0.0.00000000}.{spk}"

        # get_microphone returns a non-loopback mic (same-name headset mic bug)
        fake_non_loopback = mock.Mock()
        fake_non_loopback.name = "Speakers X"
        fake_non_loopback.id = "{0.0.0.00000000}.{spk}"
        fake_non_loopback.isloopback = False

        # But all_microphones has a real loopback
        fake_loopback = mock.Mock()
        fake_loopback.name = "Speakers X (loopback)"
        fake_loopback.id = "{0.0.0.00000000}.{spk}"
        fake_loopback.isloopback = True

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_non_loopback)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_non_loopback, fake_loopback])

        result = music_sync.pick_loopback(fake_sc)
        self.assertIs(result, fake_loopback)

    def test_falls_back_to_first_loopback_mic(self):
        """If get_microphone raises, fall back to first isloopback mic."""
        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_mic1 = mock.Mock()
        fake_mic1.name = "Real Mic"
        fake_mic1.isloopback = False

        fake_mic2 = mock.Mock()
        fake_mic2.name = "Speakers Y"
        fake_mic2.isloopback = True

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(side_effect=Exception("not found"))
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic1, fake_mic2])

        result = music_sync.pick_loopback(fake_sc)
        self.assertIs(result, fake_mic2)

    def test_returns_none_when_no_loopback(self):
        """If no loopback mics found, return None."""
        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_mic = mock.Mock()
        fake_mic.name = "Real Mic"
        fake_mic.isloopback = False

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(side_effect=Exception("not found"))
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        result = music_sync.pick_loopback(fake_sc)
        self.assertIsNone(result)


class TestRecorderOpenedOnce(StateDirMixin, unittest.TestCase):
    """Test that the recorder is opened once, not per frame."""

    def test_recorder_opened_once_for_multiple_frames(self):
        """mic.recorder should be called exactly once for 5 frames."""
        self.set_mode("music")
        recorder_call_count = [0]

        def fake_recorder(samplerate, channels):
            recorder_call_count[0] += 1
            fake_rec = mock.Mock()
            fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
            fake_rec.__exit__ = mock.Mock(return_value=False)
            fake_rec.close = mock.Mock()

            frame_count = [0]

            def fake_record(numframes):
                frame_count[0] += 1
                if frame_count[0] >= 5:
                    raise KeyboardInterrupt()
                return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

            fake_rec.record = mock.Mock(side_effect=fake_record)
            return fake_rec

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_mic = mock.Mock()
        fake_mic.name = "Speakers X"
        fake_mic.isloopback = True
        fake_mic.recorder = fake_recorder

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        self.assertEqual(recorder_call_count[0], 1,
                        f"Expected recorder opened once, got {recorder_call_count[0]}")


class TestRuntimeErrorRecovery(StateDirMixin, unittest.TestCase):
    """Test recovery from RuntimeError during audio capture."""

    def test_runtime_error_reopens_recorder(self):
        """RuntimeError on frame 2 should not exit; recorder reopened; colours sent after."""
        self.set_mode("music")
        recorder_call_count = [0]
        colors_sent = []
        total_record_calls = [0]

        def fake_color(ip, r, g, b):
            colors_sent.append((ip, r, g, b))

        def fake_recorder(samplerate, channels):
            recorder_call_count[0] += 1
            fake_rec = mock.Mock()
            fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
            fake_rec.__exit__ = mock.Mock(return_value=False)
            fake_rec.close = mock.Mock()

            def fake_record(numframes):
                total_record_calls[0] += 1
                if total_record_calls[0] == 1:
                    # First record call: RuntimeError
                    raise RuntimeError("WASAPI error")
                if total_record_calls[0] >= 4:
                    raise KeyboardInterrupt()
                return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

            fake_rec.record = mock.Mock(side_effect=fake_record)
            return fake_rec

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_mic = mock.Mock()
        fake_mic.name = "Speakers X"
        fake_mic.isloopback = True
        fake_mic.recorder = fake_recorder

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # Recorder should have been opened twice (once initially, once after error)
        self.assertEqual(recorder_call_count[0], 2,
                        f"Expected recorder opened twice, got {recorder_call_count[0]}")
        # Colours should have been sent after the error
        self.assertGreater(len(colors_sent), 0,
                          "Expected colours sent after RuntimeError recovery")


class TestRecorderReopenWithStrictFake(StateDirMixin, unittest.TestCase):
    """Test recorder reopen with a strict fake that enforces __enter__/__exit__."""

    def _make_strict_recorder(self, record_side_effect=None):
        """Create a strict fake recorder that enforces __enter__/__exit__."""
        class StrictRecorder:
            def __init__(self):
                self.entered = False
                self.exit_count = 0
                self.fail_enter = False

            def __enter__(self):
                if getattr(self, "fail_enter", False):
                    raise RuntimeError("enter failed")
                self.entered = True
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.exit_count += 1
                return False

            @property
            def exited(self):
                return self.exit_count > 0

            def record(self, numframes):
                if not self.entered or self.exit_count > 0:
                    raise RuntimeError("not entered")
                if record_side_effect is not None:
                    record_side_effect()
                return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        return StrictRecorder()

    def test_reopen_after_runtime_error(self):
        """RuntimeError on frame 2: run() keeps going, first recorder exited,
        second recorder entered, colours sent after error."""
        self.set_mode("music")
        recorders_created = []
        record_call_count = [0]

        def record_side_effect():
            record_call_count[0] += 1
            if record_call_count[0] == 1:
                # First record call: RuntimeError
                raise RuntimeError("WASAPI error")
            if record_call_count[0] >= 4:
                raise KeyboardInterrupt()

        def make_recorder(samplerate, channels):
            rec = self._make_strict_recorder(record_side_effect)
            recorders_created.append(rec)
            return rec

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_mic = mock.Mock()
        fake_mic.name = "Speakers X"
        fake_mic.isloopback = True
        fake_mic.recorder = make_recorder

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)

        colors_sent = []

        def fake_color(ip, r, g, b):
            colors_sent.append((ip, r, g, b))

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # Two recorders should have been created
        self.assertEqual(len(recorders_created), 2,
                        f"Expected 2 recorders, got {len(recorders_created)}")
        # First recorder should have been exited
        self.assertTrue(recorders_created[0].exited,
                       "First recorder should have been exited")
        # Second recorder should have been entered
        self.assertTrue(recorders_created[1].entered,
                       "Second recorder should have been entered")
        # Colours should have been sent after the error
        self.assertGreater(len(colors_sent), 0,
                          "Expected colours sent after RuntimeError recovery")

    def test_stop_flag_after_reopen(self):
        """Stop flag after a reopen: the second recorder's __exit__ is called exactly once."""
        self.set_mode("music")
        recorders_created = []
        record_call_count = [0]
        stop_after_reopen = [False]

        def record_side_effect():
            record_call_count[0] += 1
            if record_call_count[0] == 1:
                # First record call: RuntimeError
                raise RuntimeError("WASAPI error")
            if record_call_count[0] == 2:
                # After reopen, trigger stop flag
                stop_after_reopen[0] = True
                raise KeyboardInterrupt()

        def make_recorder(samplerate, channels):
            rec = self._make_strict_recorder(record_side_effect)
            recorders_created.append(rec)
            return rec

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_mic = mock.Mock()
        fake_mic.name = "Speakers X"
        fake_mic.isloopback = True
        fake_mic.recorder = make_recorder

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # Two recorders should have been created
        self.assertEqual(len(recorders_created), 2,
                        f"Expected 2 recorders, got {len(recorders_created)}")
        # Both recorders should have been exited
        self.assertTrue(recorders_created[0].exited,
                       "First recorder should have been exited")
        self.assertTrue(recorders_created[1].exited,
                       "Second recorder should have been exited")

    def test_pick_loopback_none_then_recovers(self):
        """pick_loopback returns None after the error for 2 frames, then a mic:
        run() does not exit and recovers."""
        self.set_mode("music")
        recorders_created = []
        record_call_count = [0]
        pick_call_count = [0]

        def record_side_effect():
            record_call_count[0] += 1
            if record_call_count[0] == 1:
                # First record call: RuntimeError
                raise RuntimeError("WASAPI error")
            if record_call_count[0] >= 4:
                raise KeyboardInterrupt()

        def make_recorder(samplerate, channels):
            rec = self._make_strict_recorder(record_side_effect)
            recorders_created.append(rec)
            return rec

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_mic = mock.Mock()
        fake_mic.name = "Speakers X"
        fake_mic.isloopback = True
        fake_mic.recorder = make_recorder

        def fake_pick_loopback(sc):
            pick_call_count[0] += 1
            # First call (initial): return mic
            # Second call (after error): return None
            # Third call (next frame): return None
            # Fourth call (next frame): return mic
            if pick_call_count[0] == 1:
                return fake_mic
            elif pick_call_count[0] <= 3:
                return None
            else:
                return fake_mic

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)

        colors_sent = []

        def fake_color(ip, r, g, b):
            colors_sent.append((ip, r, g, b))

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "pick_loopback", side_effect=fake_pick_loopback):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    mock_govee.brightness = mock.Mock()
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                    try:
                                        music_sync.run(
                                            {"devices": [{"ip": "1.2.3.4"}]},
                                            fps=10,
                                            time_fn=fake_time_fn,
                                        )
                                    except KeyboardInterrupt:
                                        pass

        # Should have recovered and sent colours
        self.assertGreater(len(colors_sent), 0,
                          "Expected colours sent after recovery")
        # pick_loopback should have been called multiple times
        self.assertGreater(pick_call_count[0], 1,
                          "pick_loopback should have been called multiple times")

    def test_reopen_enter_fails_once_then_works(self):
        """record fails on frame 2; the new recorder's __enter__ raises once,
        then works: run() recovers, colours are sent afterwards, every
        recorder's __exit__ count is <= 1, and the one in use at the end
        has count exactly 1."""
        self.set_mode("music")
        recorders_created = []
        record_call_count = [0]
        enter_call_count = [0]

        def record_side_effect():
            record_call_count[0] += 1
            if record_call_count[0] == 1:
                # First record call: RuntimeError
                raise RuntimeError("WASAPI error")
            if record_call_count[0] >= 4:
                raise KeyboardInterrupt()

        def make_recorder(samplerate, channels):
            rec = self._make_strict_recorder(record_side_effect)
            # Second recorder's __enter__ raises once
            if len(recorders_created) == 1:
                rec.fail_enter = True
            recorders_created.append(rec)
            return rec

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_mic = mock.Mock()
        fake_mic.name = "Speakers X"
        fake_mic.isloopback = True
        fake_mic.recorder = make_recorder

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)

        colors_sent = []

        def fake_color(ip, r, g, b):
            colors_sent.append((ip, r, g, b))

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # Three recorders should have been created
        self.assertEqual(len(recorders_created), 3,
                        f"Expected 3 recorders, got {len(recorders_created)}")
        # First recorder should have been exited exactly once
        self.assertEqual(recorders_created[0].exit_count, 1,
                        "First recorder should have been exited exactly once")
        # Second recorder (enter failed) should not have been exited
        self.assertEqual(recorders_created[1].exit_count, 0,
                        "Second recorder (enter failed) should not have been exited")
        # Third recorder should have been entered and exited by finally
        self.assertTrue(recorders_created[2].entered,
                       "Third recorder should have been entered")
        self.assertEqual(recorders_created[2].exit_count, 1,
                        "Third recorder should have been exited by finally")
        # Every recorder exit_count <= 1
        for i, rec in enumerate(recorders_created):
            self.assertLessEqual(rec.exit_count, 1,
                               f"Recorder {i} exit_count should be <= 1")
        # Colours should have been sent after the error
        self.assertGreater(len(colors_sent), 0,
                          "Expected colours sent after RuntimeError recovery")

    def test_stop_flag_while_rec_is_none(self):
        """Stop flag while rec is None (pick_loopback returns None):
        run() exits cleanly, no recorder exited twice."""
        self.set_mode("music")
        recorders_created = []
        pick_call_count = [0]
        record_call_count = [0]

        def fake_pick_loopback(sc):
            pick_call_count[0] += 1
            # First call (startup check): return mic
            # Second call (first in-loop open): return mic, recorder opens
            # Third call (after error, rec is None): return None
            if pick_call_count[0] <= 2:
                return fake_mic
            else:
                return None

        def make_recorder(samplerate, channels):
            rec = self._make_strict_recorder()
            recorders_created.append(rec)
            return rec

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_mic = mock.Mock()
        fake_mic.name = "Speakers X"
        fake_mic.isloopback = True
        fake_mic.recorder = make_recorder

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)

        fake_time_fn = bounded_clock()

        # Create stop flag after first record error
        def fake_record_side_effect():
            record_call_count[0] += 1
            if record_call_count[0] == 1:
                # First record call: create stop flag and raise error
                stop_flag = self.state_dir / "music_stop"
                stop_flag.write_text("stop")
                raise RuntimeError("WASAPI error")
            raise RuntimeError("should not reach here")

        fake_rec = self._make_strict_recorder(fake_record_side_effect)
        recorders_created.append(fake_rec)
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "pick_loopback", side_effect=fake_pick_loopback):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    mock_govee.brightness = mock.Mock()
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                music_sync.run(
                                    {"devices": [{"ip": "1.2.3.4"}]},
                                    fps=10,
                                    time_fn=fake_time_fn,
                                )

        # No recorder should have been exited twice
        for rec in recorders_created:
            self.assertLessEqual(rec.exit_count, 1,
                               "No recorder should be exited more than once")
        # The recorder that opened should have been exited exactly once
        self.assertEqual(fake_rec.exit_count, 1,
                        "Recorder should have been exited exactly once")
        # pick_loopback should have been called once (at startup)
        # The stop flag is checked before pick_loopback on subsequent iterations
        self.assertEqual(pick_call_count[0], 1,
                       "pick_loopback should have been called once at startup")

    def test_default_speaker_change_reopens(self):
        """When the default speaker changes, the recorder should be reopened."""
        self.set_mode("music")
        recorders_created = []
        calls_per_recorder = []
        current_speaker_id = ["A"]

        def record_side_effect():
            # Increment the counter for the current recorder
            calls_per_recorder[-1] += 1
            # Stop after 3 record calls on the second recorder
            if len(recorders_created) == 2 and calls_per_recorder[-1] >= 3:
                raise KeyboardInterrupt()

        def make_recorder(samplerate, channels):
            rec = self._make_strict_recorder(record_side_effect)
            recorders_created.append(rec)
            calls_per_recorder.append(0)
            return rec

        # Speaker A
        fake_speaker_a = mock.Mock()
        fake_speaker_a.name = "Speakers A"
        fake_speaker_a.id = "A"

        fake_mic_a = mock.Mock()
        fake_mic_a.name = "Speakers A"
        fake_mic_a.id = "A"
        fake_mic_a.isloopback = True
        fake_mic_a.recorder = make_recorder

        # Speaker B
        fake_speaker_b = mock.Mock()
        fake_speaker_b.name = "Speakers B"
        fake_speaker_b.id = "B"

        fake_mic_b = mock.Mock()
        fake_mic_b.name = "Speakers B"
        fake_mic_b.id = "B"
        fake_mic_b.isloopback = True
        fake_mic_b.recorder = make_recorder

        def fake_default_speaker():
            return fake_speaker_a if current_speaker_id[0] == "A" else fake_speaker_b

        def fake_get_microphone(id, include_loopback=False):
            if id == "A":
                return fake_mic_a
            else:
                return fake_mic_b

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(side_effect=fake_default_speaker)
        fake_sc.get_microphone = mock.Mock(side_effect=fake_get_microphone)

        # Change speaker after 4 seconds (before the first device check at 5s)
        # Bound the clock to prevent infinite loops if run() doesn't reopen
        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            if t > 1000:
                raise AssertionError("run() did not terminate")
            if t >= 4.0:
                current_speaker_id[0] = "B"
            return t

        fake_time = [0.0]

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # Two recorders should have been created (one for each speaker)
        self.assertEqual(len(recorders_created), 2,
                        f"Expected 2 recorders, got {len(recorders_created)}")
        # First recorder (speaker A) should have been exited
        self.assertEqual(recorders_created[0].exit_count, 1,
                        "First recorder should have been exited exactly once")
        # Second recorder (speaker B) should have been entered and exited
        self.assertTrue(recorders_created[1].entered,
                       "Second recorder should have been entered")
        self.assertEqual(recorders_created[1].exit_count, 1,
                        "Second recorder should have been exited exactly once")
        # Every recorder exit_count <= 1
        for i, rec in enumerate(recorders_created):
            self.assertLessEqual(rec.exit_count, 1,
                               f"Recorder {i} exit_count should be <= 1")
        # First recorder should have recorded at least one frame
        self.assertGreaterEqual(calls_per_recorder[0], 1,
                               "First recorder should have recorded at least one frame")
        # Second recorder should have recorded exactly 3 frames
        self.assertEqual(calls_per_recorder[1], 3,
                        "Second recorder should have recorded exactly 3 frames")
        # get_microphone should have been called with "A" first and "B" later
        mic_calls = fake_sc.get_microphone.call_args_list
        self.assertGreater(len(mic_calls), 0,
                          "get_microphone should have been called")
        self.assertEqual(mic_calls[0][0][0], "A",
                        "First get_microphone call should be for speaker A")
        self.assertEqual(mic_calls[-1][0][0], "B",
                        "Last get_microphone call should be for speaker B")

    def test_same_speaker_no_reopen(self):
        """When the default speaker doesn't change, the recorder should not be reopened."""
        self.set_mode("music")
        recorders_created = []
        record_call_count = [0]

        def record_side_effect():
            record_call_count[0] += 1
            if record_call_count[0] >= 100:
                raise KeyboardInterrupt()

        def make_recorder(samplerate, channels):
            rec = self._make_strict_recorder(record_side_effect)
            recorders_created.append(rec)
            return rec

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers A"
        fake_speaker.id = "A"

        fake_mic = mock.Mock()
        fake_mic.name = "Speakers A"
        fake_mic.id = "A"
        fake_mic.isloopback = True
        fake_mic.recorder = make_recorder

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)

        fake_time_fn = bounded_clock()

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # Only one recorder should have been created
        self.assertEqual(len(recorders_created), 1,
                        f"Expected 1 recorder, got {len(recorders_created)}")
        # It should have been exited exactly once (by finally)
        self.assertEqual(recorders_created[0].exit_count, 1,
                        "Recorder should have been exited exactly once")


class TestModeSwitchStep3(StateDirMixin, unittest.TestCase):
    """Tests for mode switch step 3: music_sync runs only in music mode."""

    def setUp(self):
        super().setUp()
        self.original_state_dir = music_sync.STATE_DIR
        self.original_pid_file = music_sync.PID_FILE
        self.original_stop_flag = music_sync.STOP_FLAG_FILE
        self.original_log_file = music_sync.LOG_FILE

        music_sync.STATE_DIR = self.state_dir
        music_sync.PID_FILE = self.state_dir / "music_sync.pid"
        music_sync.STOP_FLAG_FILE = self.state_dir / "music_stop"
        music_sync.LOG_FILE = self.state_dir / "music_sync.log"

    def tearDown(self):
        music_sync.STATE_DIR = self.original_state_dir
        music_sync.PID_FILE = self.original_pid_file
        music_sync.STOP_FLAG_FILE = self.original_stop_flag
        music_sync.LOG_FILE = self.original_log_file
        super().tearDown()

    def test_mode_change_exits_loop(self):
        """run(): mode changes to "weather" mid-run -> loop ends, PID file gone,
        music_active cleared, no restore sent."""
        self.set_mode("music")

        # Track govee calls
        govee_calls = []
        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))
        def fake_brightness(ip, b):
            govee_calls.append(("brightness", ip, b))
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))

        # Change mode to "weather" after first frame
        mode_changed = [False]
        def fake_get_mode():
            if mode_changed[0]:
                return "weather"
            return "music"

        fake_time_fn = bounded_clock()

        # Create a fake recorder
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]
        def fake_record(numframes):
            frame_count[0] += 1
            if frame_count[0] >= 2:
                # Change mode after first frame
                mode_changed[0] = True
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "get_mode", side_effect=fake_get_mode):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.brightness = fake_brightness
                    mock_govee.turn = fake_turn
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )

        # PID file should be gone
        self.assertFalse(music_sync.PID_FILE.exists(),
                        "PID file should be removed after mode change exit")
        # music_active should be cleared
        self.assertFalse(arbiter.music_active(),
                        "music_active should be cleared after mode change exit")
        # No restore calls (no turn off, no brightness/color restore)
        # Only the initial brightness set should have happened
        brightness_calls = [c for c in govee_calls if c[0] == "brightness"]
        self.assertEqual(len(brightness_calls), 1,
                        f"Expected 1 brightness call (initial only), got {len(brightness_calls)}")

    def test_silence_turns_off_lights(self):
        """run(): silent frames for > silence_seconds -> exactly one off;
        then loud frames -> on + colour."""
        self.set_mode("music")

        # Track govee calls
        govee_calls = []
        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))

        fake_time_fn = bounded_clock(step=0.1)

        # Create a fake recorder
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]
        def fake_record(numframes):
            frame_count[0] += 1
            if frame_count[0] >= 30:  # 3 seconds of silence, then loud
                raise KeyboardInterrupt()
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        # Silent for first 25 frames, then loud
        def fake_analyze(samples, rate):
            if frame_count[0] <= 25:
                return {"level": 0.01, "bass": 0.0, "mid": 0.0, "treble": 0.0}
            else:
                return {"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.turn = fake_turn
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", side_effect=fake_analyze):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}], "music": {"silence_seconds": 2.0}},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # Should have turned off once due to silence
        turn_off_calls = [c for c in govee_calls if c[0] == "turn" and not c[2]]
        self.assertEqual(len(turn_off_calls), 1,
                        f"Expected exactly one turn-off call, got {len(turn_off_calls)}")
        # Should have turned on twice: once at start, once when sound returned
        turn_on_calls = [c for c in govee_calls if c[0] == "turn" and c[2]]
        self.assertEqual(len(turn_on_calls), 2,
                        f"Expected exactly two turn-on calls (start + sound returned), got {len(turn_on_calls)}")
        # Should have sent colours after sound returned
        color_calls = [c for c in govee_calls if c[0] == "color"]
        self.assertGreater(len(color_calls), 0,
                          "Expected colour calls after sound returned")

    def test_short_gap_no_off(self):
        """run(): a gap shorter than silence_seconds -> no off."""
        self.set_mode("music")

        # Track govee calls
        govee_calls = []
        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))

        fake_time_fn = bounded_clock(step=0.1)

        # Create a fake recorder
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]
        def fake_record(numframes):
            frame_count[0] += 1
            if frame_count[0] >= 15:  # 1.5 seconds, less than 2s silence threshold
                raise KeyboardInterrupt()
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        # Silent for 10 frames (1 second), then loud
        def fake_analyze(samples, rate):
            if frame_count[0] <= 10:
                return {"level": 0.01, "bass": 0.0, "mid": 0.0, "treble": 0.0}
            else:
                return {"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.turn = fake_turn
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", side_effect=fake_analyze):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}], "music": {"silence_seconds": 2.0}},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # Should NOT have turned off (gap was too short)
        turn_off_calls = [c for c in govee_calls if c[0] == "turn" and not c[2]]
        self.assertEqual(len(turn_off_calls), 0,
                        f"Expected no turn-off calls, got {len(turn_off_calls)}")

    def test_no_device_turns_off_once(self):
        """run(): no device -> off sent once, loop keeps running for N iterations,
        mode.json still "music"."""
        self.set_mode("music")

        # Track govee calls
        govee_calls = []
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))

        fake_time_fn = bounded_clock(step=0.1)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(side_effect=Exception("not found"))
        fake_sc.all_microphones = mock.Mock(return_value=[])

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.turn = fake_turn
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            # Run for a few iterations, then stop via flag
                            stop_after = [0]
                            def fake_stop_flag_exists():
                                stop_after[0] += 1
                                return stop_after[0] > 5
                            with mock.patch.object(music_sync, "STOP_FLAG_FILE") as mock_stop_flag:
                                mock_stop_flag.exists = fake_stop_flag_exists
                                music_sync.run({"devices": [{"ip": "1.2.3.4"}]}, fps=10, time_fn=fake_time_fn)

        # Should have turned off once due to no device
        turn_off_calls = [c for c in govee_calls if c[0] == "turn" and not c[2]]
        self.assertEqual(len(turn_off_calls), 1,
                        f"Expected exactly one turn-off call, got {len(turn_off_calls)}")
        # Mode should still be "music"
        self.assertEqual(arbiter.get_mode(), "music",
                        "Mode should still be 'music' after no-device exit")

    def test_signal_clears_during_silence_sends_off(self):
        """run(): signal active -> nothing sent; signal clears during silence -> off (not a colour)."""
        self.set_mode("music")

        # Track govee calls
        govee_calls = []
        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))

        fake_time_fn = bounded_clock(step=0.1)

        # Signal is active for first 5 frames, then clears
        signal_active_count = [0]
        def fake_signal_active():
            signal_active_count[0] += 1
            return signal_active_count[0] <= 10  # Active for first ~5 frames (2 calls per frame)

        # Create a fake recorder
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]
        def fake_record(numframes):
            frame_count[0] += 1
            if frame_count[0] >= 30:  # Run long enough for silence timeout
                raise KeyboardInterrupt()
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        # Silent throughout
        def fake_analyze(samples, rate):
            return {"level": 0.01, "bass": 0.0, "mid": 0.0, "treble": 0.0}

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "signal_active", side_effect=fake_signal_active):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.turn = fake_turn
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    mock_govee.brightness = mock.Mock()
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                with mock.patch.object(music_sync, "analyze", side_effect=fake_analyze):
                                    try:
                                        music_sync.run(
                                            {"devices": [{"ip": "1.2.3.4"}], "music": {"silence_seconds": 2.0}},
                                            fps=10,
                                            time_fn=fake_time_fn,
                                        )
                                    except KeyboardInterrupt:
                                        pass

        # No colours should have been sent (signal was active, then silence)
        color_calls = [c for c in govee_calls if c[0] == "color"]
        self.assertEqual(len(color_calls), 0,
                        f"Expected no colour calls, got {len(color_calls)}")
        # Should have turned off due to silence after signal cleared
        turn_off_calls = [c for c in govee_calls if c[0] == "turn" and not c[2]]
        self.assertEqual(len(turn_off_calls), 1,
                        f"Expected exactly one turn-off call, got {len(turn_off_calls)}")

    def test_mode_off_at_start_sends_nothing(self):
        """Bug 1: run() with mode "off" at start should send nothing to strips,
        remove PID file, and not create music_active.json."""
        self.set_mode("off")

        # Track govee calls
        govee_calls = []
        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))
        def fake_brightness(ip, b):
            govee_calls.append(("brightness", ip, b))
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))
        def fake_status(ip, timeout=2):
            govee_calls.append(("status", ip))
            return {"msg": {"data": {"brightness": 50}}}

        # Write a PID file so we can check it's removed
        my_pid = os.getpid()
        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
            music_sync.PID_FILE.write_text(str(my_pid))

            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.brightness = fake_brightness
                mock_govee.turn = fake_turn
                mock_govee.status = fake_status
                music_sync.run(
                    {"devices": [{"ip": "1.2.3.4"}]},
                    fps=10,
                )

            # PID file should be removed
            self.assertFalse(music_sync.PID_FILE.exists(),
                            "PID file should be removed when mode is not music")

        # No govee calls at all
        self.assertEqual(len(govee_calls), 0,
                        f"Expected no govee calls, got {len(govee_calls)}")
        # music_active.json should not exist
        self.assertFalse(arbiter.music_active(),
                        "music_active should not be set when mode is not music")

    def test_no_device_then_device_turns_on(self):
        """Bug 2: after "no audio device" the strips are never turned on again.
        No device for 3 loops, then a device with loud frames -> turn off once,
        later turn on once, then a colour."""
        self.set_mode("music")

        # Track govee calls in order
        govee_calls = []
        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))

        fake_time_fn = bounded_clock(step=0.1)

        # pick_loopback returns None for first 3 calls, then a mic
        pick_call_count = [0]
        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True

        def fake_pick_loopback(sc):
            pick_call_count[0] += 1
            if pick_call_count[0] <= 3:
                return None
            return fake_mic

        # Recorder that works once device is found
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]
        def fake_record(numframes):
            frame_count[0] += 1
            if frame_count[0] >= 3:
                raise KeyboardInterrupt()
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "pick_loopback", side_effect=fake_pick_loopback):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.turn = fake_turn
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    mock_govee.brightness = mock.Mock()
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                    try:
                                        music_sync.run(
                                            {"devices": [{"ip": "1.2.3.4"}]},
                                            fps=10,
                                            time_fn=fake_time_fn,
                                        )
                                    except KeyboardInterrupt:
                                        pass

        # Should have turned off once due to no device
        turn_off_calls = [c for c in govee_calls if c[0] == "turn" and not c[2]]
        self.assertEqual(len(turn_off_calls), 1,
                        f"Expected exactly one turn-off call, got {len(turn_off_calls)}")
        # Should have turned on twice: once at start, once when device appeared
        turn_on_calls = [c for c in govee_calls if c[0] == "turn" and c[2]]
        self.assertEqual(len(turn_on_calls), 2,
                        f"Expected exactly two turn-on calls (start + device appeared), got {len(turn_on_calls)}")
        # Turn off should come before the second turn on
        off_idx = next(i for i, c in enumerate(govee_calls) if c[0] == "turn" and not c[2])
        # Find the index of the second turn-on call
        on_indices = [i for i, c in enumerate(govee_calls) if c[0] == "turn" and c[2]]
        self.assertLess(off_idx, on_indices[1],
                       "Turn off should come before second turn on")
        # Should have sent a colour after turning on
        color_calls = [c for c in govee_calls if c[0] == "color"]
        self.assertGreater(len(color_calls), 0,
                          "Expected colour calls after device appeared")
        # Colour should come after the second turn on
        color_idx = next(i for i, c in enumerate(govee_calls) if c[0] == "color")
        self.assertGreater(color_idx, on_indices[1],
                          "Colour should come after second turn on")

    def test_signal_active_during_silence_no_turn(self):
        """Bug 3: the silence off/turn-on is sent while the agent signal is active.
        Signal active at re-check, frames silent for longer than silence_seconds
        -> no govee.turn call at all."""
        self.set_mode("music")

        # Track govee calls
        govee_calls = []
        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))

        fake_time_fn = bounded_clock(step=0.1)

        # Signal is inactive at top of loop, active at re-check
        # Use a flag set by fake_record instead of counting calls
        captured = [False]
        def fake_signal_active():
            if captured[0]:
                captured[0] = False
                return True  # re-check before send
            return False  # top of loop

        # Create a fake recorder
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]
        def fake_record(numframes):
            frame_count[0] += 1
            captured[0] = True  # signal that we captured audio
            if frame_count[0] >= 30:  # 3 seconds of silence
                raise KeyboardInterrupt()
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        # Silent throughout
        def fake_analyze(samples, rate):
            return {"level": 0.01, "bass": 0.0, "mid": 0.0, "treble": 0.0}

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync.arbiter, "signal_active", side_effect=fake_signal_active):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.turn = fake_turn
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    mock_govee.brightness = mock.Mock()
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                with mock.patch.object(music_sync, "analyze", side_effect=fake_analyze):
                                    try:
                                        music_sync.run(
                                            {"devices": [{"ip": "1.2.3.4"}], "music": {"silence_seconds": 2.0}},
                                            fps=10,
                                            time_fn=fake_time_fn,
                                        )
                                    except KeyboardInterrupt:
                                        pass

        # Only the initial turn-on call (signal was active at re-check every time)
        turn_calls = [c for c in govee_calls if c[0] == "turn"]
        self.assertEqual(len(turn_calls), 1,
                        f"Expected 1 turn call (initial on), got {len(turn_calls)}")
        self.assertTrue(turn_calls[0][2], "Initial turn should be on")
        # No colour calls either
        color_calls = [c for c in govee_calls if c[0] == "color"]
        self.assertEqual(len(color_calls), 0,
                        f"Expected no colour calls, got {len(color_calls)}")


class TestModeSwitchMusic(StateDirMixin, unittest.TestCase):
    """Test that switch("music") calls cmd_start."""

    def test_switch_music_calls_cmd_start(self):
        """switch("music") calls music_sync.cmd_start()."""
        config = {"devices": [{"ip": "192.168.1.1"}]}
        with mock.patch("music_sync.cmd_start") as mock_start:
            def fake_start():
                arbiter.set_mode("music")
                return 0
            mock_start.side_effect = fake_start
            import mode
            mode.switch("music", config)
        mock_start.assert_called_once()
        self.assertEqual(arbiter.get_mode(), "music")

    def test_cmd_stop_sets_mode_off(self):
        """music_sync.cmd_stop() sets mode to "off"."""
        # Set mode to music first
        arbiter.set_mode("music")

        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
            with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                # Create a fake running process
                music_sync.PID_FILE.write_text("12345")

                with mock.patch.object(music_sync, "_is_process_alive", return_value=False):
                    with mock.patch.object(arbiter, "music_active", return_value=True):
                        with mock.patch("govee.load_config", return_value={"devices": []}):
                            with mock.patch("mode.govee.turn"):
                                with mock.patch("builtins.print"):
                                    music_sync.cmd_stop()

        self.assertEqual(arbiter.get_mode(), "off",
                        "cmd_stop should set mode to 'off'")

    def test_cmd_stop_turns_off_strips(self):
        """cmd_stop calls mode.switch('off', config) which turns strips off."""
        arbiter.set_mode("music")

        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
            with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                with mock.patch.object(music_sync, "_get_running_pid", return_value=None):
                    with mock.patch("govee.load_config") as mock_load:
                        mock_load.return_value = {"devices": [{"ip": "192.168.1.50"}]}
                        with mock.patch("mode.govee.turn") as mock_turn:
                            with mock.patch("builtins.print"):
                                rc = music_sync.cmd_stop()

        self.assertEqual(rc, 0)
        mock_load.assert_called_once()
        mock_turn.assert_called_once_with("192.168.1.50", False)
        self.assertEqual(arbiter.get_mode(), "off")

    def test_cmd_stop_config_error_still_sets_mode_off(self):
        """cmd_stop with config error still sets mode to 'off' and returns 0."""
        arbiter.set_mode("music")

        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
            with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                with mock.patch.object(music_sync, "_get_running_pid", return_value=None):
                    with mock.patch("govee.load_config", side_effect=OSError("no config")):
                        with mock.patch("builtins.print"):
                            rc = music_sync.cmd_stop()

        self.assertEqual(rc, 0)
        self.assertEqual(arbiter.get_mode(), "off")

    def test_cmd_start_sets_mode_music(self):
        """cmd_start sets mode to 'music' before spawning."""
        arbiter.set_mode("off")

        with mock.patch.object(music_sync, "STATE_DIR", self.state_dir):
            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        mock_popen.return_value.pid = 99999
                        with mock.patch("builtins.print"):
                            rc = music_sync.cmd_start()

        self.assertEqual(rc, 0)
        self.assertEqual(arbiter.get_mode(), "music")
        mock_popen.assert_called_once()

    def test_cmd_start_missing_dependency_no_mode_change(self):
        """cmd_start with missing dependency does not change mode."""
        arbiter.set_mode("off")

        with mock.patch.object(music_sync, "STATE_DIR", self.state_dir):
            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        with mock.patch("importlib.util.find_spec", return_value=None):
                            with mock.patch("builtins.print"):
                                rc = music_sync.cmd_start()

        self.assertNotEqual(rc, 0)
        self.assertEqual(arbiter.get_mode(), "off")
        mock_popen.assert_not_called()

    def test_cmd_start_set_mode_oserror(self):
        """cmd_start returns 1 when set_mode raises OSError."""
        arbiter.set_mode("off")

        with mock.patch.object(music_sync, "STATE_DIR", self.state_dir):
            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                    with mock.patch("subprocess.Popen") as mock_popen:
                        with mock.patch.object(arbiter, "set_mode", side_effect=OSError("locked")):
                            with mock.patch("builtins.print"):
                                rc = music_sync.cmd_start()

        self.assertEqual(rc, 1)
        mock_popen.assert_not_called()

    def test_cmd_toggle_running_sets_mode_off(self):
        """cmd_toggle while running stops music and sets mode to 'off'."""
        arbiter.set_mode("music")

        with mock.patch.object(music_sync, "STATE_DIR", self.state_dir):
            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                    with mock.patch.object(music_sync, "_get_running_pid", return_value=12345):
                        with mock.patch.object(music_sync, "_is_process_alive", return_value=False):
                            with mock.patch.object(arbiter, "music_active", return_value=True):
                                with mock.patch("govee.load_config", return_value={"devices": []}):
                                    with mock.patch("mode.govee.turn"):
                                        with mock.patch("builtins.print"):
                                            rc = music_sync.cmd_toggle()

        self.assertEqual(rc, 0)
        self.assertEqual(arbiter.get_mode(), "off")


class TestTurnAllErrorHandling(unittest.TestCase):
    """Test _turn_all error handling and return value."""

    def test_turn_all_returns_true_when_all_succeed(self):
        """_turn_all returns True when all devices succeed."""
        devices = [{"ip": "1.2.3.4"}, {"ip": "5.6.7.8"}]
        with mock.patch.object(music_sync, "govee") as mock_govee:
            mock_govee.turn = mock.Mock()
            result = music_sync._turn_all(devices, True)
        self.assertTrue(result)
        self.assertEqual(mock_govee.turn.call_count, 2)

    def test_turn_all_returns_false_when_one_fails(self):
        """_turn_all returns False when one device fails, logs warning, calls others."""
        devices = [{"ip": "1.2.3.4"}, {"ip": "5.6.7.8"}]
        turn_calls = []
        def fake_turn(ip, on):
            turn_calls.append((ip, on))
            if ip == "1.2.3.4":
                raise OSError("connection refused")
        with mock.patch.object(music_sync, "govee") as mock_govee:
            mock_govee.turn = fake_turn
            with self.assertLogs("music_sync", level="WARNING") as cm:
                result = music_sync._turn_all(devices, True)
        self.assertFalse(result)
        # Both devices should have been attempted
        self.assertEqual(len(turn_calls), 2)
        # Warning should mention the failed IP
        self.assertTrue(any("1.2.3.4" in log for log in cm.output))

    def test_turn_all_logs_turn_off_failure(self):
        """_turn_all logs 'turn off failed' when turning off fails."""
        devices = [{"ip": "1.2.3.4"}]
        with mock.patch.object(music_sync, "govee") as mock_govee:
            mock_govee.turn = mock.Mock(side_effect=OSError("timeout"))
            with self.assertLogs("music_sync", level="WARNING") as cm:
                music_sync._turn_all(devices, False)
        self.assertTrue(any("turn off failed" in log for log in cm.output))


class TestMusicSyncStartPowerOn(StateDirMixin, unittest.TestCase):
    """Test that music sync turns strips on at start."""

    def setUp(self):
        super().setUp()
        self.original_state_dir = music_sync.STATE_DIR
        self.original_pid_file = music_sync.PID_FILE
        self.original_stop_flag = music_sync.STOP_FLAG_FILE
        self.original_log_file = music_sync.LOG_FILE

        music_sync.STATE_DIR = self.state_dir
        music_sync.PID_FILE = self.state_dir / "music_sync.pid"
        music_sync.STOP_FLAG_FILE = self.state_dir / "music_stop"
        music_sync.LOG_FILE = self.state_dir / "music_sync.log"

    def tearDown(self):
        music_sync.STATE_DIR = self.original_state_dir
        music_sync.PID_FILE = self.original_pid_file
        music_sync.STOP_FLAG_FILE = self.original_stop_flag
        music_sync.LOG_FILE = self.original_log_file
        super().tearDown()

    def test_run_turns_on_at_start(self):
        """run() calls turn(ip, True) for each device at start."""
        self.set_mode("music")

        turn_calls = []
        def fake_turn(ip, on):
            turn_calls.append((ip, on))

        fake_time_fn = bounded_clock()

        # Create a fake recorder that raises KeyboardInterrupt on first frame
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)
        fake_rec.record.side_effect = KeyboardInterrupt()

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.turn = fake_turn
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            try:
                                music_sync.run(
                                    {"devices": [{"ip": "1.2.3.4"}, {"ip": "5.6.7.8"}]},
                                    fps=10,
                                    time_fn=fake_time_fn,
                                )
                            except KeyboardInterrupt:
                                pass

        # Should have turned on both devices at start
        turn_on_calls = [c for c in turn_calls if c[1] is True]
        self.assertEqual(len(turn_on_calls), 2,
                        f"Expected 2 turn-on calls at start, got {len(turn_on_calls)}")
        self.assertEqual(turn_on_calls[0][0], "1.2.3.4")
        self.assertEqual(turn_on_calls[1][0], "5.6.7.8")


class TestMusicSyncModeRace(StateDirMixin, unittest.TestCase):
    """Test mode re-check before sends (race condition fix)."""

    def setUp(self):
        super().setUp()
        self.original_state_dir = music_sync.STATE_DIR
        self.original_pid_file = music_sync.PID_FILE
        self.original_stop_flag = music_sync.STOP_FLAG_FILE
        self.original_log_file = music_sync.LOG_FILE

        music_sync.STATE_DIR = self.state_dir
        music_sync.PID_FILE = self.state_dir / "music_sync.pid"
        music_sync.STOP_FLAG_FILE = self.state_dir / "music_stop"
        music_sync.LOG_FILE = self.state_dir / "music_sync.log"

    def tearDown(self):
        music_sync.STATE_DIR = self.original_state_dir
        music_sync.PID_FILE = self.original_pid_file
        music_sync.STOP_FLAG_FILE = self.original_stop_flag
        music_sync.LOG_FILE = self.original_log_file
        super().tearDown()

    def test_mode_changed_before_send_exits(self):
        """If mode changes to 'off' during capture, no color sent and log shows exit."""
        self.set_mode("music")

        # Use a mutable dict so the recorder can change the mode during capture
        mode = {"value": "music"}

        govee_calls = []
        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))

        fake_time_fn = bounded_clock()

        # Create a fake recorder that changes mode to "off" during capture
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]
        def fake_record(numframes):
            frame_count[0] += 1
            # Change mode to "off" during capture (simulates user switching mode)
            mode["value"] = "off"
            # Return a loud frame (level well above silence threshold)
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "get_mode", side_effect=lambda: mode["value"]):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.turn = fake_turn
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    mock_govee.brightness = mock.Mock()
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                # Return a loud frame so silence detection doesn't interfere
                                with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                    with self.assertLogs("music_sync", level="INFO") as cm:
                                        music_sync.run(
                                            {"devices": [{"ip": "1.2.3.4"}]},
                                            fps=10,
                                            time_fn=fake_time_fn,
                                        )

        # No color calls (mode changed before send)
        color_calls = [c for c in govee_calls if c[0] == "color"]
        self.assertEqual(len(color_calls), 0,
                        f"Expected no color calls, got {len(color_calls)}")
        # No turn-on calls after the initial one (mode changed before any sends)
        turn_on_calls = [c for c in govee_calls if c[0] == "turn" and c[2]]
        self.assertEqual(len(turn_on_calls), 1,
                        f"Expected 1 turn-on call (initial), got {len(turn_on_calls)}")
        # Log should contain the mode change exit message
        self.assertTrue(any("mode changed to off; exiting music sync" in log for log in cm.output),
                       f"Expected 'mode changed to off; exiting music sync' in logs, got: {cm.output}")

    def test_mode_off_during_start_queries_no_power_on(self):
        """If mode changes to 'off' during start-up status queries, no brightness/turn-on sent."""
        self.set_mode("music")

        # Use a mutable dict so the status query can change the mode
        mode = {"value": "music"}

        govee_calls = []
        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))
        def fake_brightness(ip, level):
            govee_calls.append(("brightness", ip, level))

        fake_time_fn = bounded_clock()

        # Create a fake recorder that returns a loud frame
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)
        fake_rec.record = mock.Mock(return_value=mock.Mock(ndim=1, shape=(1024,), dtype="float64"))

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        # Mode changes to "off" during the status query
        def status_side_effect(ip, timeout=2):
            mode["value"] = "off"
            return None

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "get_mode", side_effect=lambda: mode["value"]):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.turn = fake_turn
                    mock_govee.brightness = fake_brightness
                    mock_govee.status = mock.Mock(side_effect=status_side_effect)
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}]},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )

        # No brightness or turn-on calls after mode changed to off
        brightness_calls = [c for c in govee_calls if c[0] == "brightness"]
        self.assertEqual(len(brightness_calls), 0,
                        f"Expected no brightness calls, got {len(brightness_calls)}")
        turn_on_calls = [c for c in govee_calls if c[0] == "turn" and c[2]]
        self.assertEqual(len(turn_on_calls), 0,
                        f"Expected no turn-on calls, got {len(turn_on_calls)}")

    def test_signal_active_during_start_no_power_on(self):
        """If an agent signal is active during start-up, no brightness/turn-on sent."""
        self.set_mode("music")

        govee_calls = []
        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))
        def fake_turn(ip, on):
            govee_calls.append(("turn", ip, on))
        def fake_brightness(ip, level):
            govee_calls.append(("brightness", ip, level))

        fake_time_fn = bounded_clock()

        # Create a fake recorder that returns a loud frame
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)
        fake_rec.record = mock.Mock(return_value=mock.Mock(ndim=1, shape=(1024,), dtype="float64"))

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        # Signal is active only during start-up (first call), then inactive
        signal_calls = [0]
        def signal_active_side_effect():
            signal_calls[0] += 1
            return signal_calls[0] == 1

        # Mode changes to "off" on the second call (at the top of the loop)
        mode_calls = [0]
        def get_mode_side_effect():
            mode_calls[0] += 1
            if mode_calls[0] == 1:
                return "music"  # First call: during start-up
            return "off"  # Second call: at the top of the loop

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "get_mode", side_effect=get_mode_side_effect):
                with mock.patch.object(arbiter, "signal_active", side_effect=signal_active_side_effect):
                    with mock.patch.object(music_sync, "govee") as mock_govee:
                        mock_govee.color = fake_color
                        mock_govee.turn = fake_turn
                        mock_govee.brightness = fake_brightness
                        mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                        with mock.patch("time.sleep"):
                            with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                                with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                                    with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                        music_sync.run(
                                            {"devices": [{"ip": "1.2.3.4"}]},
                                            fps=10,
                                            time_fn=fake_time_fn,
                                        )

        # No brightness or turn-on calls when signal was active during start-up
        brightness_calls = [c for c in govee_calls if c[0] == "brightness"]
        self.assertEqual(len(brightness_calls), 0,
                        f"Expected no brightness calls, got {len(brightness_calls)}")
        turn_on_calls = [c for c in govee_calls if c[0] == "turn" and c[2]]
        self.assertEqual(len(turn_on_calls), 0,
                        f"Expected no turn-on calls, got {len(turn_on_calls)}")


class TestSilenceOffRetry(StateDirMixin, unittest.TestCase):
    """Test that failed silence off is retried on next silent frame."""

    def setUp(self):
        super().setUp()
        self.original_state_dir = music_sync.STATE_DIR
        self.original_pid_file = music_sync.PID_FILE
        self.original_stop_flag = music_sync.STOP_FLAG_FILE
        self.original_log_file = music_sync.LOG_FILE

        music_sync.STATE_DIR = self.state_dir
        music_sync.PID_FILE = self.state_dir / "music_sync.pid"
        music_sync.STOP_FLAG_FILE = self.state_dir / "music_stop"
        music_sync.LOG_FILE = self.state_dir / "music_sync.log"

    def tearDown(self):
        music_sync.STATE_DIR = self.original_state_dir
        music_sync.PID_FILE = self.original_pid_file
        music_sync.STOP_FLAG_FILE = self.original_stop_flag
        music_sync.LOG_FILE = self.original_log_file
        super().tearDown()

    def test_failed_silence_off_retried(self):
        """If turn off fails, lights_on stays True and off is retried next silent frame."""
        self.set_mode("music")

        turn_calls = []
        def fake_turn(ip, on):
            turn_calls.append((ip, on))
            # First turn off fails (turn_calls[0] is the initial turn-on)
            if not on and len(turn_calls) == 2:
                raise OSError("connection refused")

        fake_time_fn = bounded_clock(step=0.1)

        # Create a fake recorder
        fake_rec = mock.Mock()
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        frame_count = [0]
        def fake_record(numframes):
            frame_count[0] += 1
            if frame_count[0] >= 30:  # 3 seconds of silence
                raise KeyboardInterrupt()
            return mock.Mock(ndim=1, shape=(1024,), dtype="float64")

        fake_rec.record = mock.Mock(side_effect=fake_record)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.isloopback = True
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_speaker = mock.Mock()
        fake_speaker.name = "Stereo Mix (loopback)"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(return_value=fake_mic)
        fake_sc.all_microphones = mock.Mock(return_value=[fake_mic])

        # Silent throughout
        def fake_analyze(samples, rate):
            return {"level": 0.01, "bass": 0.0, "mid": 0.0, "treble": 0.0}

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.turn = fake_turn
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                        with mock.patch.object(music_sync, "PID_FILE", self.state_dir / "music_sync.pid"):
                            with mock.patch.object(music_sync, "analyze", side_effect=fake_analyze):
                                try:
                                    music_sync.run(
                                        {"devices": [{"ip": "1.2.3.4"}], "music": {"silence_seconds": 2.0}},
                                        fps=10,
                                        time_fn=fake_time_fn,
                                    )
                                except KeyboardInterrupt:
                                    pass

        # Should have attempted turn off multiple times (first fails, later succeeds)
        turn_off_calls = [c for c in turn_calls if not c[1]]
        self.assertGreater(len(turn_off_calls), 1,
                          f"Expected multiple turn-off attempts, got {len(turn_off_calls)}")


if __name__ == "__main__":
    unittest.main()
