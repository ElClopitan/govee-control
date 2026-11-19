#!/usr/bin/env python3
"""Weather-synced lighting via Open-Meteo API.

Fetches current weather for a configured location and sets Govee lights
to a colour that reflects the conditions. Uses the free, keyless
Open-Meteo API.

Config keys (in config.json):
  "weather": {
    "latitude": 51.5074,
    "longitude": -0.1278,
    "brightness": 50
  }

Colour mapping (WMO weather codes):
  0-1   clear: day=warm yellow (#ffd27f), night=deep blue (#1a237e)
  2-3   partly/mostly cloudy: grey (#b0bec5)
  45-48 fog: light grey (#cfd8dc)
  51-67 drizzle/rain: blue (#1e88e5)
  71-77 snow: pale blue (#e3f2fd)
  80-82 showers: blue (#1e88e5)
  85-86 snow showers: pale blue (#e3f2fd)
  95-99 thunderstorm: purple (#7b1fa2)
  other unknown: white (#ffffff)
"""

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import arbiter
import govee

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# When blocked by signal/game priority, poll at least this often (seconds)
# so weather takes over quickly after a game ends or signal clears.
BLOCKED_POLL_SECONDS = 10


def fetch_weather(lat, lon):
    """Fetch current weather from Open-Meteo API.

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        dict with 'temperature_2m', 'weather_code', 'is_day' keys
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code,is_day",
    }
    query = urllib.parse.urlencode(params)
    url = f"{OPEN_METEO_URL}?{query}"

    logger.info("Fetching weather from Open-Meteo for (%s, %s)", lat, lon)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    current = data["current"]
    return {
        "temperature_2m": current["temperature_2m"],
        "weather_code": current["weather_code"],
        "is_day": current["is_day"],
    }


def weather_to_color(code, temp_c, is_day):
    """Map weather conditions to a colour hex string.

    Args:
        code: WMO weather code (int)
        temp_c: Temperature in Celsius (float)
        is_day: 1 if daytime, 0 if night (int)

    Returns:
        Hex colour string like '#ffd27f'
    """
    if code <= 1:
        # Clear sky
        if is_day:
            return "#ffd27f"  # warm yellow
        else:
            return "#1a237e"  # deep blue
    elif code <= 3:
        # Partly/mostly cloudy
        return "#b0bec5"
    elif code <= 48:
        # Fog
        return "#cfd8dc"
    elif code <= 67:
        # Drizzle/rain
        return "#1e88e5"
    elif code <= 77:
        # Snow
        return "#e3f2fd"
    elif code <= 82:
        # Showers
        return "#1e88e5"
    elif code <= 86:
        # Snow showers
        return "#e3f2fd"
    elif code <= 99:
        # Thunderstorm
        return "#7b1fa2"
    else:
        # Unknown
        return "#ffffff"


def run(config, once=False, interval=900, dry_run=False):
    """Run the weather sync loop.

    Args:
        config: Loaded config dict
        once: If True, run once and exit
        interval: Seconds between updates (default 900 = 15 min)
        dry_run: If True, print instead of sending to lights
    """
    weather_cfg = config.get("weather", {})
    lat = weather_cfg.get("latitude", 0.0)
    lon = weather_cfg.get("longitude", 0.0)
    brightness = weather_cfg.get("brightness", 50)

    # Validate location
    if lat == 0.0 and lon == 0.0:
        logger.error("Weather location not configured (latitude and longitude are both 0.0). "
                     "Set 'weather.latitude' and 'weather.longitude' in your config.")
        sys.exit(2)

    devices = config.get("devices", [])
    if not devices:
        logger.error("No devices configured")
        sys.exit(1)

    last_color = None
    priority_was_active = False

    while True:
        # Check signal/game priority
        if arbiter.signal_active() or arbiter.game_active():
            if not priority_was_active:
                logger.info("skipped: signal/game active")
            priority_was_active = True
            # Reset last_color so the first successful pass after the block
            # always sends, even if the colour hasn't changed.
            last_color = None
            if once:
                break
            time.sleep(min(interval, BLOCKED_POLL_SECONDS))
            continue

        priority_was_active = False

        try:
            weather = fetch_weather(lat, lon)
        except (OSError, ValueError, KeyError) as e:
            logger.error("Failed to fetch weather: %s", e)
            if once:
                sys.exit(1)
            time.sleep(interval)
            continue

        code = weather["weather_code"]
        if code is None:
            logger.warning("weather_code is null; skipping this iteration")
            if once:
                sys.exit(1)
            time.sleep(interval)
            continue

        temp = weather["temperature_2m"]
        if temp is None:
            logger.warning("temperature_2m is null; skipping this iteration")
            if once:
                sys.exit(1)
            time.sleep(interval)
            continue

        is_day = weather["is_day"]

        color_hex = weather_to_color(code, temp, is_day)
        logger.info("Weather: code=%d temp=%.1f°C day=%d -> color=%s",
                    code, temp, is_day, color_hex)

        # Re-check priority just before sending (race condition fix).
        # A signal or game could have become active during the weather fetch.
        if arbiter.signal_active() or arbiter.game_active():
            logger.info("skipped: signal/game became active during fetch")
            priority_was_active = True
            last_color = None
            if once:
                break
            time.sleep(min(interval, BLOCKED_POLL_SECONDS))
            continue

        if color_hex != last_color or dry_run:
            r, g, b = govee.parse_color(color_hex)
            try:
                for dev in devices:
                    ip = dev["ip"]
                    if dry_run:
                        logger.info("[dry-run] Would set %s to %s (brightness %d)",
                                    ip, color_hex, brightness)
                    else:
                        govee.color(ip, r, g, b)
                        govee.brightness(ip, brightness)
                        logger.info("Set %s to %s (brightness %d)", ip, color_hex, brightness)
            except OSError as e:
                logger.error("Failed to send to lights: %s", e)
                # Don't update last_color so we retry next iteration
            else:
                last_color = color_hex

        if once:
            break

        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(
        description="Weather-synced Govee lighting via Open-Meteo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python weather_sync.py --once --dry-run
  python weather_sync.py --interval 600
  python weather_sync.py --config myconfig.json
""",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (useful for testing)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=900,
        help="Seconds between weather checks (default: 900 = 15 min)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without sending",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.json"),
        help="Path to config.json",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        config = govee.load_config(args.config)
    except FileNotFoundError:
        logger.error("Config not found: %s", args.config)
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in config: %s", e)
        sys.exit(1)

    run(config, once=args.once, interval=args.interval, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
