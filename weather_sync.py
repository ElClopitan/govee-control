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
  Day:
    0-1   clear: warm yellow (#ffd27f)
    2-3   partly/mostly cloudy: drift #546e7a <-> #90a4ae
    45-48 fog: light grey (#cfd8dc)
    51-67 drizzle/rain: wave #1e88e5 <-> #0d47a1
    71-77 snow: pale blue (#e3f2fd)
    80-82 showers: wave #1e88e5 <-> #0d47a1
    85-86 snow showers: pale blue (#e3f2fd)
    95-99 thunderstorm: pulse #4a148c <-> #7b1fa2 (brightness 60-80) with white flashes
    other unknown: white (#ffffff)
  Night (is_day=0):
    0-1   clear: deep blue (#1a237e)
    2-3   partly/mostly cloudy: drift #37474f <-> #5c6bc0
    45-48 fog: dark grey (#455a64)
    51-67 drizzle/rain: wave #0d47a1 <-> #1a237e
    71-77 snow: indigo (#3949ab)
    80-82 showers: wave #0d47a1 <-> #1a237e
    85-86 snow showers: indigo (#3949ab)
    95-99 thunderstorm: same as day (flashes keep flash_brightness)
    other unknown: dark grey (#37474f)
  Night brightness: weather.night_brightness (default 30), applied to all
  base frames and static colours at night. Thunderstorm flashes keep
  their own flash_brightness.
"""

import argparse
import json
import logging
import logging.handlers
import math
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import agent_signal
import arbiter
import govee

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# When blocked by signal/game priority, poll at least this often (seconds)
# so weather takes over quickly after a game ends or signal clears.
BLOCKED_POLL_SECONDS = 10

# Default frame interval for pattern animation (seconds)
DEFAULT_FRAME_INTERVAL = 1.0
MIN_FRAME_INTERVAL = 0.5

# Retry interval for failed weather fetches in pattern mode (seconds)
FETCH_RETRY_SECONDS = 60


def hex_to_rgb(hex_color):
    """Convert hex color string to (r, g, b) tuple."""
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def rgb_to_hex(r, g, b):
    """Convert (r, g, b) tuple to hex color string."""
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def lerp(a, b, t):
    """Linear interpolation between a and b at parameter t (0..1)."""
    return a + (b - a) * t


def pattern_frame(pattern, t, strip_index):
    """Compute the frame for a pattern at time t for a given strip.

    Args:
        pattern: Pattern definition dict with keys:
            - type: 'static', 'drift', 'wave', or 'thunderstorm'
            - color1, color2: hex colors for animation
            - period: seconds per full cycle (for drift/wave/thunderstorm)
            - brightness: target brightness (int)
            - brightness_min: minimum brightness for thunderstorm pulse (default 60)
            - phase_offset: seconds of phase offset per strip (for wave)
        t: Current time in seconds (float)
        strip_index: Index of the strip (int)

    Returns:
        (r, g, b, brightness) tuple
    """
    ptype = pattern.get("type", "static")
    brightness = pattern.get("brightness", 80)

    if ptype == "static":
        color = pattern.get("color", "#ffffff")
        r, g, b = hex_to_rgb(color)
        return (r, g, b, brightness)

    # For animated patterns, compute phase
    period = pattern.get("period", 10.0)
    phase_offset = pattern.get("phase_offset", 0.0)
    effective_t = t + (strip_index * phase_offset)
    # Normalize to 0..1 within the cycle
    phase = (effective_t % period) / period

    color1 = pattern.get("color1", "#ffffff")
    color2 = pattern.get("color2", "#000000")
    r1, g1, b1 = hex_to_rgb(color1)
    r2, g2, b2 = hex_to_rgb(color2)

    if ptype == "drift":
        # Slow drift: linear interpolation back and forth
        # Use a triangle wave: 0->1->0 over the period
        if phase < 0.5:
            interp_t = phase * 2.0  # 0->1
        else:
            interp_t = (1.0 - phase) * 2.0  # 1->0
        r = int(lerp(r1, r2, interp_t))
        g = int(lerp(g1, g2, interp_t))
        b = int(lerp(b1, b2, interp_t))
    elif ptype == "wave":
        # Wave: sinusoidal interpolation
        interp_t = (1.0 - math.cos(2.0 * math.pi * phase)) / 2.0
        r = int(lerp(r1, r2, interp_t))
        g = int(lerp(g1, g2, interp_t))
        b = int(lerp(b1, b2, interp_t))
    elif ptype == "thunderstorm":
        # Thunderstorm: sinusoidal color interpolation like wave,
        # with brightness pulsing between brightness_min and brightness
        interp_t = (1.0 - math.cos(2.0 * math.pi * phase)) / 2.0
        r = int(lerp(r1, r2, interp_t))
        g = int(lerp(g1, g2, interp_t))
        b = int(lerp(b1, b2, interp_t))
        brightness_min = pattern.get("brightness_min", 60)
        brightness = int(round(lerp(brightness_min, brightness, interp_t)))
    else:
        # Unknown type, fall back to static color1
        r, g, b = r1, g1, b1

    return (r, g, b, brightness)


def schedule_next_flash(rng, flash_every, now):
    """Schedule the next flash time.

    Args:
        rng: random.Random instance
        flash_every: [min, max] seconds between flashes
        now: current time

    Returns:
        Next flash time (float)
    """
    min_interval, max_interval = flash_every
    interval = rng.uniform(min_interval, max_interval)
    return now + interval


def should_flash(now, next_flash_time):
    """Check if it's time to flash."""
    return next_flash_time is not None and now >= next_flash_time


def next_hour_boundary(now):
    """Return the epoch time of the next local wall-clock HH:00:00 strictly after `now`.

    Args:
        now: Current epoch time (float)

    Returns:
        Epoch time (float) of the next top-of-the-hour
    """
    # Use time.localtime to get local time components
    local = time.localtime(now)
    # Calculate seconds until next hour
    seconds_into_hour = local.tm_min * 60 + local.tm_sec
    seconds_until_next_hour = 3600 - seconds_into_hour
    return now + seconds_until_next_hour




def get_pattern_for_code(code, patterns_cfg, is_day=1):
    """Get the pattern definition for a weather code.

    User overrides in patterns_cfg are merged over the defaults, so a
    partial override (e.g. only flash_every) keeps the other default keys.

    Args:
        code: WMO weather code
        patterns_cfg: Config dict for weather.patterns
        is_day: 1 if daytime, 0 if night (int)

    Returns:
        Pattern definition dict, or None for static color
    """
    if code is None:
        return None

    def _merge(key, default):
        """Merge user override over default; ignore non-dict overrides."""
        override = patterns_cfg.get(key)
        if isinstance(override, dict):
            return {**default, **override}
        return default

    # Cloudy: codes 2-3
    if 2 <= code <= 3:
        if is_day:
            return _merge("cloudy", {
                "type": "drift",
                "color1": "#546e7a",
                "color2": "#90a4ae",
                "period": 40.0,  # 20s per half cycle
                "brightness": 75,
                "phase_offset": 0.0,
            })
        else:
            return _merge("cloudy_night", {
                "type": "drift",
                "color1": "#37474f",
                "color2": "#5c6bc0",
                "period": 40.0,
                "brightness": 30,
                "phase_offset": 0.0,
            })

    # Rain: codes 51-67, 80-82
    if (51 <= code <= 67) or (80 <= code <= 82):
        if is_day:
            return _merge("rain", {
                "type": "wave",
                "color1": "#1e88e5",
                "color2": "#0d47a1",
                "period": 8.0,  # 4s per half cycle
                "brightness": 80,
                "phase_offset": 4.0,  # half cycle out of phase
            })
        else:
            return _merge("rain_night", {
                "type": "wave",
                "color1": "#0d47a1",
                "color2": "#1a237e",
                "period": 8.0,
                "brightness": 30,
                "phase_offset": 4.0,
            })

    # Thunderstorm: codes 95-99 (same pattern day and night)
    if 95 <= code <= 99:
        return _merge("thunderstorm", {
            "type": "thunderstorm",
            "color1": "#4a148c",
            "color2": "#7b1fa2",
            "period": 12.0,  # 6s per half cycle
            "brightness": 80,
            "brightness_min": 60,
            "phase_offset": 0.0,
            "flash_every": [6, 20],  # [min, max] seconds between flashes
            "flash_duration": 0.15,  # 150ms flash
            "flash_color": "#ffffff",
            "flash_brightness": 100,
            "double_flash_prob": 0.3,
            "flash_both_prob": 0.5,
        })

    # All other codes: static (no pattern)
    return None


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
        if is_day:
            return "#546e7a"  # blue-grey
        else:
            return "#37474f"  # dark blue-grey
    elif code <= 48:
        # Fog
        if is_day:
            return "#cfd8dc"  # light grey
        else:
            return "#455a64"  # dark grey
    elif code <= 67:
        # Drizzle/rain
        if is_day:
            return "#1e88e5"  # blue
        else:
            return "#0d47a1"  # dark blue
    elif code <= 77:
        # Snow
        if is_day:
            return "#e3f2fd"  # pale blue
        else:
            return "#3949ab"  # indigo
    elif code <= 82:
        # Showers
        if is_day:
            return "#1e88e5"  # blue
        else:
            return "#0d47a1"  # dark blue
    elif code <= 86:
        # Snow showers
        if is_day:
            return "#e3f2fd"  # pale blue
        else:
            return "#3949ab"  # indigo
    elif code <= 99:
        # Thunderstorm (same day and night)
        return "#7b1fa2"
    else:
        # Unknown
        if is_day:
            return "#ffffff"
        else:
            return "#37474f"


def run(config, once=False, interval=900, dry_run=False, rng=None, time_fn=None):
    """Run the weather sync loop.

    Args:
        config: Loaded config dict
        once: If True, run once and exit
        interval: Seconds between updates (default 900 = 15 min)
        dry_run: If True, print instead of sending to lights
        rng: Optional random.Random instance for testability
        time_fn: Optional time function for testability
    """
    if rng is None:
        rng = random.Random()
    if time_fn is None:
        time_fn = time.time
    weather_cfg = config.get("weather", {})
    lat = weather_cfg.get("latitude", 0.0)
    lon = weather_cfg.get("longitude", 0.0)
    brightness = weather_cfg.get("brightness", 80)
    brightness = arbiter.cap_brightness(brightness, config)
    night_brightness = weather_cfg.get("night_brightness", 30)
    night_brightness = arbiter.cap_brightness(night_brightness, config)

    # Pattern configuration
    patterns_enabled = weather_cfg.get("patterns_enabled", True)
    patterns_cfg = weather_cfg.get("patterns", {})
    frame_interval = weather_cfg.get("frame_interval", DEFAULT_FRAME_INTERVAL)
    frame_interval = max(MIN_FRAME_INTERVAL, frame_interval)

    # Fetch-on-the-hour configuration
    fetch_on_the_hour = weather_cfg.get("fetch_on_the_hour", True)

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
    last_brightness = {}  # ip -> brightness (per-strip tracking)
    priority_was_active = False
    need_power_on = True
    current_pattern = None
    pattern_start_time = None
    last_frame_time = {}  # ip -> last frame send time
    last_fetch = None  # time of last weather fetch
    next_fetch_at = None  # next scheduled fetch time (when fetch_on_the_hour is true)
    last_frame_error_time = None  # for rate-limiting frame error logs
    current_is_day = None  # track day/night for pattern switching
    last_sweep_time = None  # for rate-limiting sweep_and_restore

    # Thunderstorm flash state
    next_flash_time = None

    while True:
        now = time_fn()

        # Check signal/game priority
        if arbiter.weather_blocked():
            if not priority_was_active:
                logger.info("skipped: signal active or mode is not weather")
            priority_was_active = True
            need_power_on = True
            # Reset state so the first successful pass after the block
            # always sends, even if the colour hasn't changed.
            last_color = None
            last_brightness = {}
            current_pattern = None
            pattern_start_time = None
            last_fetch = None  # force re-fetch after priority block
            if once:
                break
            # Sweep stale session markers at most once every 60s while blocked
            if last_sweep_time is None or (now - last_sweep_time) >= 60:
                last_sweep_time = now
                try:
                    agent_signal.sweep_and_restore()
                except Exception as e:
                    logger.warning("sweep_and_restore failed: %s", e)
            time.sleep(min(interval, BLOCKED_POLL_SECONDS))
            continue

        priority_was_active = False

        # Power on the strips if they were off/blocked
        if need_power_on:
            powered_on = True
            for dev in devices:
                ip = dev["ip"]
                if dry_run:
                    logger.info("[dry-run] on -> %s", ip)
                    print(f"[dry-run] on -> {ip}")
                else:
                    try:
                        govee.turn(ip, True)
                        logger.info("on -> %s", ip)
                        print(f"on -> {ip}")
                    except OSError as e:
                        logger.warning("failed to turn on %s: %s", ip, e)
                        print(f"warning: failed to turn on {ip}: {e}", file=sys.stderr)
                        powered_on = False
            if powered_on:
                need_power_on = False

        # Determine if we need to fetch weather
        if fetch_on_the_hour:
            # Fetch at top of the hour (or immediately if never fetched / after priority block)
            if last_fetch is None or next_fetch_at is None:
                need_fetch = True
            else:
                need_fetch = now >= next_fetch_at
        else:
            # Old behaviour: fetch every `interval` seconds
            need_fetch = (last_fetch is None or (now - last_fetch) >= interval)

        if need_fetch:
            weather = None
            try:
                weather = fetch_weather(lat, lon)
            except (OSError, ValueError, KeyError) as e:
                logger.error("Failed to fetch weather: %s", e)
                if once:
                    sys.exit(1)

            if weather is not None:
                code = weather["weather_code"]
                if code is None:
                    logger.warning("weather_code is null; skipping this iteration")
                    if once:
                        sys.exit(1)
                    weather = None
                else:
                    temp = weather["temperature_2m"]
                    if temp is None:
                        logger.warning("temperature_2m is null; skipping this iteration")
                        if once:
                            sys.exit(1)
                        weather = None

            if weather is None:
                # Fetch failed or returned null fields
                if current_pattern is not None:
                    # Pattern mode: retry in ~60s, keep animating with last pattern
                    last_fetch = now - interval + FETCH_RETRY_SECONDS
                    if fetch_on_the_hour:
                        next_fetch_at = now + FETCH_RETRY_SECONDS
                else:
                    time.sleep(interval)
                    continue
            else:
                code = weather["weather_code"]
                temp = weather["temperature_2m"]
                is_day = weather["is_day"]

                color_hex = weather_to_color(code, temp, is_day)
                logger.info("Weather: code=%d temp=%.1f°C day=%d -> color=%s",
                            code, temp, is_day, color_hex)

                # Determine if we should use a pattern
                if patterns_enabled:
                    new_pattern = get_pattern_for_code(code, patterns_cfg, is_day)
                else:
                    new_pattern = None

                # If pattern changed (code or day/night), reset the pattern timer
                if new_pattern != current_pattern or is_day != current_is_day:
                    current_pattern = new_pattern
                    current_is_day = is_day
                    pattern_start_time = now
                    if current_pattern is not None:
                        logger.info("Starting pattern: %s (day=%d)",
                                    current_pattern.get("type", "unknown"), is_day)
                        # Schedule first flash for thunderstorm patterns
                        if current_pattern.get("type") == "thunderstorm":
                            flash_every = current_pattern.get("flash_every", [6, 20])
                            next_flash_time = schedule_next_flash(rng, flash_every, now)
                    else:
                        next_flash_time = None

                last_fetch = now

                # Schedule next fetch
                if fetch_on_the_hour:
                    next_fetch_at = next_hour_boundary(now)
                    next_local = time.localtime(next_fetch_at)
                    logger.info("Next weather fetch at %02d:%02d", next_local.tm_hour, next_local.tm_min)
                # When not fetch_on_the_hour, next fetch is determined by interval check

        else:
            # Reuse last weather data; color_hex is from previous fetch
            # (still valid for pattern animation)
            pass

        # Re-check priority just before sending (race condition fix).
        # A signal or game could have become active during the weather fetch.
        if arbiter.weather_blocked():
            logger.info("skipped: signal active or mode is not weather during fetch")
            priority_was_active = True
            need_power_on = True
            last_color = None
            last_brightness = {}
            current_pattern = None
            pattern_start_time = None
            last_fetch = None
            if once:
                break
            time.sleep(min(interval, BLOCKED_POLL_SECONDS))
            continue

        # Send frame(s)
        if current_pattern is not None:
            # Pattern mode: compute frame based on elapsed time
            elapsed = now - pattern_start_time

            # Check for thunderstorm flash
            is_thunderstorm = current_pattern.get("type") == "thunderstorm"
            if is_thunderstorm and should_flash(now, next_flash_time):
                # Re-check arbiter right before flashing
                if arbiter.weather_blocked():
                    logger.debug("Skipping flash: signal/game active")
                    # Schedule next flash and continue outer loop
                    flash_every = current_pattern.get("flash_every", [6, 20])
                    next_flash_time = schedule_next_flash(rng, flash_every, time_fn())
                    continue

                logger.debug("Thunderstorm flash!")
                flash_color = current_pattern.get("flash_color", "#ffffff")
                flash_brightness = current_pattern.get("flash_brightness", 100)
                flash_duration = current_pattern.get("flash_duration", 0.15)
                double_flash_prob = current_pattern.get("double_flash_prob", 0.3)
                flash_both_prob = current_pattern.get("flash_both_prob", 0.5)
                r, g, b = hex_to_rgb(flash_color)

                # Decide which strips to flash
                if len(devices) == 1:
                    flash_strips = [0]
                else:
                    if rng.random() < flash_both_prob:
                        flash_strips = [0, 1]
                    else:
                        flash_strips = [rng.randint(0, 1)]

                # Send flash frame to selected strips
                for i in flash_strips:
                    ip = devices[i]["ip"]
                    if dry_run:
                        logger.debug("[dry-run] Would flash %s to %s (brightness %d)",
                                     ip, flash_color, flash_brightness)
                    else:
                        try:
                            govee.color(ip, r, g, b)
                            govee.brightness(ip, arbiter.cap_brightness(flash_brightness, config, allow_flash=True))
                            last_brightness[ip] = flash_brightness
                            logger.debug("Flashed %s to %s (brightness %d)",
                                         ip, flash_color, flash_brightness)
                        except OSError as e:
                            if last_frame_error_time is None or (now - last_frame_error_time) >= 60:
                                logger.error("Failed to send to lights: %s", e)
                                last_frame_error_time = now

                # Wait for flash duration
                time.sleep(flash_duration)

                # Re-check arbiter after flash sleep, before double-flash logic
                if arbiter.weather_blocked():
                    logger.debug("Skipping double-flash logic: signal/game active")
                    # Schedule next flash and continue outer loop
                    flash_every = current_pattern.get("flash_every", [6, 20])
                    next_flash_time = schedule_next_flash(rng, flash_every, time_fn())
                    continue

                # Double flash?
                if rng.random() < double_flash_prob:
                    # Send base frame during the gap (spec: 120ms of base frame)
                    for i in flash_strips:
                        ip = devices[i]["ip"]
                        base_r, base_g, base_b, base_brightness = pattern_frame(current_pattern, elapsed, i)
                        # At night, use night_brightness for base frames
                        if current_is_day == 0:
                            base_brightness = night_brightness
                        base_brightness = arbiter.cap_brightness(base_brightness, config)
                        if dry_run:
                            logger.debug("[dry-run] Would send base frame to %s during double-flash gap", ip)
                        else:
                            try:
                                govee.color(ip, base_r, base_g, base_b)
                                govee.brightness(ip, base_brightness)
                                last_brightness[ip] = base_brightness
                                logger.debug("Sent base frame to %s during double-flash gap", ip)
                            except OSError as e:
                                if last_frame_error_time is None or (now - last_frame_error_time) >= 60:
                                    logger.error("Failed to send to lights: %s", e)
                                    last_frame_error_time = now

                    time.sleep(0.12)

                    # Re-check arbiter before second flash
                    if arbiter.weather_blocked():
                        logger.debug("Skipping second flash: signal/game active")
                        # Schedule next flash and continue outer loop
                        flash_every = current_pattern.get("flash_every", [6, 20])
                        next_flash_time = schedule_next_flash(rng, flash_every, time_fn())
                        continue
                    else:
                        for i in flash_strips:
                            ip = devices[i]["ip"]
                            if dry_run:
                                logger.debug("[dry-run] Would flash %s again (double flash)", ip)
                            else:
                                try:
                                    govee.color(ip, r, g, b)
                                    govee.brightness(ip, arbiter.cap_brightness(flash_brightness, config, allow_flash=True))
                                    last_brightness[ip] = flash_brightness
                                    logger.debug("Double-flashed %s", ip)
                                except OSError as e:
                                    if last_frame_error_time is None or (now - last_frame_error_time) >= 60:
                                        logger.error("Failed to send to lights: %s", e)
                                        last_frame_error_time = now
                        time.sleep(flash_duration)

                # Re-check arbiter before restoring base frame
                if arbiter.weather_blocked():
                    logger.debug("Skipping restore: signal/game active")
                    # Schedule next flash and continue outer loop
                    flash_every = current_pattern.get("flash_every", [6, 20])
                    next_flash_time = schedule_next_flash(rng, flash_every, time_fn())
                    continue

                # Restore base frame to all strips
                for i, dev in enumerate(devices):
                    ip = dev["ip"]
                    base_r, base_g, base_b, base_brightness = pattern_frame(current_pattern, elapsed, i)
                    # At night, use night_brightness for base frames
                    if current_is_day == 0:
                        base_brightness = night_brightness
                    base_brightness = arbiter.cap_brightness(base_brightness, config)
                    base_color = rgb_to_hex(base_r, base_g, base_b)
                    if dry_run:
                        logger.debug("[dry-run] Would restore %s to %s (brightness %d)",
                                     ip, base_color, base_brightness)
                    else:
                        try:
                            govee.color(ip, base_r, base_g, base_b)
                            govee.brightness(ip, base_brightness)
                            last_brightness[ip] = base_brightness
                            logger.debug("Restored %s to %s (brightness %d)",
                                         ip, base_color, base_brightness)
                        except OSError as e:
                            if last_frame_error_time is None or (now - last_frame_error_time) >= 60:
                                logger.error("Failed to send to lights: %s", e)
                                last_frame_error_time = now

                # Schedule next flash
                flash_every = current_pattern.get("flash_every", [6, 20])
                next_flash_time = schedule_next_flash(rng, flash_every, time_fn())

            # Re-check arbiter before sending normal base frame
            if arbiter.weather_blocked():
                logger.debug("Skipping base frame: signal/game active")
                continue

            # Send normal base frame
            for i, dev in enumerate(devices):
                ip = dev["ip"]
                # Check frame interval
                if ip in last_frame_time and (now - last_frame_time[ip]) < frame_interval:
                    continue

                r, g, b, frame_brightness = pattern_frame(current_pattern, elapsed, i)
                # At night, use night_brightness for base frames
                if current_is_day == 0:
                    frame_brightness = night_brightness
                frame_brightness = arbiter.cap_brightness(frame_brightness, config)

                color_str = rgb_to_hex(r, g, b)
                if dry_run:
                    logger.debug("[dry-run] Would set %s to %s (brightness %d) [pattern]",
                                 ip, color_str, frame_brightness)
                else:
                    try:
                        govee.color(ip, r, g, b)
                        if last_brightness.get(ip) != frame_brightness:
                            govee.brightness(ip, frame_brightness)
                            last_brightness[ip] = frame_brightness
                        logger.debug("Set %s to %s (brightness %d) [pattern]",
                                     ip, color_str, frame_brightness)
                    except OSError as e:
                        # Rate-limit frame error logs to one per 60 seconds
                        if last_frame_error_time is None or (now - last_frame_error_time) >= 60:
                            logger.error("Failed to send to lights: %s", e)
                            last_frame_error_time = now
                        continue
                last_frame_time[ip] = now
                last_color = color_str
        else:
            # Static mode: send only if color changed
            # At night, use night_brightness
            effective_brightness = night_brightness if current_is_day == 0 else brightness
            if color_hex != last_color or dry_run:
                r, g, b = govee.parse_color(color_hex)
                try:
                    for dev in devices:
                        ip = dev["ip"]
                        if dry_run:
                            logger.info("[dry-run] Would set %s to %s (brightness %d)",
                                        ip, color_hex, effective_brightness)
                        else:
                            govee.color(ip, r, g, b)
                            if last_brightness.get(ip) != effective_brightness:
                                govee.brightness(ip, effective_brightness)
                                last_brightness[ip] = effective_brightness
                            logger.info("Set %s to %s (brightness %d)", ip, color_hex, effective_brightness)
                except OSError as e:
                    logger.error("Failed to send to lights: %s", e)
                    # Don't update last_color so we retry next iteration
                else:
                    last_color = color_hex

        if once:
            break

        # Sleep for the appropriate interval
        if current_pattern is not None:
            # In pattern mode, sleep for frame_interval
            time.sleep(frame_interval)
        else:
            # In static mode, sleep until next fetch time (or interval, whichever is shorter)
            if fetch_on_the_hour and next_fetch_at is not None:
                sleep_time = max(1.0, min(next_fetch_at - now, interval))
            else:
                sleep_time = interval
            time.sleep(sleep_time)


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
    parser.add_argument(
        "--log-file",
        default=None,
        help="Log to this file with size rotation (1MB, 2 backups)",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    if args.log_file:
        # Log to file with rotation
        handler = logging.handlers.RotatingFileHandler(
            args.log_file, maxBytes=1_000_000, backupCount=2
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(log_level)
    else:
        logging.basicConfig(
            level=log_level,
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
