"""Tests for weather_sync.py."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import weather_sync
import govee
from helpers import StateDirMixin


class _StopLoop(Exception):
    """Raised by test sleep side_effects to exit the sync loop."""
    pass


class TestWeatherToColor(unittest.TestCase):
    """Test the pure weather_to_color function."""

    def test_clear_day(self):
        """Clear sky during day -> warm yellow."""
        self.assertEqual(weather_sync.weather_to_color(0, 25.0, 1), "#ffd27f")
        self.assertEqual(weather_sync.weather_to_color(1, 25.0, 1), "#ffd27f")

    def test_clear_night(self):
        """Clear sky at night -> deep blue."""
        self.assertEqual(weather_sync.weather_to_color(0, 15.0, 0), "#1a237e")
        self.assertEqual(weather_sync.weather_to_color(1, 15.0, 0), "#1a237e")

    def test_partly_cloudy(self):
        """Partly cloudy -> grey."""
        self.assertEqual(weather_sync.weather_to_color(2, 20.0, 1), "#b0bec5")
        self.assertEqual(weather_sync.weather_to_color(3, 20.0, 1), "#b0bec5")

    def test_fog(self):
        """Fog -> light grey."""
        self.assertEqual(weather_sync.weather_to_color(45, 10.0, 1), "#cfd8dc")
        self.assertEqual(weather_sync.weather_to_color(48, 10.0, 1), "#cfd8dc")

    def test_drizzle(self):
        """Drizzle -> blue."""
        self.assertEqual(weather_sync.weather_to_color(51, 12.0, 1), "#1e88e5")
        self.assertEqual(weather_sync.weather_to_color(53, 12.0, 1), "#1e88e5")
        self.assertEqual(weather_sync.weather_to_color(55, 12.0, 1), "#1e88e5")

    def test_rain(self):
        """Rain -> blue."""
        self.assertEqual(weather_sync.weather_to_color(61, 15.0, 1), "#1e88e5")
        self.assertEqual(weather_sync.weather_to_color(63, 15.0, 1), "#1e88e5")
        self.assertEqual(weather_sync.weather_to_color(65, 15.0, 1), "#1e88e5")
        self.assertEqual(weather_sync.weather_to_color(67, 15.0, 1), "#1e88e5")

    def test_snow(self):
        """Snow -> pale blue."""
        self.assertEqual(weather_sync.weather_to_color(71, -2.0, 1), "#e3f2fd")
        self.assertEqual(weather_sync.weather_to_color(73, -2.0, 1), "#e3f2fd")
        self.assertEqual(weather_sync.weather_to_color(75, -2.0, 1), "#e3f2fd")
        self.assertEqual(weather_sync.weather_to_color(77, -2.0, 1), "#e3f2fd")

    def test_showers(self):
        """Showers -> blue."""
        self.assertEqual(weather_sync.weather_to_color(80, 18.0, 1), "#1e88e5")
        self.assertEqual(weather_sync.weather_to_color(81, 18.0, 1), "#1e88e5")
        self.assertEqual(weather_sync.weather_to_color(82, 18.0, 1), "#1e88e5")

    def test_snow_showers(self):
        """Snow showers -> pale blue."""
        self.assertEqual(weather_sync.weather_to_color(85, -1.0, 1), "#e3f2fd")
        self.assertEqual(weather_sync.weather_to_color(86, -1.0, 1), "#e3f2fd")

    def test_thunderstorm(self):
        """Thunderstorm -> purple."""
        self.assertEqual(weather_sync.weather_to_color(95, 22.0, 1), "#7b1fa2")
        self.assertEqual(weather_sync.weather_to_color(96, 22.0, 1), "#7b1fa2")
        self.assertEqual(weather_sync.weather_to_color(99, 22.0, 1), "#7b1fa2")

    def test_unknown_code(self):
        """Unknown weather code -> white."""
        self.assertEqual(weather_sync.weather_to_color(100, 20.0, 1), "#ffffff")
        self.assertEqual(weather_sync.weather_to_color(999, 20.0, 1), "#ffffff")


class TestFetchWeather(unittest.TestCase):
    """Test fetch_weather with mocked HTTP."""

    def _mock_response(self, data):
        """Create a mock HTTP response."""
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode("utf-8")
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        return mock_resp

    @mock.patch("urllib.request.urlopen")
    def test_fetch_success(self, mock_urlopen):
        """Successful weather fetch returns parsed data."""
        fixture = {
            "current": {
                "temperature_2m": 22.5,
                "weather_code": 3,
                "is_day": 1,
            }
        }
        mock_urlopen.return_value = self._mock_response(fixture)

        result = weather_sync.fetch_weather(51.5, -0.1)

        self.assertEqual(result["temperature_2m"], 22.5)
        self.assertEqual(result["weather_code"], 3)
        self.assertEqual(result["is_day"], 1)
        # Verify URL was called with correct params (Request object wraps the URL)
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        self.assertIn("latitude=51.5", request_obj.full_url)
        self.assertIn("longitude=-0.1", request_obj.full_url)

    @mock.patch("urllib.request.urlopen")
    def test_fetch_url_error(self, mock_urlopen):
        """Network error propagates."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timeout")

        with self.assertRaises(urllib.error.URLError):
            weather_sync.fetch_weather(51.5, -0.1)


class TestRunOnce(StateDirMixin, unittest.TestCase):
    """Test run() with once=True and mocked dependencies."""

    def _make_config(self, lat=51.5, lon=-0.1, brightness=50):
        return {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {
                "latitude": lat,
                "longitude": lon,
                "brightness": brightness,
            },
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_weather_color_applied(self, mock_brightness, mock_color, mock_fetch):
        """Weather colour is applied to devices."""
        mock_fetch.return_value = {
            "temperature_2m": 25.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Clear day -> #ffd27f = (255, 210, 127)
        self.assertEqual(mock_color.call_count, 1)
        mock_color.assert_called_with("192.168.1.50", 255, 210, 127)
        self.assertEqual(mock_brightness.call_count, 1)
        mock_brightness.assert_called_with("192.168.1.50", 50)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_night_color(self, mock_brightness, mock_color, mock_fetch):
        """Night clear sky uses deep blue."""
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 0,
            "is_day": 0,
        }
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Clear night -> #1a237e = (26, 35, 126)
        mock_color.assert_called_with("192.168.1.50", 26, 35, 126)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_rain_color(self, mock_brightness, mock_color, mock_fetch):
        """Rain uses blue (static, patterns disabled)."""
        mock_fetch.return_value = {
            "temperature_2m": 12.0,
            "weather_code": 61,
            "is_day": 1,
        }
        config = self._make_config()
        config["weather"]["patterns_enabled"] = False

        weather_sync.run(config, once=True)

        # Rain -> #1e88e5 = (30, 136, 229)
        mock_color.assert_called_with("192.168.1.50", 30, 136, 229)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_multiple_devices(self, mock_brightness, mock_color, mock_fetch):
        """All devices get the colour."""
        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 2,
            "is_day": 1,
        }
        config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "weather": {
                "latitude": 51.5,
                "longitude": -0.1,
                "brightness": 50,
                "patterns_enabled": False,
            },
        }

        weather_sync.run(config, once=True)

        self.assertEqual(mock_color.call_count, 2)
        # Brightness is sent only when it changes (optimization)
        self.assertGreaterEqual(mock_brightness.call_count, 1)


class TestZeroLocation(unittest.TestCase):
    """Test the 0.0/0.0 location refusal."""

    def test_zero_location_exits(self):
        """Both lat and lon 0.0 -> exit code 2."""
        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 0.0, "longitude": 0.0, "brightness": 50},
        }
        with self.assertRaises(SystemExit) as ctx:
            weather_sync.run(config, once=True)
        self.assertEqual(ctx.exception.code, 2)

    def test_zero_location_via_cli(self):
        """CLI with placeholder config exits 2."""
        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 0.0, "longitude": 0.0, "brightness": 50},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(config, f)
            config_path = f.name

        try:
            with mock.patch("sys.argv", [
                "weather_sync.py", "--once", "--dry-run",
                "--config", config_path
            ]):
                with self.assertRaises(SystemExit) as ctx:
                    weather_sync.main()
                self.assertEqual(ctx.exception.code, 2)
        finally:
            Path(config_path).unlink()


class TestNetworkError(StateDirMixin, unittest.TestCase):
    """Test network error handling."""

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("time.sleep")
    def test_network_error_once_mode(self, mock_sleep, mock_fetch):
        """Network error in --once mode exits non-zero."""
        import urllib.error
        mock_fetch.side_effect = urllib.error.URLError("connection failed")
        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }
        with self.assertRaises(SystemExit) as ctx:
            weather_sync.run(config, once=True)
        self.assertEqual(ctx.exception.code, 1)

    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("time.sleep")
    def test_network_error_loop_mode(self, mock_sleep, mock_fetch, mock_brightness, mock_color):
        """Network error in loop mode retries (doesn't crash)."""
        import urllib.error
        call_count = [0]

        def fail_then_succeed(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise urllib.error.URLError("first call fails")
            return {"temperature_2m": 20.0, "weather_code": 0, "is_day": 1}

        mock_fetch.side_effect = fail_then_succeed

        # Mock sleep to raise KeyboardInterrupt after 2 calls to exit loop
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            if sleep_count[0] >= 2:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }

        try:
            weather_sync.run(config, once=False, interval=1)
        except KeyboardInterrupt:
            pass

        # Should have called fetch twice (once failed, once succeeded)
        self.assertEqual(call_count[0], 2)
        # Should have sent color once (after successful fetch)
        self.assertEqual(mock_color.call_count, 1)
        mock_color.assert_called_with("192.168.1.50", 255, 210, 127)


    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("time.sleep")
    def test_connection_reset_once_mode(self, mock_sleep, mock_fetch):
        """ConnectionResetError in --once mode exits non-zero."""
        mock_fetch.side_effect = ConnectionResetError("connection reset")
        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }
        with self.assertRaises(SystemExit) as ctx:
            weather_sync.run(config, once=True)
        self.assertEqual(ctx.exception.code, 1)

    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("time.sleep")
    def test_govee_color_oserror_loop_mode(self, mock_sleep, mock_fetch, mock_brightness, mock_color):
        """govee.color OSError in loop mode retries (doesn't crash)."""
        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }

        call_count = [0]
        def color_side_effect(ip, r, g, b):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("network down")

        mock_color.side_effect = color_side_effect

        # Mock sleep to raise KeyboardInterrupt after 2 calls to exit loop
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            if sleep_count[0] >= 2:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }

        try:
            weather_sync.run(config, once=False, interval=1)
        except KeyboardInterrupt:
            pass

        # Should have tried to send color twice (once failed, once succeeded)
        self.assertEqual(call_count[0], 2)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("time.sleep")
    def test_null_weather_code_once_mode(self, mock_sleep, mock_fetch):
        """Null weather_code in --once mode exits non-zero."""
        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": None,
            "is_day": 1,
        }
        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }
        with self.assertRaises(SystemExit) as ctx:
            weather_sync.run(config, once=True)
        self.assertEqual(ctx.exception.code, 1)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_null_temperature_once_mode(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Null temperature_2m in --once mode exits non-zero and does not send color."""
        mock_fetch.return_value = {
            "temperature_2m": None,
            "weather_code": 0,
            "is_day": 1,
        }
        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }
        with self.assertRaises(SystemExit) as ctx:
            weather_sync.run(config, once=True)
        self.assertEqual(ctx.exception.code, 1)
        # Should not have sent any color
        mock_color.assert_not_called()


class TestFetchWeatherUrl(unittest.TestCase):
    """Test fetch_weather URL construction."""

    def _mock_response(self, data):
        """Create a mock HTTP response."""
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(data).encode("utf-8")
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        return mock_resp

    @mock.patch("urllib.request.urlopen")
    def test_url_encoding(self, mock_urlopen):
        """URL uses urllib.parse.urlencode (commas are escaped)."""
        fixture = {
            "current": {
                "temperature_2m": 22.5,
                "weather_code": 3,
                "is_day": 1,
            }
        }
        mock_urlopen.return_value = self._mock_response(fixture)

        weather_sync.fetch_weather(51.5, -0.1)

        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        # urlencode escapes commas as %2C
        self.assertIn("latitude=51.5", request_obj.full_url)
        self.assertIn("longitude=-0.1", request_obj.full_url)
        self.assertIn("current=temperature_2m%2Cweather_code%2Cis_day", request_obj.full_url)


class TestDryRun(unittest.TestCase):
    """Test dry-run mode."""

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_dry_run_no_send(self, mock_brightness, mock_color, mock_fetch):
        """Dry-run mode prints instead of sending."""
        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }

        weather_sync.run(config, once=True, dry_run=True)

        # Should NOT have called govee functions
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()


class TestPriority(StateDirMixin, unittest.TestCase):
    """Test that weather sync respects signal/game priority."""

    def _make_config(self):
        return {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_game_active_skips_send(self, mock_brightness, mock_color, mock_fetch):
        """When game is active, weather sync does not send to lights."""
        import arbiter
        arbiter.set_game_active("Test Game")

        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Should NOT have called govee functions
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_signal_active_skips_send(self, mock_brightness, mock_color, mock_fetch):
        """When signal is active, weather sync does not send to lights."""
        import arbiter
        (arbiter.STATE_DIR / "saved_state.json").write_text("[]")

        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Should NOT have called govee functions
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_no_priority_sends_color(self, mock_brightness, mock_color, mock_fetch):
        """When neither signal nor game is active, weather sync sends color."""
        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Should have called govee functions
        self.assertEqual(mock_color.call_count, 1)
        mock_color.assert_called_with("192.168.1.50", 255, 210, 127)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_stale_game_active_allows_weather(self, mock_brightness, mock_color, mock_fetch):
        """A stale game_active.json (mtime > 60s) does not block weather sync."""
        import arbiter
        # Create a game_active.json with mtime 120 seconds ago
        arbiter.set_game_active("Test Game")
        path = arbiter.STATE_DIR / "game_active.json"
        old_time = time.time() - 120
        os.utime(path, (old_time, old_time))

        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Should have called govee functions (stale game_active ignored)
        self.assertEqual(mock_color.call_count, 1)
        mock_color.assert_called_with("192.168.1.50", 255, 210, 127)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_reapply_after_priority_clear_survives_failure(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """After priority clears, re-apply even if first attempt fails.

        Pass 1: sends colour X
        Pass 2: signal active (no send)
        Pass 3: signal gone but fetch raises OSError
        Pass 4: signal gone, fetch returns same X -> sends again
        Total: govee.color called exactly 2 times (pass 1 and pass 4)
        """
        import arbiter

        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config()

        # Track sleep calls to control state transitions
        sleep_count = [0]

        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            if sleep_count[0] == 1:
                # After pass 1, activate signal
                (arbiter.STATE_DIR / "saved_state.json").write_text("[]")
            elif sleep_count[0] == 2:
                # After pass 2 (signal active), remove signal
                (arbiter.STATE_DIR / "saved_state.json").unlink()
            elif sleep_count[0] == 4:
                # After pass 4 (successful re-apply), exit
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        # Make fetch fail on pass 3 only (when sleep_count is 2, we're in pass 3)
        def fetch_side_effect(*args, **kwargs):
            if sleep_count[0] == 2:
                # Pass 3: signal just cleared, fetch fails
                raise OSError("network unreachable")
            return mock_fetch.return_value

        mock_fetch.side_effect = fetch_side_effect

        try:
            weather_sync.run(config, once=False, interval=1)
        except KeyboardInterrupt:
            pass

        # govee.color should be called exactly 2 times: pass 1 and pass 4
        self.assertEqual(mock_color.call_count, 2)


class TestBlockedPollInterval(StateDirMixin, unittest.TestCase):
    """Test that weather sync polls every 10s while blocked."""

    def _make_config(self):
        return {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_blocked_uses_shorter_interval(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """When blocked by signal, sleep uses min(interval, 10) not full interval."""
        import arbiter
        # Create signal file to block weather sync
        (arbiter.STATE_DIR / "saved_state.json").write_text("[]")

        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config()

        # Run with interval=900; should sleep 10s while blocked
        def sleep_side_effect(seconds):
            # Verify the sleep duration is 10, not 900
            self.assertEqual(seconds, 10)
            raise _StopLoop()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except _StopLoop:
            pass

        # Should have slept once with 10 seconds
        self.assertEqual(mock_sleep.call_count, 1)
        mock_sleep.assert_called_with(10)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_blocked_recheck_uses_shorter_interval(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """When blocked during re-check before send, sleep uses min(interval, 10)."""
        import arbiter

        def fetch_with_game(*args, **kwargs):
            # Simulate game becoming active during the fetch
            arbiter.set_game_active("Test Game")
            return {
                "temperature_2m": 20.0,
                "weather_code": 0,
                "is_day": 1,
            }

        mock_fetch.side_effect = fetch_with_game
        config = self._make_config()

        def sleep_side_effect(seconds):
            # Verify the sleep duration is 10, not 900
            self.assertEqual(seconds, 10)
            raise _StopLoop()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except _StopLoop:
            pass

        # Should have slept once with 10 seconds
        self.assertEqual(mock_sleep.call_count, 1)
        mock_sleep.assert_called_with(10)


class TestPriorityRecheckBeforeSend(StateDirMixin, unittest.TestCase):
    """Test that weather sync re-checks priority just before sending."""

    def _make_config(self):
        return {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_signal_during_fetch_skips_send(self, mock_brightness, mock_color, mock_fetch):
        """If signal becomes active during weather fetch, skip sending.

        This tests the re-check just before the send loop. The signal file
        is created as a side effect of fetch_weather, simulating a race
        where the signal is raised while weather is being fetched.
        """
        import arbiter

        def fetch_with_signal(*args, **kwargs):
            # Simulate signal being raised during the fetch
            (arbiter.STATE_DIR / "saved_state.json").write_text("[]")
            return {
                "temperature_2m": 20.0,
                "weather_code": 0,
                "is_day": 1,
            }

        mock_fetch.side_effect = fetch_with_signal
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Should NOT have called govee functions because signal became active
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_game_during_fetch_skips_send(self, mock_brightness, mock_color, mock_fetch):
        """If game becomes active during weather fetch, skip sending."""
        import arbiter

        def fetch_with_game(*args, **kwargs):
            # Simulate game becoming active during the fetch
            arbiter.set_game_active("Test Game")
            return {
                "temperature_2m": 20.0,
                "weather_code": 0,
                "is_day": 1,
            }

        mock_fetch.side_effect = fetch_with_game
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Should NOT have called govee functions because game became active
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_one_skip_log_per_block(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Only one 'skipped:' log line per blocked period, not two.

        When the re-check branch fires (signal/game became active during
        fetch), it must set priority_was_active = True so the next loop
        pass does not also log 'skipped: signal/game active'.
        """
        import arbiter

        def fetch_with_signal(*args, **kwargs):
            # Simulate signal being raised during the fetch
            (arbiter.STATE_DIR / "saved_state.json").write_text("[]")
            return {
                "temperature_2m": 20.0,
                "weather_code": 0,
                "is_day": 1,
            }

        mock_fetch.side_effect = fetch_with_signal

        # Exit the loop after the 3rd sleep call
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            if sleep_count[0] >= 3:
                raise _StopLoop()

        mock_sleep.side_effect = sleep_side_effect
        config = self._make_config()

        with self.assertLogs("weather_sync", "INFO") as cm:
            try:
                weather_sync.run(config, once=False, interval=900)
            except _StopLoop:
                pass

        # Count how many log records contain "skipped:"
        skipped_records = [r for r in cm.records if "skipped:" in r.getMessage()]
        # First pass: "skipped: signal/game became active during fetch"
        # Subsequent passes: no additional "skipped:" because priority_was_active is True
        self.assertEqual(len(skipped_records), 1,
                         f"Expected 1 skipped log, got {len(skipped_records)}: "
                         + "; ".join(r.getMessage() for r in skipped_records))


class TestBrightnessCap(StateDirMixin, unittest.TestCase):
    """Test that brightness is capped at max_brightness (default 80)."""

    @mock.patch("weather_sync.govee.color")
    @mock.patch("weather_sync.govee.brightness")
    @mock.patch("weather_sync.fetch_weather")
    def test_weather_brightness_capped_at_80(self, mock_fetch, mock_brightness, mock_color):
        """Weather brightness of 100 is capped to 80 (default max_brightness)."""
        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }

        config = {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {
                "latitude": 51.5074,
                "longitude": -0.1278,
                "brightness": 100,
            },
        }

        weather_sync.run(config, once=True)

        # Brightness should be capped at 80, not 100
        self.assertEqual(mock_brightness.call_count, 1)
        self.assertEqual(mock_brightness.call_args[0][1], 80)


class TestPatternFrame(unittest.TestCase):
    """Test the pure pattern_frame function."""

    def test_static_pattern(self):
        """Static pattern returns the configured color."""
        pattern = {"type": "static", "color": "#ff0000", "brightness": 50}
        r, g, b, brightness = weather_sync.pattern_frame(pattern, 0.0, 0)
        self.assertEqual((r, g, b), (255, 0, 0))
        self.assertEqual(brightness, 50)

    def test_drift_pattern_endpoints(self):
        """Drift pattern at t=0 returns color1."""
        pattern = {
            "type": "drift",
            "color1": "#000000",
            "color2": "#ffffff",
            "period": 10.0,
            "brightness": 80,
            "phase_offset": 0.0,
        }
        # At t=0, phase=0, interp_t=0 -> color1
        r, g, b, brightness = weather_sync.pattern_frame(pattern, 0.0, 0)
        self.assertEqual((r, g, b), (0, 0, 0))
        self.assertEqual(brightness, 80)

    def test_drift_pattern_midpoint(self):
        """Drift pattern at midpoint returns color2."""
        pattern = {
            "type": "drift",
            "color1": "#000000",
            "color2": "#ffffff",
            "period": 10.0,
            "brightness": 80,
            "phase_offset": 0.0,
        }
        # At t=2.5 (phase=0.25), interp_t=0.5 -> midpoint
        r, g, b, brightness = weather_sync.pattern_frame(pattern, 2.5, 0)
        self.assertEqual((r, g, b), (127, 127, 127))
        self.assertEqual(brightness, 80)

    def test_wave_pattern_endpoints(self):
        """Wave pattern at t=0 returns color1."""
        pattern = {
            "type": "wave",
            "color1": "#000000",
            "color2": "#ffffff",
            "period": 10.0,
            "brightness": 80,
            "phase_offset": 0.0,
        }
        # At t=0, phase=0, cos(0)=1, interp_t=0 -> color1
        r, g, b, brightness = weather_sync.pattern_frame(pattern, 0.0, 0)
        self.assertEqual((r, g, b), (0, 0, 0))
        self.assertEqual(brightness, 80)

    def test_wave_pattern_midpoint(self):
        """Wave pattern at quarter period returns color2."""
        pattern = {
            "type": "wave",
            "color1": "#000000",
            "color2": "#ffffff",
            "period": 10.0,
            "brightness": 80,
            "phase_offset": 0.0,
        }
        # At t=2.5 (phase=0.25), cos(pi/2)=0, interp_t=0.5 -> midpoint
        r, g, b, brightness = weather_sync.pattern_frame(pattern, 2.5, 0)
        self.assertEqual((r, g, b), (127, 127, 127))
        self.assertEqual(brightness, 80)

    def test_rain_strips_out_of_phase(self):
        """Rain pattern: strip 0 and strip 1 are out of phase at same t."""
        pattern = {
            "type": "wave",
            "color1": "#1e88e5",
            "color2": "#0d47a1",
            "period": 8.0,
            "brightness": 80,
            "phase_offset": 4.0,
        }
        # At t=0, strip 0 is at phase 0, strip 1 is at phase 0.5
        r0, g0, b0, _ = weather_sync.pattern_frame(pattern, 0.0, 0)
        r1, g1, b1, _ = weather_sync.pattern_frame(pattern, 0.0, 1)
        # They should be different (out of phase)
        self.assertNotEqual((r0, g0, b0), (r1, g1, b1))

    def test_rain_strips_match_at_half_cycle(self):
        """Rain pattern: strip 0 at t matches strip 1 at t + half cycle."""
        pattern = {
            "type": "wave",
            "color1": "#1e88e5",
            "color2": "#0d47a1",
            "period": 8.0,
            "brightness": 80,
            "phase_offset": 4.0,
        }
        # Strip 0 at t=0 should match strip 1 at t=4 (half cycle later)
        r0, g0, b0, _ = weather_sync.pattern_frame(pattern, 0.0, 0)
        r1, g1, b1, _ = weather_sync.pattern_frame(pattern, 4.0, 1)
        self.assertEqual((r0, g0, b0), (r1, g1, b1))

    def test_cloudy_pattern(self):
        """Cloudy pattern uses drift between grey tones."""
        pattern = {
            "type": "drift",
            "color1": "#b0bec5",
            "color2": "#eceff1",
            "period": 40.0,
            "brightness": 75,
            "phase_offset": 0.0,
        }
        # At t=0, should be color1
        r, g, b, brightness = weather_sync.pattern_frame(pattern, 0.0, 0)
        self.assertEqual((r, g, b), (176, 190, 197))
        self.assertEqual(brightness, 75)


class TestGetPatternForCode(unittest.TestCase):
    """Test pattern selection by weather code."""

    def test_cloudy_codes_get_pattern(self):
        """Weather codes 2-3 get cloudy pattern."""
        patterns_cfg = {}
        for code in [2, 3]:
            pattern = weather_sync.get_pattern_for_code(code, patterns_cfg)
            self.assertIsNotNone(pattern)
            self.assertEqual(pattern["type"], "drift")

    def test_rain_codes_get_pattern(self):
        """Weather codes 51-67 and 80-82 get rain pattern."""
        patterns_cfg = {}
        for code in [51, 53, 55, 61, 63, 65, 67, 80, 81, 82]:
            pattern = weather_sync.get_pattern_for_code(code, patterns_cfg)
            self.assertIsNotNone(pattern)
            self.assertEqual(pattern["type"], "wave")

    def test_other_codes_get_no_pattern(self):
        """All other weather codes get no pattern (static)."""
        patterns_cfg = {}
        for code in [0, 1, 45, 48, 71, 73, 75, 77, 85, 86, 95, 96, 99, 100]:
            pattern = weather_sync.get_pattern_for_code(code, patterns_cfg)
            self.assertIsNone(pattern)

    def test_custom_pattern_config(self):
        """Custom pattern config overrides defaults."""
        custom = {
            "cloudy": {
                "type": "wave",
                "color1": "#ff0000",
                "color2": "#00ff00",
                "period": 5.0,
                "brightness": 60,
                "phase_offset": 0.0,
            }
        }
        pattern = weather_sync.get_pattern_for_code(2, custom)
        self.assertEqual(pattern["type"], "wave")
        self.assertEqual(pattern["color1"], "#ff0000")
        self.assertEqual(pattern["brightness"], 60)


class TestPatternLoop(StateDirMixin, unittest.TestCase):
    """Test the pattern animation loop."""

    def _make_config(self, patterns_enabled=True, frame_interval=1.0):
        return {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "weather": {
                "latitude": 51.5,
                "longitude": -0.1,
                "brightness": 80,
                "patterns_enabled": patterns_enabled,
                "frame_interval": frame_interval,
            },
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_pattern_sends_frames(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Pattern mode sends frames at frame_interval."""
        mock_time.return_value = 1000.0
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 61,  # rain
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)

        # Exit after 3 sleep calls
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            mock_time.return_value += 1.0  # advance time
            if sleep_count[0] >= 3:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Should have sent multiple frames (at least 2 color calls)
        self.assertGreaterEqual(mock_color.call_count, 2)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_pattern_blocked_by_signal(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Pattern sends nothing while signal is active."""
        import arbiter
        mock_time.return_value = 1000.0
        (arbiter.STATE_DIR / "saved_state.json").write_text("[]")

        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 61,
            "is_day": 1,
        }
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Should NOT have sent any frames
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_pattern_resumes_after_signal(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Pattern resumes after signal clears."""
        import arbiter
        mock_time.return_value = 1000.0

        # Start with signal active
        (arbiter.STATE_DIR / "saved_state.json").write_text("[]")

        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 61,
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)

        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            mock_time.return_value += 1.0
            if sleep_count[0] == 1:
                # Clear signal after first blocked iteration
                (arbiter.STATE_DIR / "saved_state.json").unlink()
            elif sleep_count[0] >= 3:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Should have sent frames after signal cleared
        self.assertGreater(mock_color.call_count, 0)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_pattern_brightness_capped(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Pattern brightness never exceeds max_brightness (80)."""
        mock_time.return_value = 1000.0
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 61,
            "is_day": 1,
        }
        config = self._make_config()
        config["max_brightness"] = 80

        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            mock_time.return_value += 1.0
            if sleep_count[0] >= 2:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Check all brightness calls are <= 80
        for call in mock_brightness.call_args_list:
            self.assertLessEqual(call[0][1], 80)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_patterns_disabled_uses_static(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """When patterns_enabled is false, use static color."""
        mock_time.return_value = 1000.0
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 61,  # rain (would normally be animated)
            "is_day": 1,
        }
        config = self._make_config(patterns_enabled=False)

        weather_sync.run(config, once=True)

        # Should have sent static rain color #1e88e5 = (30, 136, 229) to both devices
        self.assertEqual(mock_color.call_count, 2)
        # Check first device got the right color
        first_call = mock_color.call_args_list[0]
        self.assertEqual(first_call[0], ("192.168.1.50", 30, 136, 229))


class TestPatternFetchInterval(StateDirMixin, unittest.TestCase):
    """Test that weather is fetched every `interval` seconds, not every frame."""

    def _make_config(self, patterns_enabled=True, frame_interval=1.0):
        return {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "weather": {
                "latitude": 51.5,
                "longitude": -0.1,
                "brightness": 80,
                "patterns_enabled": patterns_enabled,
                "frame_interval": frame_interval,
            },
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_pattern_mode_fetches_once_per_interval(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """In pattern mode, fetch_weather is called once per interval, not per frame."""
        mock_time.return_value = 1000.0
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 61,  # rain
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)

        # Simulate 60 frames (60 seconds)
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            mock_time.return_value += 1.0  # advance 1 second per frame
            if sleep_count[0] >= 60:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Should have fetched weather exactly once (at the start)
        self.assertEqual(mock_fetch.call_count, 1)
        # Should have sent many frames
        self.assertGreater(mock_color.call_count, 10)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_pattern_mode_refetches_after_interval(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """After interval elapses, weather is fetched again."""
        mock_time.return_value = 1000.0
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 61,  # rain
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)

        # Simulate frames until interval (900s) elapses, then a few more
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            mock_time.return_value += 1.0
            if sleep_count[0] >= 905:  # 900s + 5 extra frames
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Should have fetched weather twice: once at start, once after 900s
        self.assertEqual(mock_fetch.call_count, 2)


class TestPerStripBrightness(StateDirMixin, unittest.TestCase):
    """Test that brightness is tracked per strip, not shared."""

    def _make_config(self, patterns_enabled=True, frame_interval=1.0):
        return {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "weather": {
                "latitude": 51.5,
                "longitude": -0.1,
                "brightness": 80,
                "patterns_enabled": patterns_enabled,
                "frame_interval": frame_interval,
            },
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_both_strips_receive_brightness(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Both strips receive a brightness command in pattern mode."""
        mock_time.return_value = 1000.0
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 61,  # rain
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)

        # Run for 2 frames
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            mock_time.return_value += 1.0
            if sleep_count[0] >= 2:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Both strips should have received a brightness command
        brightness_ips = {call[0][0] for call in mock_brightness.call_args_list}
        self.assertIn("192.168.1.50", brightness_ips)
        self.assertIn("192.168.1.51", brightness_ips)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_both_strips_receive_brightness_static(self, mock_brightness, mock_color, mock_fetch):
        """Both strips receive a brightness command in static mode."""
        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "weather": {
                "latitude": 51.5,
                "longitude": -0.1,
                "brightness": 50,
                "patterns_enabled": False,
            },
        }

        weather_sync.run(config, once=True)

        # Both strips should have received a brightness command
        brightness_ips = {call[0][0] for call in mock_brightness.call_args_list}
        self.assertIn("192.168.1.50", brightness_ips)
        self.assertIn("192.168.1.51", brightness_ips)


class TestFrameErrorRateLimit(StateDirMixin, unittest.TestCase):
    """Test that frame send errors are rate-limited to one per 60 seconds."""

    def _make_config(self, patterns_enabled=True, frame_interval=1.0):
        return {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "weather": {
                "latitude": 51.5,
                "longitude": -0.1,
                "brightness": 80,
                "patterns_enabled": patterns_enabled,
                "frame_interval": frame_interval,
            },
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_frame_errors_rate_limited(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """10 consecutive frame errors within 60s produce at most one error log."""
        mock_time.return_value = 1000.0
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 61,  # rain
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)

        # Make govee.color fail every time
        mock_color.side_effect = OSError("network down")

        # Run for 10 frames
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            mock_time.return_value += 1.0
            if sleep_count[0] >= 10:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        with self.assertLogs("weather_sync", "ERROR") as cm:
            try:
                weather_sync.run(config, once=False, interval=900)
            except KeyboardInterrupt:
                pass

        # Count error log lines about frame send failures
        frame_error_logs = [r for r in cm.records if "Failed to send to lights" in r.getMessage()]
        # Should be at most 1 (rate-limited to one per 60s)
        self.assertLessEqual(len(frame_error_logs), 1)


if __name__ == "__main__":
    unittest.main()
