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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import arbiter
import govee

STATE_DIR = Path(__file__).parent / "state"
LOCK_FILE = STATE_DIR / "agent_signal.lock"
LOCK_TIMEOUT = 10.0
LOCK_STALE = 30.0
STATUS_TIMEOUT = 1.0
SAVE_STATE_BUDGET = 4.0  # lock is held for save_state + set_signal_color; with blink on for 2 strips set_signal_color takes ~4 s, so total must stay under LOCK_TIMEOUT with margin
LOG_MAX_BYTES = 200 * 1024  # 200 KB
LOG_MAX_LINES = 100


def signal_log_path():
    """Return the path to the signal log, resolved at call time.

    This uses the current module value of STATE_DIR so that tests can
    patch STATE_DIR and have log events land in the test directory.
    """
    return STATE_DIR / "signal.log"

DEFAULT_SIGNAL = {
    "color": "#ff6a00",
    "brightness": 80,
    "blink": False,
}


def is_unattended(env=None):
    """Check if the current session is unattended (background/dispatcher).

    Returns True when CLAUDE_CODE_SESSION_ATTENDED is set to "0".
    """
    if env is None:
        env = os.environ
    return env.get("CLAUDE_CODE_SESSION_ATTENDED") == "0"


def read_hook_input():
    """Read hook input JSON from stdin if available.

    Returns a dict with session_id and message if present, or an empty dict.
    Never fails if stdin is empty or not JSON.
    """
    if sys.stdin.isatty():
        return {}
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        data = json.loads(raw)
        return {
            "session_id": data.get("session_id", ""),
            "message": data.get("message", ""),
        }
    except (json.JSONDecodeError, OSError):
        return {}


def log_signal_event(command, action, hook_input=None):
    """Append a log line to state/signal.log.

    Format: ISO timestamp, command, action, session_id, message.
    Truncates the log if it exceeds LOG_MAX_BYTES.
    """
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)

        log_path = signal_log_path()

        # Truncate if too large
        if log_path.exists():
            try:
                size = log_path.stat().st_size
                if size > LOG_MAX_BYTES:
                    # Keep last 100 lines
                    with open(log_path, "r") as f:
                        lines = f.readlines()
                    with open(log_path, "w") as f:
                        f.writelines(lines[-LOG_MAX_LINES:])
            except OSError:
                pass

        now = datetime.now(timezone.utc).isoformat()
        session_id = ""
        message = ""
        if hook_input:
            session_id = hook_input.get("session_id", "")
            message = hook_input.get("message", "")

        line = f"{now} {command} {action}"
        if session_id:
            line += f" session={session_id}"
        if message:
            line += f" msg={message}"
        line += "\n"

        with open(log_path, "a") as f:
            f.write(line)
    except OSError:
        pass


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


def is_signal_state(entry, signal_cfg):
    """Check if a device state entry matches the signal colour.

    Returns True when the entry's color r/g/b equals the signal colour
    and the entry is on. Brightness does not matter.
    """
    if not entry.get("on", True):
        return False
    color_str = signal_cfg.get("color", DEFAULT_SIGNAL["color"])
    try:
        r, g, b = govee.parse_color(color_str)
    except ValueError:
        return False
    entry_color = entry.get("color", {})
    return (
        entry_color.get("r") == r
        and entry_color.get("g") == g
        and entry_color.get("b") == b
    )


def save_state(devices, signal_cfg, dry_run=False):
    """Save current device states to file."""
    signal_path = arbiter.signal_file()
    if dry_run:
        print(f"[dry-run] would save state to {signal_path}")
        return

    signal_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.time() + SAVE_STATE_BUDGET
    states = []
    for dev in devices:
        ip = dev["ip"]
        resp = None
        for attempt in range(3):
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                resp = govee.status(ip, timeout=min(STATUS_TIMEOUT, remaining))
                if resp:
                    break
            except OSError:
                pass
            if attempt < 2:
                sleep_time = 0.3
                if time.time() + sleep_time >= deadline:
                    break
                time.sleep(sleep_time)

        if resp:
            data = resp.get("msg", {}).get("data", {})
            entry = {
                "ip": ip,
                "on": bool(data.get("onOff", 1)),
                "brightness": data.get("brightness", 100),
                "color": data.get("color", {"r": 255, "g": 255, "b": 255}),
                "colorTemInKelvin": data.get("colorTemInKelvin", 0),
            }
            # Skip saving if the device is already showing the signal colour
            if not is_signal_state(entry, signal_cfg):
                states.append(entry)
        else:
            print(f"warning: no status response from {ip}", file=sys.stderr)

    if not states:
        print("warning: no device answered devStatus; writing empty marker", file=sys.stderr)

    with open(signal_path, "w") as f:
        json.dump(states, f, indent=2)
    print(f"saved state to {signal_path}")


def load_saved_state(quiet=False):
    """Load saved device states from file.

    Validates the shape of the loaded data: must be a list of dicts, each with
    a string "ip" field. Invalid entries are dropped with a warning.
    """
    signal_path = arbiter.signal_file()
    if not signal_path.exists():
        return None
    try:
        with open(signal_path, "r") as f:
            data = json.load(f)
    except (ValueError, OSError) as e:
        if not quiet:
            print(f"warning: failed to parse saved state: {e}", file=sys.stderr)
        return []

    # Validate shape: must be a list
    if not isinstance(data, list):
        if not quiet:
            print("warning: saved state is not a list; ignoring it", file=sys.stderr)
        return []

    # Filter to only valid entries (dicts with a string "ip" field)
    valid = []
    for entry in data:
        if isinstance(entry, dict) and isinstance(entry.get("ip"), str):
            valid.append(entry)
        elif not quiet:
            print(f"warning: dropping invalid saved state entry: {entry}", file=sys.stderr)

    return valid


def delete_saved_state(dry_run=False, quiet=False):
    """Delete the saved state file."""
    signal_path = arbiter.signal_file()
    if dry_run:
        print(f"[dry-run] would delete {signal_path}")
        return
    if signal_path.exists():
        signal_path.unlink()
        if not quiet:
            print(f"deleted {signal_path}")


def set_signal_color(devices, signal_cfg, cfg, dry_run=False):
    """Set all devices to the signal colour."""
    color_str = signal_cfg.get("color", DEFAULT_SIGNAL["color"])
    brightness = signal_cfg.get("brightness", DEFAULT_SIGNAL["brightness"])
    brightness = arbiter.cap_brightness(brightness, cfg)
    blink = signal_cfg.get("blink", DEFAULT_SIGNAL["blink"])

    r, g, b = govee.parse_color(color_str)

    if blink:
        # Blink 3 times (on/off pairs), then stay on
        for i in range(3):
            if not dry_run:
                for dev in devices:
                    govee.turn(dev["ip"], True)
                    time.sleep(0.1)
                    govee.brightness(dev["ip"], brightness)
                    time.sleep(0.1)
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
                time.sleep(0.1)
                govee.brightness(dev["ip"], brightness)
                time.sleep(0.1)
                govee.color(dev["ip"], r, g, b)
        else:
            print(f"[dry-run] staying on {color_str} at {brightness}%")
    else:
        # Just set the colour
        if not dry_run:
            for dev in devices:
                govee.turn(dev["ip"], True)
                time.sleep(0.1)
                govee.brightness(dev["ip"], brightness)
                time.sleep(0.1)
                govee.color(dev["ip"], r, g, b)
        else:
            print(f"[dry-run] set {color_str} at {brightness}% on all devices")


def restore_state(devices, signal_cfg, cfg, default_cfg=None, dry_run=False, quiet=False):
    """Restore saved state. Returns True if state was restored, False if none."""
    saved = load_saved_state(quiet=quiet)

    if saved is not None:
        # Build a map of saved states by IP
        saved_by_ip = {s["ip"]: s for s in saved}

        # Track which devices were skipped (signal colour) so they get fallback
        skipped_ips = set()

        # Restore from saved state for devices that have it
        for dev_state in saved:
            ip = dev_state["ip"]
            # Skip restoring if the saved state matches the signal colour
            # (it was saved while the signal was active)
            if is_signal_state(dev_state, signal_cfg):
                skipped_ips.add(ip)
                continue
            was_on = dev_state.get("on", True)
            brightness = dev_state.get("brightness", 100)
            brightness = arbiter.cap_brightness(brightness, cfg)
            color = dev_state.get("color", {"r": 255, "g": 255, "b": 255})
            kelvin = dev_state.get("colorTemInKelvin", 0)

            if not dry_run:
                if was_on:
                    # If it was on: turn on first, then brightness, then color
                    govee.turn(ip, True)
                    time.sleep(0.1)
                    govee.brightness(ip, brightness)
                    time.sleep(0.1)
                    govee.color(ip, color.get("r", 255), color.get("g", 255), color.get("b", 255), kelvin=kelvin)
                else:
                    # If it was off: set brightness and color first, then turn off LAST
                    # (color command can switch the light back on)
                    govee.brightness(ip, brightness)
                    time.sleep(0.1)
                    govee.color(ip, color.get("r", 255), color.get("g", 255), color.get("b", 255), kelvin=kelvin)
                    time.sleep(0.1)
                    govee.turn(ip, False)
            else:
                print(f"[dry-run] restore {ip}: on={was_on}, brightness={brightness}")

        # Fallback: for devices in config but not in saved state, or skipped
        # (signal colour), apply default.
        # If default_cfg is None (config had "default": null), use the built-in default.
        fallback = default_cfg if default_cfg is not None else arbiter.BUILTIN_DEFAULT
        for dev in devices:
            ip = dev["ip"]
            if ip not in saved_by_ip or ip in skipped_ips:
                color_str = fallback.get("color", "white")
                brightness = fallback.get("brightness", 40)
                brightness = arbiter.cap_brightness(brightness, cfg)
                r, g, b = govee.parse_color(color_str)
                if not dry_run:
                    govee.turn(ip, True)
                    time.sleep(0.1)
                    govee.brightness(ip, brightness)
                    time.sleep(0.1)
                    govee.color(ip, r, g, b, kelvin=0)
                else:
                    print(f"[dry-run] fallback {ip}: {color_str} at {brightness}%")

        # Only print "restored saved state" if we actually had saved state to restore
        # (not just an empty/corrupt file that fell through to the default)
        if saved:
            print("restored saved state")
        return True
    else:
        print("no active signal; nothing to do")
        return False


def cmd_needs_input(args):
    """Handle the needs-input command."""
    hook_input = read_hook_input()

    # Check if unattended and not forced
    if not args.force and is_unattended():
        cfg = load_config(args.config)
        signal_cfg = get_signal_config(cfg)
        include_unattended = signal_cfg.get("include_unattended", False)
        if not include_unattended:
            log_signal_event("needs-input", "skipped-unattended", hook_input)
            return

    cfg = load_config(args.config)
    devices = cfg.get("devices", [])
    if not devices:
        print("no devices in config", file=sys.stderr)
        sys.exit(1)

    signal_cfg = get_signal_config(cfg)
    signal_path = arbiter.signal_file()

    # Always acquire lock before saving state (race condition fix)
    if not acquire_lock(dry_run=args.dry_run):
        # Lock timed out: don't set the signal colour. Without the lock we
        # can't save state, so a later clear would take its fast path
        # ("no active signal") and never restore the strips. A missed
        # signal is better than orange strips that nothing clears.
        print("warning: lock busy; not setting the signal colour", file=sys.stderr)
        log_signal_event("needs-input", "lock-timeout-skipped", hook_input)
        return

    try:
        # Re-check under the lock (race condition fix)
        if not signal_path.exists() or args.dry_run:
            save_state(devices, signal_cfg, dry_run=args.dry_run)

        try:
            set_signal_color(devices, signal_cfg, cfg, dry_run=args.dry_run)
        except OSError as e:
            print(f"warning: could not set signal colour: {e}", file=sys.stderr)
            log_signal_event("needs-input", "oserror", hook_input)
            return
        log_signal_event("needs-input", "applied", hook_input)
        print("signal set")
    finally:
        release_lock(dry_run=args.dry_run)


def cmd_clear(args):
    """Handle the clear command."""
    hook_input = read_hook_input()
    signal_path = arbiter.signal_file()
    # Fast path: if no saved state, nothing to do (no lock needed)
    if not signal_path.exists():
        log_signal_event("clear", "no-signal", hook_input)
        print("no active signal; nothing to do")
        return

    cfg = load_config(args.config)
    devices = cfg.get("devices", [])
    if not devices:
        print("no devices in config", file=sys.stderr)
        sys.exit(1)

    signal_cfg = get_signal_config(cfg)
    default_cfg = cfg.get("default")

    # Acquire lock before restoring state
    if not acquire_lock(dry_run=args.dry_run):
        # Lock timed out, exit 0 without doing anything
        log_signal_event("clear", "lock-timeout", hook_input)
        return

    try:
        # Re-check under the lock
        if not signal_path.exists():
            log_signal_event("clear", "no-signal", hook_input)
            print("no active signal; nothing to do")
            return

        # Check if the saved state is corrupt before restoring
        saved = load_saved_state(quiet=True)
        was_corrupt = saved == []

        try:
            restore_state(devices, signal_cfg, cfg, default_cfg=default_cfg, dry_run=args.dry_run, quiet=was_corrupt)
        except OSError as e:
            print(f"warning: could not restore lights: {e}", file=sys.stderr)
            log_signal_event("clear", "oserror", hook_input)
            return
        delete_saved_state(dry_run=args.dry_run, quiet=was_corrupt)
        log_signal_event("clear", "applied", hook_input)
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="apply signal even for unattended/background sessions",
    )

    args = parser.parse_args()

    if args.command == "needs-input":
        cmd_needs_input(args)
    elif args.command == "clear":
        cmd_clear(args)


if __name__ == "__main__":
    main()
