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
        """Partly cloudy day -> blue-grey."""
        self.assertEqual(weather_sync.weather_to_color(2, 20.0, 1), "#546e7a")
        self.assertEqual(weather_sync.weather_to_color(3, 20.0, 1), "#546e7a")

    def test_partly_cloudy_night(self):
        """Partly cloudy night -> dark blue-grey."""
        self.assertEqual(weather_sync.weather_to_color(2, 15.0, 0), "#37474f")
        self.assertEqual(weather_sync.weather_to_color(3, 15.0, 0), "#37474f")

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

    def test_night_colors(self):
        """Night mode colors for each weather code group."""
        # Clear night
        self.assertEqual(weather_sync.weather_to_color(0, 15.0, 0), "#1a237e")
        # Cloudy night
        self.assertEqual(weather_sync.weather_to_color(2, 15.0, 0), "#37474f")
        # Fog night
        self.assertEqual(weather_sync.weather_to_color(45, 10.0, 0), "#455a64")
        # Rain night
        self.assertEqual(weather_sync.weather_to_color(61, 12.0, 0), "#0d47a1")
        # Snow night
        self.assertEqual(weather_sync.weather_to_color(71, -2.0, 0), "#3949ab")
        # Showers night
        self.assertEqual(weather_sync.weather_to_color(80, 18.0, 0), "#0d47a1")
        # Snow showers night
        self.assertEqual(weather_sync.weather_to_color(85, -1.0, 0), "#3949ab")
        # Thunderstorm night (same as day)
        self.assertEqual(weather_sync.weather_to_color(95, 22.0, 0), "#7b1fa2")
        # Unknown night
        self.assertEqual(weather_sync.weather_to_color(100, 20.0, 0), "#37474f")


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

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

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

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_night_brightness_default(self, mock_brightness, mock_color, mock_fetch):
        """Night mode uses default night_brightness of 30."""
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 2,
            "is_day": 0,
        }
        config = self._make_config(brightness=50)
        config["weather"]["patterns_enabled"] = False

        weather_sync.run(config, once=True)

        # Night brightness should be 30 (default)
        mock_brightness.assert_called_with("192.168.1.50", 30)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    def test_night_brightness_configured(self, mock_brightness, mock_color, mock_fetch):
        """Night mode uses configured night_brightness."""
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 2,
            "is_day": 0,
        }
        config = self._make_config(brightness=50)
        config["weather"]["patterns_enabled"] = False
        config["weather"]["night_brightness"] = 40

        weather_sync.run(config, once=True)

        # Night brightness should be 40 (configured)
        mock_brightness.assert_called_with("192.168.1.50", 40)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_day_night_transition_switches_pattern(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """When is_day changes, pattern and brightness switch."""
        mock_time.return_value = 1000.0

        # First fetch: day, cloudy
        # Second fetch: night, cloudy (same code, different is_day)
        fetch_count = [0]
        def fetch_side_effect(*args, **kwargs):
            fetch_count[0] += 1
            if fetch_count[0] == 1:
                return {"temperature_2m": 20.0, "weather_code": 2, "is_day": 1}
            else:
                return {"temperature_2m": 15.0, "weather_code": 2, "is_day": 0}

        mock_fetch.side_effect = fetch_side_effect

        config = self._make_config(brightness=50)
        config["weather"]["patterns_enabled"] = False
        config["weather"]["fetch_on_the_hour"] = False  # Use interval-based mode

        # Advance time past interval on second sleep
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            if sleep_count[0] == 1:
                mock_time.return_value = 2000.0  # advance past 900s interval
            if sleep_count[0] >= 2:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Should have fetched twice
        self.assertEqual(mock_fetch.call_count, 2)

        # First call: day color #546e7a, brightness 50
        # Second call: night color #37474f, brightness 30
        self.assertEqual(mock_color.call_count, 2)
        self.assertEqual(mock_color.call_args_list[0][0], ("192.168.1.50", 84, 110, 122))  # #546e7a
        self.assertEqual(mock_color.call_args_list[1][0], ("192.168.1.50", 55, 71, 79))  # #37474f

        # Brightness should switch from 50 to 30
        self.assertEqual(mock_brightness.call_count, 2)
        self.assertEqual(mock_brightness.call_args_list[0][0], ("192.168.1.50", 50))
        self.assertEqual(mock_brightness.call_args_list[1][0], ("192.168.1.50", 30))


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

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

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

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

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

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

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

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

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
        for code in [0, 1, 45, 48, 71, 73, 75, 77, 85, 86, 100]:
            pattern = weather_sync.get_pattern_for_code(code, patterns_cfg)
            self.assertIsNone(pattern)

    def test_thunderstorm_codes_get_pattern(self):
        """Weather codes 95-99 get thunderstorm pattern."""
        patterns_cfg = {}
        for code in [95, 96, 99]:
            pattern = weather_sync.get_pattern_for_code(code, patterns_cfg)
            self.assertIsNotNone(pattern)
            self.assertEqual(pattern["type"], "thunderstorm")

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

    def test_cloudy_day_pattern_colors(self):
        """Day cloudy pattern uses #546e7a/#90a4ae."""
        pattern = weather_sync.get_pattern_for_code(2, {}, is_day=1)
        self.assertEqual(pattern["color1"], "#546e7a")
        self.assertEqual(pattern["color2"], "#90a4ae")

    def test_cloudy_night_pattern_colors(self):
        """Night cloudy pattern uses #37474f/#5c6bc0."""
        pattern = weather_sync.get_pattern_for_code(2, {}, is_day=0)
        self.assertEqual(pattern["color1"], "#37474f")
        self.assertEqual(pattern["color2"], "#5c6bc0")

    def test_cloudy_night_pattern_override(self):
        """patterns_cfg cloudy_night override is used at night."""
        custom = {
            "cloudy_night": {
                "type": "drift",
                "color1": "#ff0000",
                "color2": "#00ff00",
                "period": 10.0,
                "brightness": 50,
                "phase_offset": 0.0,
            }
        }
        pattern = weather_sync.get_pattern_for_code(2, custom, is_day=0)
        self.assertEqual(pattern["color1"], "#ff0000")
        self.assertEqual(pattern["color2"], "#00ff00")


class TestPatternLoop(StateDirMixin, unittest.TestCase):
    """Test the pattern animation loop."""

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

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

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

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
        """After interval elapses, weather is fetched again (interval-based mode)."""
        mock_time.return_value = 1000.0
        mock_fetch.return_value = {
            "temperature_2m": 15.0,
            "weather_code": 61,  # rain
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)
        config["weather"]["fetch_on_the_hour"] = False  # Use interval-based mode

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

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

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

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

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


class TestThunderstormPattern(StateDirMixin, unittest.TestCase):
    """Test the thunderstorm pattern with lightning flashes."""

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

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
    def test_thunderstorm_pattern_selected(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Thunderstorm weather code selects thunderstorm pattern."""
        mock_fetch.return_value = {
            "temperature_2m": 22.0,
            "weather_code": 95,  # thunderstorm
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)

        # Exit after 2 sleep calls
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            if sleep_count[0] >= 2:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Should have sent frames
        self.assertGreater(mock_color.call_count, 0)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_flash_sends_100_then_returns_to_80(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """A flash sends brightness 100 then returns to <= 80."""
        import random
        mock_fetch.return_value = {
            "temperature_2m": 22.0,
            "weather_code": 95,
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)

        # Seed the RNG for deterministic behavior
        rng = random.Random(42)

        # Use a controllable time function
        current_time = [1000.0]
        def time_fn():
            return current_time[0]

        # Exit after flash (advance time to trigger flash)
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            current_time[0] += seconds
            # Advance time to trigger flash after a few frames
            if sleep_count[0] >= 3:
                current_time[0] = 1015.0  # Force flash time (well past 6s minimum)
            if sleep_count[0] >= 15:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900, rng=rng, time_fn=time_fn)
        except KeyboardInterrupt:
            pass

        # Check that brightness 100 was sent (flash)
        brightness_values = [call[0][1] for call in mock_brightness.call_args_list]
        self.assertIn(100, brightness_values, "Flash should send brightness 100")

        # Check that after the flash, brightness returns to <= 80
        # Find the last flash brightness value and check the next one
        last_flash_index = -1
        for i, b in enumerate(brightness_values):
            if b == 100:
                last_flash_index = i
        if last_flash_index + 1 < len(brightness_values):
            self.assertLessEqual(brightness_values[last_flash_index + 1], 80,
                                "After flash, brightness should return to <= 80")

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_no_flash_when_arbiter_blocks(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """No flash when signal/game has priority."""
        import arbiter
        import random
        mock_fetch.return_value = {
            "temperature_2m": 22.0,
            "weather_code": 95,
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)

        # Activate signal to block flash
        (arbiter.STATE_DIR / "saved_state.json").write_text("[]")

        # Seed the RNG
        rng = random.Random(42)

        weather_sync.run(config, once=True, rng=rng)

        # Should NOT have sent any frames (signal active)
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_non_flash_frames_never_exceed_80(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Non-flash frames never exceed brightness 80."""
        import random
        mock_fetch.return_value = {
            "temperature_2m": 22.0,
            "weather_code": 95,
            "is_day": 1,
        }
        config = self._make_config(frame_interval=1.0)
        config["max_brightness"] = 80

        # Seed the RNG
        rng = random.Random(42)

        # Exit after a few frames
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            if sleep_count[0] >= 5:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900, rng=rng)
        except KeyboardInterrupt:
            pass

        # All brightness values should be <= 80 (no flash triggered in this test)
        brightness_values = [call[0][1] for call in mock_brightness.call_args_list]
        for b in brightness_values:
            self.assertLessEqual(b, 80, f"Non-flash brightness {b} exceeds 80")


class TestThunderstormDoubleFlash(StateDirMixin, unittest.TestCase):
    """Test thunderstorm double-flash sequence and arbiter interaction."""

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

    def _make_config(self):
        return {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "weather": {
                "latitude": 51.5,
                "longitude": -0.1,
                "brightness": 80,
                "patterns_enabled": True,
                "frame_interval": 1.0,
            },
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_double_flash_sends_base_frame_in_gap(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Double flash: flash 100 -> base <= 80 -> flash 100 -> base <= 80.

        Uses a seeded RNG where random() < 0.3 forces the double flash.
        """
        import random
        import arbiter

        mock_fetch.return_value = {
            "temperature_2m": 22.0,
            "weather_code": 95,
            "is_day": 1,
        }
        config = self._make_config()

        # Seed RNG so random() < 0.3 triggers double flash
        # random.Random(42).random() = 0.639... (not < 0.3)
        # We need to find a seed where random() < 0.3
        # random.Random(1).random() = 0.134... (yes!)
        rng = random.Random(1)

        # Controllable time
        current_time = [1000.0]
        def time_fn():
            return current_time[0]

        # Advance time to trigger flash, then exit
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            current_time[0] += seconds
            if sleep_count[0] == 1:
                # After first frame, advance to trigger flash
                current_time[0] = 1015.0
            if sleep_count[0] >= 10:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900, rng=rng, time_fn=time_fn)
        except KeyboardInterrupt:
            pass

        # Extract brightness calls for the first device
        brightness_calls = [
            (call[0][0], call[0][1])
            for call in mock_brightness.call_args_list
            if call[0][0] == "192.168.1.50"
        ]

        # Find flash brightness values (100)
        flash_indices = [i for i, (ip, b) in enumerate(brightness_calls) if b == 100]

        # Should have at least 2 flashes (double flash)
        self.assertGreaterEqual(len(flash_indices), 2,
                                f"Expected at least 2 flashes, got {len(flash_indices)}")

        # Check that between the two flashes, there's a base frame <= 80
        first_flash = flash_indices[0]
        second_flash = flash_indices[1]

        # There should be a brightness call between the two flashes that is <= 80
        between_calls = brightness_calls[first_flash + 1:second_flash]
        self.assertGreater(len(between_calls), 0,
                           "Expected base frame between flashes")

        # The last call before the second flash should be <= 80 (base frame)
        last_before_second = between_calls[-1]
        self.assertLessEqual(last_before_second[1], 80,
                             f"Expected base frame <= 80 between flashes, got {last_before_second[1]}")

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_flash_intervals_within_range(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Across >= 50 flashes, every gap is within [6, 20] seconds."""
        import random

        mock_fetch.return_value = {
            "temperature_2m": 22.0,
            "weather_code": 95,
            "is_day": 1,
        }
        config = self._make_config()

        # Use a seeded RNG for reproducibility
        rng = random.Random(42)

        # Track intervals by patching rng.uniform
        intervals = []
        original_uniform = rng.uniform
        def uniform_side_effect(a, b):
            result = original_uniform(a, b)
            intervals.append(result)
            return result
        rng.uniform = uniform_side_effect

        current_time = [1000.0]
        def time_fn():
            return current_time[0]

        # Run for enough time to get 50+ flashes
        # With flash_every [6, 20], average is 13s, so 50 flashes ~ 650s
        # Use 800 to be safe
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            current_time[0] += seconds
            if sleep_count[0] >= 800:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900, rng=rng, time_fn=time_fn)
        except KeyboardInterrupt:
            pass

        # Should have at least 50 intervals (one per flash)
        self.assertGreaterEqual(len(intervals), 50,
                                f"Expected >= 50 flash intervals, got {len(intervals)}")

        # Check all intervals are within [6, 20]
        for i, interval in enumerate(intervals):
            self.assertGreaterEqual(interval, 6.0,
                                    f"Flash interval {interval} < 6.0 at flash {i}")
            self.assertLessEqual(interval, 20.0,
                                 f"Flash interval {interval} > 20.0 at flash {i}")

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_arbiter_blocks_second_flash(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """If arbiter activates between flashes, second flash is skipped."""
        import random
        import arbiter

        mock_fetch.return_value = {
            "temperature_2m": 22.0,
            "weather_code": 95,
            "is_day": 1,
        }
        config = self._make_config()

        # Seed RNG so random() < 0.3 triggers double flash
        rng = random.Random(1)

        # Controllable time
        current_time = [1000.0]
        def time_fn():
            return current_time[0]

        # Activate signal during the double-flash gap
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            current_time[0] += seconds
            if sleep_count[0] == 1:
                # After first frame, advance to trigger flash
                current_time[0] = 1015.0
            elif sleep_count[0] == 2:
                # This is the flash_duration sleep after first flash
                # Activate signal before the double-flash gap
                (arbiter.STATE_DIR / "saved_state.json").write_text("[]")
            elif sleep_count[0] == 3:
                # This is the 0.12s gap sleep
                # Signal is active, second flash should be skipped
                pass
            if sleep_count[0] >= 10:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900, rng=rng, time_fn=time_fn)
        except KeyboardInterrupt:
            pass

        # Count flash brightness calls (100)
        flash_calls = [
            call for call in mock_brightness.call_args_list
            if call[0][1] == 100
        ]

        # Should have exactly 1 flash (first flash only, second blocked)
        self.assertEqual(len(flash_calls), 1,
                         f"Expected 1 flash (second blocked), got {len(flash_calls)}")


class TestThunderstormSignalRace(StateDirMixin, unittest.TestCase):
    """Test that signal/game raised during thunderstorm flash stops all further writes."""

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

    def _make_config(self):
        return {
            "devices": [
                {"name": "left", "ip": "192.168.1.50"},
                {"name": "right", "ip": "192.168.1.51"},
            ],
            "weather": {
                "latitude": 51.5,
                "longitude": -0.1,
                "brightness": 80,
                "patterns_enabled": True,
                "frame_interval": 1.0,
            },
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_signal_during_flash_stops_writes(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Signal raised during flash_duration sleep: no writes after signal."""
        import random
        import arbiter

        mock_fetch.return_value = {
            "temperature_2m": 22.0,
            "weather_code": 95,
            "is_day": 1,
        }
        config = self._make_config()

        # Seed RNG so random() < 0.3 triggers double flash
        rng = random.Random(1)

        # Controllable time
        current_time = [1000.0]
        def time_fn():
            return current_time[0]

        # Track when signal is raised and calls after it
        signal_raised = [False]
        calls_after_signal = [0]

        def color_side_effect(*args, **kwargs):
            if signal_raised[0]:
                calls_after_signal[0] += 1
            # Don't actually call the real function

        def brightness_side_effect(*args, **kwargs):
            if signal_raised[0]:
                calls_after_signal[0] += 1
            # Don't actually call the real function

        mock_color.side_effect = color_side_effect
        mock_brightness.side_effect = brightness_side_effect

        # Activate signal during the flash_duration sleep (2nd sleep call)
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            current_time[0] += seconds
            if sleep_count[0] == 1:
                # After first frame, advance to trigger flash
                current_time[0] = 1015.0
            elif sleep_count[0] == 2:
                # This is the flash_duration sleep after first flash
                # Raise signal here
                (arbiter.STATE_DIR / "saved_state.json").write_text("[]")
                signal_raised[0] = True
            if sleep_count[0] >= 10:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900, rng=rng, time_fn=time_fn)
        except KeyboardInterrupt:
            pass

        # Verify signal was raised
        self.assertTrue(signal_raised[0])

        # No govee calls should happen after the signal is raised
        self.assertEqual(calls_after_signal[0], 0,
                         f"Expected 0 calls after signal, got {calls_after_signal[0]}")

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_signal_during_double_flash_gap_stops_writes(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Signal raised during double-flash gap: no writes after signal."""
        import random
        import arbiter

        mock_fetch.return_value = {
            "temperature_2m": 22.0,
            "weather_code": 95,
            "is_day": 1,
        }
        config = self._make_config()

        # Seed RNG so random() < 0.3 triggers double flash
        rng = random.Random(1)

        # Controllable time
        current_time = [1000.0]
        def time_fn():
            return current_time[0]

        # Activate signal during the 0.12s gap sleep (3rd sleep call)
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            current_time[0] += seconds
            if sleep_count[0] == 1:
                # After first frame, advance to trigger flash
                current_time[0] = 1015.0
            elif sleep_count[0] == 3:
                # This is the 0.12s gap sleep
                # Raise signal here
                (arbiter.STATE_DIR / "saved_state.json").write_text("[]")
            if sleep_count[0] >= 10:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900, rng=rng, time_fn=time_fn)
        except KeyboardInterrupt:
            pass

        # Count flash brightness calls (100)
        flash_calls = [
            call for call in mock_brightness.call_args_list
            if call[0][1] == 100
        ]
        # Should have exactly 1 flash (first flash only, second blocked)
        self.assertEqual(len(flash_calls), 1,
                         f"Expected 1 flash, got {len(flash_calls)}")

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    def test_signal_before_first_flash_recheck(self, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """Signal active before first flash re-check: no flash, no base frame."""
        import random
        import arbiter

        mock_fetch.return_value = {
            "temperature_2m": 22.0,
            "weather_code": 95,
            "is_day": 1,
        }
        config = self._make_config()

        # Seed RNG
        rng = random.Random(1)

        # Controllable time
        current_time = [1000.0]
        def time_fn():
            return current_time[0]

        # Patch arbiter.weather_blocked to return True from the 3rd call onwards
        # (first two are the top-of-loop and pre-send checks)
        original_weather_blocked = arbiter.weather_blocked
        call_count = [0]
        def weather_blocked_side_effect():
            call_count[0] += 1
            if call_count[0] >= 3:
                # This is the re-check before the first flash (and subsequent checks)
                return True
            return original_weather_blocked()

        with mock.patch.object(arbiter, "weather_blocked", side_effect=weather_blocked_side_effect):
            # Advance time to trigger flash
            sleep_count = [0]
            def sleep_side_effect(seconds):
                sleep_count[0] += 1
                current_time[0] += seconds
                if sleep_count[0] == 1:
                    current_time[0] = 1015.0
                if sleep_count[0] >= 5:
                    raise KeyboardInterrupt()

            mock_sleep.side_effect = sleep_side_effect

            try:
                weather_sync.run(config, once=False, interval=900, rng=rng, time_fn=time_fn)
            except KeyboardInterrupt:
                pass

        # Should have no flash calls (blocked before flash)
        flash_calls = [
            call for call in mock_brightness.call_args_list
            if call[0][1] == 100
        ]
        self.assertEqual(len(flash_calls), 0,
                         f"Expected 0 flashes, got {len(flash_calls)}")


class TestLogFileArgument(unittest.TestCase):
    """Test the --log-file argument with size rotation."""

    def test_log_file_creates_file(self):
        """Running with --log-file creates the log file."""
        import tempfile
        import os
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            config_path = os.path.join(tmpdir, "config.json")

            # Create a minimal config
            config = {
                "devices": [{"name": "test", "ip": "192.168.1.1"}],
                "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
            }
            with open(config_path, "w") as f:
                json.dump(config, f)

            # Mock fetch_weather to return clear sky
            with mock.patch("weather_sync.fetch_weather") as mock_fetch:
                mock_fetch.return_value = {
                    "temperature_2m": 20.0,
                    "weather_code": 0,
                    "is_day": 1,
                }

                # Run with --log-file and --once
                with mock.patch("sys.argv", [
                    "weather_sync.py",
                    "--once",
                    "--dry-run",
                    "--config", config_path,
                    "--log-file", log_path,
                ]):
                    weather_sync.main()

            # Close logger handlers to release file handles (Windows)
            for handler in weather_sync.logger.handlers[:]:
                handler.close()
                weather_sync.logger.removeHandler(handler)

            # Log file should exist and contain log entries
            self.assertTrue(os.path.exists(log_path))
            with open(log_path, "r") as f:
                content = f.read()
            self.assertIn("INFO", content)

    def test_no_log_file_without_argument(self):
        """Without --log-file, no log file is created."""
        import tempfile
        import os
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            config_path = os.path.join(tmpdir, "config.json")

            # Create a minimal config
            config = {
                "devices": [{"name": "test", "ip": "192.168.1.1"}],
                "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
            }
            with open(config_path, "w") as f:
                json.dump(config, f)

            # Mock fetch_weather to return clear sky
            with mock.patch("weather_sync.fetch_weather") as mock_fetch:
                mock_fetch.return_value = {
                    "temperature_2m": 20.0,
                    "weather_code": 0,
                    "is_day": 1,
                }

                # Run without --log-file
                with mock.patch("sys.argv", [
                    "weather_sync.py",
                    "--once",
                    "--dry-run",
                    "--config", config_path,
                ]):
                    weather_sync.main()

            # Log file should NOT exist
            self.assertFalse(os.path.exists(log_path))


class TestNextHourBoundary(unittest.TestCase):
    """Test the next_hour_boundary helper function."""

    def test_exact_hour(self):
        """At exactly HH:00:00, next boundary is HH+1:00:00."""
        # Use a fixed timestamp: 2026-01-15 10:00:00 UTC
        import datetime
        dt = datetime.datetime(2026, 1, 15, 10, 0, 0, tzinfo=datetime.timezone.utc)
        ts = dt.timestamp()
        result = weather_sync.next_hour_boundary(ts)
        expected_dt = datetime.datetime(2026, 1, 15, 11, 0, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(result, expected_dt.timestamp())

    def test_one_second_after_hour(self):
        """At HH:00:01, next boundary is HH+1:00:00."""
        import datetime
        dt = datetime.datetime(2026, 1, 15, 10, 0, 1, tzinfo=datetime.timezone.utc)
        ts = dt.timestamp()
        result = weather_sync.next_hour_boundary(ts)
        expected_dt = datetime.datetime(2026, 1, 15, 11, 0, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(result, expected_dt.timestamp())

    def test_one_second_before_hour(self):
        """At HH:59:59, next boundary is HH+1:00:00."""
        import datetime
        dt = datetime.datetime(2026, 1, 15, 10, 59, 59, tzinfo=datetime.timezone.utc)
        ts = dt.timestamp()
        result = weather_sync.next_hour_boundary(ts)
        expected_dt = datetime.datetime(2026, 1, 15, 11, 0, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(result, expected_dt.timestamp())


class TestFetchOnTheHour(StateDirMixin, unittest.TestCase):
    """Test the fetch_on_the_hour feature."""

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

    def _make_config(self, fetch_on_the_hour=True, interval=900, patterns_enabled=False):
        return {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {
                "latitude": 51.5,
                "longitude": -0.1,
                "brightness": 50,
                "fetch_on_the_hour": fetch_on_the_hour,
                "patterns_enabled": patterns_enabled,
            },
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_fetch_at_top_of_hour(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """With fetch_on_the_hour=true, fetches at top of the hour, not before."""
        import datetime
        # Start at 10:20:00
        start_dt = datetime.datetime(2026, 1, 15, 10, 20, 0, tzinfo=datetime.timezone.utc)
        mock_time.return_value = start_dt.timestamp()

        # Record the time of each fetch
        fetch_times = []
        def fetch_side_effect(*args, **kwargs):
            fetch_times.append(mock_time.return_value)
            return {"temperature_2m": 20.0, "weather_code": 0, "is_day": 1}

        mock_fetch.side_effect = fetch_side_effect
        config = self._make_config(fetch_on_the_hour=True, interval=900)

        # Advance time to 10:59:59 - should not fetch again
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            if sleep_count[0] == 1:
                # After first fetch, advance to 10:59:59
                dt = datetime.datetime(2026, 1, 15, 10, 59, 59, tzinfo=datetime.timezone.utc)
                mock_time.return_value = dt.timestamp()
            elif sleep_count[0] == 2:
                # Advance to 11:00:00 - should trigger second fetch
                dt = datetime.datetime(2026, 1, 15, 11, 0, 0, tzinfo=datetime.timezone.utc)
                mock_time.return_value = dt.timestamp()
            elif sleep_count[0] >= 3:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Should have fetched twice: once at start, once at 11:00:00
        self.assertEqual(mock_fetch.call_count, 2)

        # Second fetch should be at 11:00:00, not before
        expected_second_fetch = datetime.datetime(2026, 1, 15, 11, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(fetch_times[1], expected_second_fetch)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_interval_based_fetching(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """With fetch_on_the_hour=false, fetches every interval seconds."""
        mock_time.return_value = 1000.0

        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config(fetch_on_the_hour=False, interval=900)

        # Advance time by 900 seconds - should trigger second fetch
        sleep_count = [0]
        def sleep_side_effect(seconds):
            sleep_count[0] += 1
            if sleep_count[0] == 1:
                mock_time.return_value = 1900.0  # 900 seconds later
            elif sleep_count[0] >= 2:
                raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Should have fetched twice: once at start, once after 900 seconds
        self.assertEqual(mock_fetch.call_count, 2)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("time.sleep")
    @mock.patch("time.time")
    def test_static_mode_sleep_until_next_hour(self, mock_time, mock_sleep, mock_brightness, mock_color, mock_fetch):
        """In static mode with fetch_on_the_hour, sleep until next hour boundary."""
        import datetime
        # Start at 10:50:00
        start_dt = datetime.datetime(2026, 1, 15, 10, 50, 0, tzinfo=datetime.timezone.utc)
        mock_time.return_value = start_dt.timestamp()

        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config(fetch_on_the_hour=True, interval=900, patterns_enabled=False)

        # First sleep should be <= 600 seconds (10 minutes to next hour)
        first_sleep = [None]
        def sleep_side_effect(seconds):
            if first_sleep[0] is None:
                first_sleep[0] = seconds
            raise KeyboardInterrupt()

        mock_sleep.side_effect = sleep_side_effect

        try:
            weather_sync.run(config, once=False, interval=900)
        except KeyboardInterrupt:
            pass

        # Sleep should be at most 600 seconds (10 minutes to 11:00:00)
        self.assertIsNotNone(first_sleep[0])
        self.assertLessEqual(first_sleep[0], 600.0)
        # And at least 1 second
        self.assertGreaterEqual(first_sleep[0], 1.0)


class TestMusicPriority(StateDirMixin, unittest.TestCase):
    """Test that weather sync yields to music sync."""

    def setUp(self):
        super().setUp()
        p = mock.patch("agent_signal.sweep_and_restore")
        p.start()
        self.addCleanup(p.stop)

    def _make_config(self):
        return {
            "devices": [{"name": "left", "ip": "192.168.1.50"}],
            "weather": {
                "latitude": 51.5074,
                "longitude": -0.1278,
                "brightness": 80,
            },
        }

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("arbiter.music_active", return_value=True)
    def test_music_active_skips_weather(self, mock_music, mock_brightness, mock_color, mock_fetch):
        """When music is active, weather sync should not send."""
        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Should NOT have sent any commands because music is active
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("arbiter.music_active", return_value=False)
    def test_music_inactive_allows_weather(self, mock_music, mock_brightness, mock_color, mock_fetch):
        """When music is not active, weather sync should send."""
        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Should have sent commands because music is not active
        self.assertGreater(mock_color.call_count, 0)

    @mock.patch("weather_sync.fetch_weather")
    @mock.patch("govee.color")
    @mock.patch("govee.brightness")
    @mock.patch("arbiter.signal_active", return_value=True)
    @mock.patch("arbiter.music_active", return_value=True)
    def test_signal_beats_music(self, mock_music, mock_signal, mock_brightness, mock_color, mock_fetch):
        """Signal should beat music (both active, signal wins)."""
        mock_fetch.return_value = {
            "temperature_2m": 20.0,
            "weather_code": 0,
            "is_day": 1,
        }
        config = self._make_config()

        weather_sync.run(config, once=True)

        # Should NOT have sent any commands because signal is active
        mock_color.assert_not_called()
        mock_brightness.assert_not_called()


if __name__ == "__main__":
    unittest.main()
