#!/usr/bin/env python3
"""Mode switch CLI.

The owner picks ONE mode by hand; only that mode may drive the strips.
The agent signal (orange) stays above everything.

Usage:
    python mode.py get
    python mode.py set <mode> [--dry-run] [--config config.json]

Modes: off, weather, game, music
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import arbiter
import govee


def load_config(path):
    """Load config from file."""
    with open(path, "r") as f:
        return json.load(f)


def switch(mode, config, dry_run=False):
    """Switch to the given mode.

    Args:
        mode: One of "off", "weather", "game", "music".
        config: The loaded config dict.
        dry_run: If True, print what would be done without doing it.
    """
    if dry_run:
        print(f"would set mode to {mode}")
        if mode == "off" and not arbiter.signal_active():
            for dev in config.get("devices", []):
                ip = dev.get("ip")
                if ip:
                    print(f"would turn off {ip}")
        return

    arbiter.set_mode(mode)

    # Only when mode is "off" and no signal is active, turn devices off.
    # For other modes, send nothing — the mode's own script will light the strips.
    if mode == "off" and not arbiter.signal_active():
        for dev in config.get("devices", []):
            ip = dev.get("ip")
            if ip:
                try:
                    govee.turn(ip, False)
                except OSError as e:
                    print(f"warning: failed to turn off {ip}: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Mode switch: pick which mode may drive the strips",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Modes:
  off      - no mode drives the strips (turns lights off if no signal)
  weather  - weather_sync.py may drive the strips
  game     - game_sync.py may drive the strips
  music    - music_sync.py may drive the strips

Examples:
  python mode.py get
  python mode.py set weather
  python mode.py set off --dry-run
""",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # get
    subparsers.add_parser("get", help="print the current mode")

    # set
    set_parser = subparsers.add_parser("set", help="set the mode")
    set_parser.add_argument("mode", help="mode: off, weather, game, or music")
    set_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be done without doing it",
    )
    set_parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.json"),
        help="path to config.json",
    )

    args = parser.parse_args()

    if args.command == "get":
        mode = arbiter.get_mode()
        print(mode)
        sys.exit(0)

    elif args.command == "set":
        if args.mode not in arbiter.MODES:
            print(f"error: unknown mode {args.mode!r}; must be one of {arbiter.MODES}", file=sys.stderr)
            sys.exit(2)
        try:
            config = load_config(args.config)
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: failed to load config {args.config}: {e}", file=sys.stderr)
            sys.exit(1)
        try:
            switch(args.mode, config, dry_run=args.dry_run)
        except OSError as e:
            print(f"error: could not set mode: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"mode: {args.mode}")
        sys.exit(0)


if __name__ == "__main__":
    main()
