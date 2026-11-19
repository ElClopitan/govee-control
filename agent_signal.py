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
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import arbiter
import govee

STATE_DIR = Path(__file__).parent / "state"
LOCK_FILE = STATE_DIR / "agent_signal.lock"
LOCK_TIMEOUT = 10.0
LOCK_STALE = 30.0

DEFAULT_SIGNAL = {
    "color": "#ff6a00",
    "brightness": 100,
    "blink": False,
}


def acquire_lock(dry_run=False):
    """Acquire an exclusive lock on the state directory.

    Returns True if the lock was acquired, False if it timed out.
    """
    if dry_run:
        return True

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + LOCK_TIMEOUT
    while True:
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            # Check if lock is stale
            try:
                mtime = os.path.getmtime(str(LOCK_FILE))
                if time.time() - mtime > LOCK_STALE:
                    # Stale lock, remove it
                    os.unlink(str(LOCK_FILE))
                    continue
            except OSError:
                pass

            if time.time() >= deadline:
                print(f"warning: could not acquire lock within {LOCK_TIMEOUT}s", file=sys.stderr)
                return False

            time.sleep(0.1)


def release_lock(dry_run=False):
    """Release the lock."""
    if dry_run:
        return

    try:
        os.unlink(str(LOCK_FILE))
    except OSError:
        pass


def load_config(path):
    """Load config from JSON file."""
    with open(path, "r") as f:
        return json.load(f)


def get_signal_config(cfg):
    """Get signal config, falling back to defaults."""
    return cfg.get("signal", DEFAULT_SIGNAL)


def save_state(devices, dry_run=False):
    """Save current device states to file."""
    signal_path = arbiter.signal_file()
    if dry_run:
        print(f"[dry-run] would save state to {signal_path}")
        return

    signal_path.parent.mkdir(parents=True, exist_ok=True)

    states = []
    for dev in devices:
        ip = dev["ip"]
        resp = None
        for attempt in range(3):
            try:
                resp = govee.status(ip)
                if resp:
                    break
            except OSError:
                pass
            if attempt < 2:
                time.sleep(0.3)

        if resp:
            data = resp.get("msg", {}).get("data", {})
            states.append({
                "ip": ip,
                "on": bool(data.get("onOff", 1)),
                "brightness": data.get("brightness", 100),
                "color": data.get("color", {"r": 255, "g": 255, "b": 255}),
                "colorTemInKelvin": data.get("colorTemInKelvin", 0),
            })
        else:
            print(f"warning: no status response from {ip}", file=sys.stderr)

    if not states:
        print("warning: no device answered devStatus; state not saved", file=sys.stderr)
        return

    with open(signal_path, "w") as f:
        json.dump(states, f, indent=2)
    print(f"saved state to {signal_path}")


def load_saved_state():
    """Load saved device states from file."""
    signal_path = arbiter.signal_file()
    if not signal_path.exists():
        return None
    try:
        with open(signal_path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"warning: failed to parse saved state: {e}", file=sys.stderr)
        return []


def delete_saved_state(dry_run=False):
    """Delete the saved state file."""
    signal_path = arbiter.signal_file()
    if dry_run:
        print(f"[dry-run] would delete {signal_path}")
        return
    if signal_path.exists():
        signal_path.unlink()
        print(f"deleted {signal_path}")


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


def restore_state(devices, default_cfg=None, dry_run=False):
    """Restore saved state. Returns True if state was restored, False if none."""
    saved = load_saved_state()

    if saved:
        # Build a map of saved states by IP
        saved_by_ip = {s["ip"]: s for s in saved}

        # Restore from saved state for devices that have it
        for dev_state in saved:
            ip = dev_state["ip"]
            was_on = dev_state.get("on", True)
            brightness = dev_state.get("brightness", 100)
            color = dev_state.get("color", {"r": 255, "g": 255, "b": 255})
            kelvin = dev_state.get("colorTemInKelvin", 0)

            if not dry_run:
                if was_on:
                    # If it was on: turn on first, then brightness, then color
                    govee.turn(ip, True)
                    govee.brightness(ip, brightness)
                    govee.color(ip, color.get("r", 255), color.get("g", 255), color.get("b", 255), kelvin=kelvin)
                else:
                    # If it was off: set brightness and color first, then turn off LAST
                    # (color command can switch the light back on)
                    govee.brightness(ip, brightness)
                    govee.color(ip, color.get("r", 255), color.get("g", 255), color.get("b", 255), kelvin=kelvin)
                    govee.turn(ip, False)
            else:
                print(f"[dry-run] restore {ip}: on={was_on}, brightness={brightness}")

        # Fallback: for devices in config but not in saved state, apply default
        if default_cfg:
            for dev in devices:
                ip = dev["ip"]
                if ip not in saved_by_ip:
                    color_str = default_cfg.get("color", "white")
                    brightness = default_cfg.get("brightness", 40)
                    r, g, b = govee.parse_color(color_str)
                    if not dry_run:
                        govee.turn(ip, True)
                        govee.brightness(ip, brightness)
                        govee.color(ip, r, g, b, kelvin=0)
                    else:
                        print(f"[dry-run] fallback {ip}: {color_str} at {brightness}%")

        print("restored saved state")
        return True
    else:
        print("no active signal; nothing to do")
        return False


def cmd_needs_input(args):
    """Handle the needs-input command."""
    cfg = load_config(args.config)
    devices = cfg.get("devices", [])
    if not devices:
        print("no devices in config", file=sys.stderr)
        sys.exit(1)

    signal_cfg = get_signal_config(cfg)
    signal_path = arbiter.signal_file()

    # Fast path: if state already saved, just set the signal colour
    if signal_path.exists() and not args.dry_run:
        set_signal_color(devices, signal_cfg, dry_run=args.dry_run)
        print("signal set")
        return

    # Acquire lock before saving state
    if not acquire_lock(dry_run=args.dry_run):
        # Lock timed out, still set the signal colour
        set_signal_color(devices, signal_cfg, dry_run=args.dry_run)
        print("signal set")
        return

    try:
        # Re-check under the lock (race condition fix)
        if not signal_path.exists() or args.dry_run:
            save_state(devices, dry_run=args.dry_run)

        set_signal_color(devices, signal_cfg, dry_run=args.dry_run)
        print("signal set")
    finally:
        release_lock(dry_run=args.dry_run)


def cmd_clear(args):
    """Handle the clear command."""
    signal_path = arbiter.signal_file()
    # Fast path: if no saved state, nothing to do (no lock needed)
    if not signal_path.exists():
        print("no active signal; nothing to do")
        return

    cfg = load_config(args.config)
    devices = cfg.get("devices", [])
    if not devices:
        print("no devices in config", file=sys.stderr)
        sys.exit(1)

    default_cfg = cfg.get("default")

    # Acquire lock before restoring state
    if not acquire_lock(dry_run=args.dry_run):
        # Lock timed out, exit 0 without doing anything
        return

    try:
        # Re-check under the lock
        if not signal_path.exists():
            print("no active signal; nothing to do")
            return

        restore_state(devices, default_cfg=default_cfg, dry_run=args.dry_run)
        delete_saved_state(dry_run=args.dry_run)
        print("signal cleared")
    finally:
        release_lock(dry_run=args.dry_run)


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
