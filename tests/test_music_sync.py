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

import music_sync
import arbiter
from helpers import StateDirMixin


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
        # Signal becomes active on the second call (the re-check before sending)
        signal_active_count = [0]

        def fake_signal_active():
            signal_active_count[0] += 1
            # First call (top of loop) -> False
            # Second call (re-check before send) -> True
            # Third call (top of loop, next iteration) -> True
            # Fourth call (top of loop, next iteration) -> False
            # Fifth call (re-check before send) -> False
            if signal_active_count[0] == 1:
                return False
            elif signal_active_count[0] == 2:
                return True
            elif signal_active_count[0] == 3:
                return True
            else:
                return False

        # Track colours sent
        colors_sent = []

        def fake_color(ip, r, g, b):
            colors_sent.append((ip, r, g, b))

        # Fake time that advances 0.1s per call (10 fps)
        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

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
        # Signal is active throughout
        def fake_signal_active():
            return True

        # Track govee calls
        govee_calls = []

        def fake_color(ip, r, g, b):
            govee_calls.append(("color", ip, r, g, b))

        def fake_brightness(ip, b):
            govee_calls.append(("brightness", ip, b))

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

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
        # Only the initial brightness set should have happened
        brightness_calls = [c for c in govee_calls if c[0] == "brightness"]
        # One brightness call at start (setting to 80), none in finally
        self.assertEqual(len(brightness_calls), 1,
                        f"Expected 1 brightness call (initial only), got {len(brightness_calls)}")
        # No color calls in finally (restore would send color)
        color_calls = [c for c in govee_calls if c[0] == "color"]
        self.assertEqual(len(color_calls), 0,
                        f"Expected no color calls (no restore), got {len(color_calls)}")


class TestMusicHeartbeatClearOnException(StateDirMixin, unittest.TestCase):
    """Test that heartbeat file is removed when run() exits via exception."""

    def test_heartbeat_cleared_on_exception(self):
        """When run() exits via exception, music_active.json should be removed."""
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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
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
        call_order = []

        def fake_set_music_active():
            call_order.append("set_music_active")

        def fake_status(ip, timeout=2):
            call_order.append(f"status_{ip}")
            return {"msg": {"data": {"brightness": 50}}}

        def fake_brightness(ip, b):
            call_order.append(f"brightness_{ip}")

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

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
        # Create a leftover stop flag
        stop_flag = self.state_dir / "music_stop"
        stop_flag.write_text("leftover")
        self.assertTrue(stop_flag.exists())

        # Track colours sent
        colors_sent = []

        def fake_color(ip, r, g, b):
            colors_sent.append((ip, r, g, b))

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

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
        signal_pos = source.find("arbiter.signal_active()")
        self.assertGreater(stop_flag_pos, -1)
        self.assertGreater(signal_pos, -1)
        self.assertLess(stop_flag_pos, signal_pos)


    def test_run_cleans_own_pid_file_on_exception(self):
        """run() should remove its own PID file when exiting via exception."""
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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

        with mock.patch.dict(sys.modules, {
            "soundcard": fake_sc,
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
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
        """run() should remove its own PID file when no loopback device found."""
        my_pid = os.getpid()
        music_sync.PID_FILE.write_text(str(my_pid))

        fake_speaker = mock.Mock()
        fake_speaker.name = "Speakers X"

        fake_sc = mock.Mock()
        fake_sc.default_speaker = mock.Mock(return_value=fake_speaker)
        fake_sc.get_microphone = mock.Mock(side_effect=Exception("not found"))
        fake_sc.all_microphones = mock.Mock(return_value=[])

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                with self.assertRaises(SystemExit) as ctx:
                    music_sync.run({"devices": [{"ip": "1.2.3.4"}]}, fps=10)
        self.assertEqual(ctx.exception.code, 1)
        self.assertFalse(music_sync.PID_FILE.exists(),
                        "run() should have removed its own PID file on no loopback")

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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
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
                if self.exit_count > 1:
                    raise AssertionError("recorder __exit__ called more than once")
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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "pick_loopback", side_effect=fake_pick_loopback):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.color = fake_color
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    mock_govee.brightness = mock.Mock()
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

        with mock.patch.dict(sys.modules, {"soundcard": fake_sc, "numpy": mock.Mock()}):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
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

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

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
        # pick_loopback should have been called at least twice
        self.assertGreaterEqual(pick_call_count[0], 2,
                               "pick_loopback should have been called at least twice")


if __name__ == "__main__":
    unittest.main()
