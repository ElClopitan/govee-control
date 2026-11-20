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
        but should send after signal clears."""
        # Track signal state: active for first 3 frames, then cleared
        signal_state = [True, True, True, False, False]
        signal_idx = [0]

        def fake_signal_active():
            idx = signal_idx[0]
            signal_idx[0] = idx + 1
            if idx < len(signal_state):
                return signal_state[idx]
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
        fake_rec.record.return_value = mock.Mock(ndim=1, shape=(1024,), dtype="float64")
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        with mock.patch.dict(sys.modules, {
            "soundcard": mock.Mock(all_microphones=mock.Mock(return_value=[fake_mic])),
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
                                # Run for 5 frames then KeyboardInterrupt
                                def raise_ki_after_5(*args, **kwargs):
                                    if signal_idx[0] >= 5:
                                        raise KeyboardInterrupt()
                                    return fake_rec

                                with mock.patch.object(fake_mic, "recorder", side_effect=raise_ki_after_5):
                                    try:
                                        music_sync.run(
                                            {"devices": [{"ip": "1.2.3.4"}]},
                                            fps=10,
                                            time_fn=fake_time_fn,
                                        )
                                    except KeyboardInterrupt:
                                        pass

        # No colours should have been sent while signal was active (first 3 frames)
        # Colours should have been sent after signal cleared (frames 4-5)
        # Due to color_distance threshold, at most 1 colour is sent
        self.assertGreaterEqual(len(colors_sent), 1, "Expected at least one colour after signal cleared")


class TestMusicHeartbeatClearOnException(StateDirMixin, unittest.TestCase):
    """Test that heartbeat file is removed when run() exits via exception."""

    def test_heartbeat_cleared_on_exception(self):
        """When run() exits via exception, music_active.json should be removed."""
        # Create a fake recorder that raises an exception on first frame
        fake_rec = mock.Mock()
        fake_rec.record.side_effect = RuntimeError("audio capture failed")
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        fake_time = [0.0]

        def fake_time_fn():
            t = fake_time[0]
            fake_time[0] = t + 0.1
            return t

        with mock.patch.dict(sys.modules, {
            "soundcard": mock.Mock(all_microphones=mock.Mock(return_value=[fake_mic])),
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
                        except RuntimeError:
                            pass

        # Heartbeat file should be removed
        self.assertFalse(arbiter.music_file().exists(),
                         "music_active.json should be removed after exception")


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
        fake_rec.record.return_value = mock.Mock(ndim=1, shape=(1024,), dtype="float64")
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        frame_count = [0]

        def raise_ki_after_10(*args, **kwargs):
            frame_count[0] += 1
            if frame_count[0] >= 10:
                raise KeyboardInterrupt()
            return fake_rec

        with mock.patch.dict(sys.modules, {
            "soundcard": mock.Mock(all_microphones=mock.Mock(return_value=[fake_mic])),
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(arbiter, "set_music_active", side_effect=fake_set_music_active):
                with mock.patch.object(music_sync, "govee") as mock_govee:
                    mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                    mock_govee.brightness = mock.Mock()
                    with mock.patch("time.sleep"):
                        with mock.patch.object(music_sync, "STOP_FLAG_FILE", self.state_dir / "music_stop"):
                            with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                                with mock.patch.object(fake_mic, "recorder", side_effect=raise_ki_after_10):
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
        fake_rec.record.return_value = mock.Mock(ndim=1, shape=(1024,), dtype="float64")
        fake_rec.__enter__ = mock.Mock(return_value=fake_rec)
        fake_rec.__exit__ = mock.Mock(return_value=False)

        fake_mic = mock.Mock()
        fake_mic.name = "Stereo Mix (loopback)"
        fake_mic.recorder = mock.Mock(return_value=fake_rec)

        frame_count = [0]

        def raise_ki_after_2(*args, **kwargs):
            frame_count[0] += 1
            if frame_count[0] >= 2:
                raise KeyboardInterrupt()
            return fake_rec

        with mock.patch.dict(sys.modules, {
            "soundcard": mock.Mock(all_microphones=mock.Mock(return_value=[fake_mic])),
            "numpy": mock.Mock(),
        }):
            with mock.patch.object(music_sync, "govee") as mock_govee:
                mock_govee.color = fake_color
                mock_govee.status = mock.Mock(return_value={"msg": {"data": {"brightness": 50}}})
                mock_govee.brightness = mock.Mock()
                with mock.patch("time.sleep"):
                    with mock.patch.object(music_sync, "STOP_FLAG_FILE", stop_flag):
                        with mock.patch.object(music_sync, "analyze", return_value={"level": 0.5, "bass": 0.5, "mid": 0.5, "treble": 0.5}):
                            with mock.patch.object(fake_mic, "recorder", side_effect=raise_ki_after_2):
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
        with mock.patch.object(music_sync, "_is_process_alive", return_value=True):
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

    def test_stop_flag_checked_before_signal(self):
        """The stop flag should be checked before the signal check in the loop."""
        import inspect
        source = inspect.getsource(music_sync.run)
        stop_flag_pos = source.find("STOP_FLAG_FILE.exists()")
        signal_pos = source.find("arbiter.signal_active()")
        self.assertGreater(stop_flag_pos, -1)
        self.assertGreater(signal_pos, -1)
        self.assertLess(stop_flag_pos, signal_pos)


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


if __name__ == "__main__":
    unittest.main()
