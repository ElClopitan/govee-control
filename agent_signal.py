#!/usr/bin/env python3
"""Agent-needs-input light signal.

Turns lights a signal colour when an AI agent needs input, and restores
them afterwards.

Usage:
    python agent_signal.py needs-input [--config PATH] [--dry-run]
    python agent_signal.py clear [--config PATH] [--dry-run]
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import govee

STATE_DIR = Path(__file__).parent / "state"
SAVED_STATE_FILE = STATE_DIR / "saved_state.json"

DEFAULT_SIGNAL = {
    "color": "#ff6a00",
    "brightness": 100,
    "blink": False,
}


def load_config(path):
    """Load config from JSON file."""
    with open(path, "r") as f:
        return json.load(f)


def get_signal_config(cfg):
    """Get signal config, falling back to defaults."""
    return cfg.get("signal", DEFAULT_SIGNAL)


def save_state(devices, dry_run=False):
    """Save current device states to file."""
    if dry_run:
        print(f"[dry-run] would save state to {SAVED_STATE_FILE}")
        return

    SAVED_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    states = []
    for dev in devices:
        ip = dev["ip"]
        try:
            resp = govee.status(ip)
            if resp:
                data = resp.get("msg", {}).get("data", {})
                states.append({
                    "ip": ip,
                    "on": data.get("on", True),
                    "brightness": data.get("brightness", 100),
                    "color": data.get("color", {"r": 255, "g": 255, "b": 255}),
                })
            else:
                print(f"warning: no status response from {ip}", file=sys.stderr)
        except Exception as e:
            print(f"warning: failed to get status from {ip}: {e}", file=sys.stderr)

    with open(SAVED_STATE_FILE, "w") as f:
        json.dump(states, f, indent=2)
    print(f"saved state to {SAVED_STATE_FILE}")


def load_saved_state():
    """Load saved device states from file."""
    if not SAVED_STATE_FILE.exists():
        return None
    with open(SAVED_STATE_FILE, "r") as f:
        return json.load(f)


def delete_saved_state(dry_run=False):
    """Delete the saved state file."""
    if dry_run:
        print(f"[dry-run] would delete {SAVED_STATE_FILE}")
        return
    if SAVED_STATE_FILE.exists():
        SAVED_STATE_FILE.unlink()
        print(f"deleted {SAVED_STATE_FILE}")


def set_signal_color(devices, signal_cfg, dry_run=False):
    """Set all devices to the signal colour."""
    color_str = signal_cfg.get("color", DEFAULT_SIGNAL["color"])
    brightness = signal_cfg.get("brightness", DEFAULT_SIGNAL["brightness"])
    blink = signal_cfg.get("blink", DEFAULT_SIGNAL["blink"])

    r, g, b = govee.parse_color(color_str)

    if blink:
        # Blink 3 times (on/off pairs), then stay on
        for i in range(3):
            if not dry_run:
                for dev in devices:
                    govee.turn(dev["ip"], True)
                    govee.brightness(dev["ip"], brightness)
                    govee.color(dev["ip"], r, g, b)
            else:
                print(f"[dry-run] blink {i+1}: on {color_str} at {brightness}%")
            time.sleep(0.4)

            if not dry_run:
                for dev in devices:
                    govee.turn(dev["ip"], False)
            else:
                print(f"[dry-run] blink {i+1}: off")
            time.sleep(0.4)

        # Stay on after blinking
        if not dry_run:
            for dev in devices:
                govee.turn(dev["ip"], True)
                govee.brightness(dev["ip"], brightness)
                govee.color(dev["ip"], r, g, b)
        else:
            print(f"[dry-run] staying on {color_str} at {brightness}%")
    else:
        # Just set the colour
        if not dry_run:
            for dev in devices:
                govee.turn(dev["ip"], True)
                govee.brightness(dev["ip"], brightness)
                govee.color(dev["ip"], r, g, b)
        else:
            print(f"[dry-run] set {color_str} at {brightness}% on all devices")


def restore_state(devices, cfg, dry_run=False):
    """Restore saved state or apply default."""
    saved = load_saved_state()

    if saved:
        # Restore from saved state
        for dev_state in saved:
            ip = dev_state["ip"]
            if not dry_run:
                govee.turn(ip, dev_state.get("on", True))
                govee.brightness(ip, dev_state.get("brightness", 100))
                color = dev_state.get("color", {"r": 255, "g": 255, "b": 255})
                govee.color(ip, color.get("r", 255), color.get("g", 255), color.get("b", 255))
            else:
                print(f"[dry-run] restore {ip}: on={dev_state.get('on')}, brightness={dev_state.get('brightness')}")
        print("restored saved state")
    elif "default" in cfg:
        # Apply default config
        default = cfg["default"]
        color_str = default.get("color", "white")
        brightness = default.get("brightness", 100)
        r, g, b = govee.parse_color(color_str)
        if not dry_run:
            for dev in devices:
                govee.turn(dev["ip"], True)
                govee.brightness(dev["ip"], brightness)
                govee.color(dev["ip"], r, g, b)
        else:
            print(f"[dry-run] apply default: {color_str} at {brightness}%")
        print("applied default config")
    else:
        print("no saved state and no default config; nothing to restore")
        return False
    return True


def cmd_needs_input(args):
    """Handle the needs-input command."""
    cfg = load_config(args.config)
    devices = cfg.get("devices", [])
    if not devices:
        print("no devices in config", file=sys.stderr)
        sys.exit(1)

    signal_cfg = get_signal_config(cfg)

    # Only save state if no saved file exists (idempotent)
    if not SAVED_STATE_FILE.exists() or args.dry_run:
        save_state(devices, dry_run=args.dry_run)

    set_signal_color(devices, signal_cfg, dry_run=args.dry_run)
    print("signal set")


def cmd_clear(args):
    """Handle the clear command."""
    cfg = load_config(args.config)
    devices = cfg.get("devices", [])
    if not devices:
        print("no devices in config", file=sys.stderr)
        sys.exit(1)

    restored = restore_state(devices, cfg, dry_run=args.dry_run)
    if restored:
        delete_saved_state(dry_run=args.dry_run)
    print("signal cleared")


def main():
    parser = argparse.ArgumentParser(
        description="Agent-needs-input light signal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python agent_signal.py needs-input
  python agent_signal.py clear
  python agent_signal.py needs-input --config myconfig.json --dry-run
""",
    )
    parser.add_argument(
        "command",
        choices=["needs-input", "clear"],
        help="signal command",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.json"),
        help="path to config.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be done without sending commands",
    )

    args = parser.parse_args()

    if args.command == "needs-input":
        cmd_needs_input(args)
    elif args.command == "clear":
        cmd_clear(args)


if __name__ == "__main__":
    main()
