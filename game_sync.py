#!/usr/bin/env python3
"""Game-aware lighting: detect running games and set Govee lights accordingly.

When a known game is running, set the lights to that game's colour.
When no game is running, restore a default colour/brightness, unless config
has "default": null, in which case it sends nothing and leaves the lights to
weather_sync or manual control.

Stdlib only. Uses govee.py for device control.
"""

import argparse
import csv
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import arbiter
import govee


def running_processes():
    """Get running process names on Windows via tasklist.

    Returns a set of lower-case exe names (e.g. {'chrome.exe', 'notepad.exe'}).
    """
    try:
        result = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return set()
        reader = csv.reader(io.StringIO(result.stdout))
        processes = set()
        for row in reader:
            if row:
                name = row[0].strip('"').lower()
                processes.add(name)
        return processes
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return set()


def pick_profile(processes, games):
    """Pick the first game profile whose exe is running.

    Args:
        processes: set of running process names (lower-case)
        games: list of game config dicts with 'exe' key

    Returns:
        The first matching game dict, or None if no match.
    """
    for game in games:
        exe = game.get("exe", "").lower()
        if exe in processes:
            return game
    return None


def apply_profile(config, profile, dry_run=False):
    """Apply a colour/brightness profile to all configured devices.

    Args:
        config: loaded config dict
        profile: dict with 'color' and 'brightness' keys
        dry_run: if True, print what would be sent instead of sending
    """
    devices = config.get("devices", [])
    color_str = profile.get("color", "white")
    brightness_val = profile.get("brightness", 50)
    brightness_val = arbiter.cap_brightness(brightness_val, config)

    try:
        r, g, b = govee.parse_color(color_str)
    except ValueError:
        print(f"Warning: invalid colour {color_str!r}, using white", file=sys.stderr)
        r, g, b = 255, 255, 255

    for dev in devices:
        ip = dev.get("ip")
        if not ip:
            continue
        if dry_run:
            print(f"[dry-run] color #{r:02x}{g:02x}{b:02x} brightness {brightness_val}% -> {ip}")
        else:
            govee.color(ip, r, g, b)
            govee.brightness(ip, brightness_val)
            print(f"color #{r:02x}{g:02x}{b:02x} brightness {brightness_val}% -> {ip}")


def run(config, interval=5, once=False, dry_run=False):
    """Main sync loop.

    Every interval seconds, check for running games and update lights.
    Only sends commands when the chosen profile changes (no spamming).
    Respects agent signal priority: if signal is active, do not send.

    Args:
        config: loaded config dict
        interval: seconds between checks
        once: if True, run one check and exit
        dry_run: if True, print instead of sending
    """
    games = config.get("games", [])
    # If "default" key is missing, use the built-in default.
    # If "default" is explicitly null, use None (no default profile).
    if "default" in config:
        default = config["default"]
    else:
        default = arbiter.BUILTIN_DEFAULT

    last_profile_name = None
    signal_was_active = False

    try:
        while True:
            processes = running_processes()
            profile = pick_profile(processes, games)

            if profile is None:
                profile = default
                profile_name = "default"
            else:
                profile_name = profile.get("name", profile.get("exe", "unknown"))

            # Manage game_active state (skip in dry-run and once mode).
            # In loop mode, rewriting the file every iteration is the heartbeat
            # that keeps game_active() returning True (see arbiter.GAME_STALE_SECONDS).
            if not dry_run and not once:
                if profile_name != "default":
                    arbiter.set_game_active(profile_name)
                elif arbiter.game_active():
                    arbiter.clear_game_active()

            # Check signal priority
            if arbiter.signal_active():
                if not signal_was_active:
                    print("signal active; skipping game sync")
                signal_was_active = True
                # Reset last_profile_name so the first successful pass after
                # the signal clears always sends, even if the profile hasn't changed.
                last_profile_name = None
            else:
                signal_was_active = False
                if profile_name != last_profile_name:
                    # Re-check signal just before applying (race condition fix).
                    # A signal could have become active since we last checked.
                    if arbiter.signal_active():
                        print("signal active; skipping game sync")
                        last_profile_name = None
                    else:
                        # If default is null (no game -> leave lights alone),
                        # don't send anything; just mark as applied.
                        if profile is None:
                            print("no game running; leaving lights to weather/manual")
                            last_profile_name = profile_name
                        else:
                            print(f"Switching to: {profile_name}")
                            try:
                                apply_profile(config, profile, dry_run=dry_run)
                            except OSError as e:
                                print(f"warning: failed to apply {profile_name}: {e}", file=sys.stderr)
                            else:
                                last_profile_name = profile_name

            if once:
                break

            time.sleep(interval)
    finally:
        # Clear game_active on exit (loop mode only) so a crashed or
        # Ctrl+C'd game_sync doesn't leave a stale file blocking weather.
        if not dry_run and not once:
            arbiter.clear_game_active()


def main():
    parser = argparse.ArgumentParser(
        description="Game-aware Govee lighting sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python game_sync.py --once --dry-run
  python game_sync.py --interval 10
  python game_sync.py --config myconfig.json
""",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one check and exit",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="seconds between checks (default: 5)",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.json"),
        help="path to config.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be sent instead of sending",
    )

    args = parser.parse_args()

    try:
        config = govee.load_config(args.config)
    except FileNotFoundError:
        print(f"Config not found: {args.config}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in config: {e}", file=sys.stderr)
        sys.exit(1)

    if "games" not in config:
        print("Config missing 'games' key", file=sys.stderr)
        sys.exit(1)

    run(config, interval=args.interval, once=args.once, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
