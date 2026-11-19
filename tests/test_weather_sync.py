"""Tests for weather_sync.py."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
import weather_sync
import govee


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


class TestRunOnce(unittest.TestCase):
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
        """Rain uses blue."""
        mock_fetch.return_value = {
            "temperature_2m": 12.0,
            "weather_code": 61,
            "is_day": 1,
        }
        config = self._make_config()

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
            "weather": {"latitude": 51.5, "longitude": -0.1, "brightness": 50},
        }

        weather_sync.run(config, once=True)

        self.assertEqual(mock_color.call_count, 2)
        self.assertEqual(mock_brightness.call_count, 2)


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


class TestNetworkError(unittest.TestCase):
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


class TestPriority(unittest.TestCase):
    """Test that weather sync respects signal/game priority."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmpdir = tempfile.mkdtemp()
        self.state_dir = Path(self.tmpdir)
        import arbiter
        arbiter.STATE_DIR = self.state_dir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

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


if __name__ == "__main__":
    unittest.main()
