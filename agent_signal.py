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
import platform
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import arbiter
import govee

STATE_DIR = Path(__file__).parent / "state"


def find_claude_pid():
    """Find the PID of the Claude Code process by walking up the parent chain.

    On Windows, uses kernel32 CreateToolhelp32Snapshot / Process32FirstW /
    Process32NextW to enumerate processes and find the first ancestor whose
    exe name is claude.exe or node.exe (case-insensitive, exact match).
    Returns None on any error or on non-Windows.
    """
    if platform.system() != "Windows":
        return None

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        # Constants
        TH32CS_SNAPPROCESS = 0x00000002

        # PROCESSENTRY32W structure
        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        # Set restype/argtypes for kernel32 functions
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        # Take ONE snapshot and build a dict of pid -> (parent_pid, exe_name)
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == wintypes.HANDLE(-1).value:
            return None

        try:
            pe = PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)

            if not kernel32.Process32FirstW(snapshot, ctypes.byref(pe)):
                return None

            # Build process tree map
            process_map = {}
            while True:
                pid = pe.th32ProcessID
                parent_pid = pe.th32ParentProcessID
                exe_name = pe.szExeFile.lower()
                process_map[pid] = (parent_pid, exe_name)

                if not kernel32.Process32NextW(snapshot, ctypes.byref(pe)):
                    break
        finally:
            kernel32.CloseHandle(snapshot)

        # Walk up the parent chain from our own PID
        current_pid = os.getpid()
        visited = set()
        while current_pid in process_map and current_pid not in visited:
            visited.add(current_pid)
            parent_pid, exe_name = process_map[current_pid]

            # Check if this process is claude.exe or node.exe (exact match)
            if exe_name == "claude.exe" or exe_name == "node.exe":
                return current_pid

            current_pid = parent_pid

        return None
    except Exception:
        return None


def pid_alive(pid):
    """Check if a process with the given PID is still alive.

    On Windows, uses OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION
    and GetExitCodeProcess. Returns True if alive, False if dead.
    If pid is None, returns True (treat as alive, fall back to max age).
    """
    if pid is None:
        return True

    if platform.system() != "Windows":
        return True

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle == 0:
            return False

        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            kernel32.CloseHandle(handle)
            return False

        kernel32.CloseHandle(handle)
        return exit_code.value == STILL_ACTIVE
    except Exception:
        return True
LOCK_FILE = STATE_DIR / "agent_signal.lock"
LOCK_TIMEOUT = 10.0
LOCK_STALE = 30.0
STATUS_TIMEOUT = 1.0
SAVE_STATE_BUDGET = 4.0  # lock is held for save_state + set_signal_color; with blink on for 2 strips set_signal_color takes ~4 s, so total must stay under LOCK_TIMEOUT with margin
LOG_MAX_BYTES = 200 * 1024  # 200 KB
LOG_MAX_LINES = 100
MARKER_MAX_AGE_HOURS_DEFAULT = 2

DEFAULT_SIGNAL = {
    "color": "#ff6a00",
    "brightness": 80,
    "blink": False,
    "ignore_message_patterns": [r" finished$", r"\bcompleted$"],
}


def signal_log_path():
    """Return the path to the signal log, resolved at call time.

    This uses the current module value of STATE_DIR so that tests can
    patch STATE_DIR and have log events land in the test directory.
    """
    return STATE_DIR / "signal.log"


def signal_sessions_dir():
    """Return the path to the signal sessions directory, resolved at call time.

    This uses the current module value of STATE_DIR so that tests can
    patch STATE_DIR and have session markers land in the test directory.
    """
    return STATE_DIR / "signal_sessions"


def marker_name(session_id):
    """Sanitise a session_id for use as a filename.

    Replaces any character that is not alphanumeric, underscore, or hyphen
    with an underscore, and truncates to 100 characters. Returns 'manual'
    when the id is empty.
    """
    if not session_id:
        return "manual"
    return re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:100]


def write_session_marker(session_id, dry_run=False):
    """Write a session marker file for the given session_id.

    If session_id is empty, uses 'manual' as the marker name.
    The marker file contains JSON with pid and created timestamp.
    """
    if dry_run:
        print(f"[dry-run] would write session marker for {marker_name(session_id)}")
        return

    sessions_dir = signal_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)

    name = marker_name(session_id)
    marker_path = sessions_dir / name
    now = datetime.now(timezone.utc).isoformat()
    pid = find_claude_pid()
    marker_data = {"pid": pid, "created": now}
    marker_path.write_text(json.dumps(marker_data))


def remove_session_marker(session_id, dry_run=False):
    """Remove the session marker file for the given session_id.

    If session_id is empty, removes the 'manual' marker.
    Returns True if a marker was removed, False if none existed.
    """
    if dry_run:
        print(f"[dry-run] would remove session marker for {marker_name(session_id)}")
        return False

    sessions_dir = signal_sessions_dir()
    name = marker_name(session_id)
    marker_path = sessions_dir / name

    if marker_path.exists():
        marker_path.unlink()
        return True
    return False


def _marker_is_stale(marker_path, now, max_age_hours):
    """Check if a session marker is stale (dead pid or too old).

    Returns True if the marker is stale, False if it's still active.
    """
    try:
        content = marker_path.read_text().strip()
        # Try to parse as JSON (new format with pid)
        try:
            marker_data = json.loads(content)
            pid = marker_data.get("pid")
            created_str = marker_data.get("created", content)
        except json.JSONDecodeError:
            # Old format: just an ISO timestamp
            pid = None
            created_str = content

        marker_time = datetime.fromisoformat(created_str)
        age_hours = (now - marker_time).total_seconds() / 3600

        # Check if pid is dead
        if pid is not None and not pid_alive(pid):
            return True
        if age_hours > max_age_hours:
            return True
        return False
    except (ValueError, TypeError, AttributeError, OSError):
        # Corrupt marker, treat as stale. TypeError for naive vs aware
        # datetime subtraction; AttributeError for JSON that is null or
        # a number (no .get method).
        return True


def get_active_session_markers(max_age_hours=None):
    """Get a list of non-stale session marker names.

    A marker is stale if its pid is dead OR it is older than max_age_hours.
    If max_age_hours is None, uses the default.
    Returns a list of session_id strings (or 'manual').
    """
    if max_age_hours is None:
        max_age_hours = MARKER_MAX_AGE_HOURS_DEFAULT

    sessions_dir = signal_sessions_dir()
    if not sessions_dir.exists():
        return []

    now = datetime.now(timezone.utc)
    active = []
    stale = []

    for marker_path in sessions_dir.iterdir():
        if not marker_path.is_file():
            continue
        if _marker_is_stale(marker_path, now, max_age_hours):
            stale.append(marker_path)
        else:
            active.append(marker_path.name)

    # Delete stale markers
    for marker_path in stale:
        try:
            marker_path.unlink()
        except OSError:
            pass

    return active


def has_other_active_markers(session_id, max_age_hours=None):
    """Check if there are other active session markers besides the given one.

    Returns True if other sessions still have active markers.
    """
    active = get_active_session_markers(max_age_hours)
    name = marker_name(session_id)
    # Remove our own marker from the list
    if name in active:
        active.remove(name)
    return len(active) > 0


def delete_all_session_markers(dry_run=False):
    """Delete all session marker files.

    Called after a successful restore to ensure no leftover markers
    block future clears.
    """
    if dry_run:
        print("[dry-run] would delete all session markers")
        return

    sessions_dir = signal_sessions_dir()
    if not sessions_dir.exists():
        return

    for marker_path in sessions_dir.iterdir():
        if marker_path.is_file():
            try:
                marker_path.unlink()
            except OSError:
                pass


def sweep_stale_markers(max_age_hours=None, dry_run=False):
    """Delete stale session markers (dead pid or too old).

    Returns the number of stale markers deleted.
    """
    if max_age_hours is None:
        max_age_hours = MARKER_MAX_AGE_HOURS_DEFAULT

    sessions_dir = signal_sessions_dir()
    if not sessions_dir.exists():
        return 0

    now = datetime.now(timezone.utc)
    stale_count = 0

    for marker_path in sessions_dir.iterdir():
        if not marker_path.is_file():
            continue
        if _marker_is_stale(marker_path, now, max_age_hours):
            if not dry_run:
                try:
                    marker_path.unlink()
                except OSError:
                    pass
            stale_count += 1

    return stale_count


def sweep_and_restore(config_path=None, dry_run=False):
    """Sweep stale markers and restore if no active markers remain.

    Sweeps stale markers (dead pid or too old). If a signal is active and
    no active markers remain (including when the sweep count is 0), restores
    the lights exactly like a normal clear.

    Returns True if a restore happened, False otherwise.
    """
    if config_path is None:
        config_path = str(Path(__file__).parent / "config.json")

    cfg = load_config(config_path)
    signal_cfg = get_signal_config(cfg)
    max_age_hours = signal_cfg.get("marker_max_age_hours", MARKER_MAX_AGE_HOURS_DEFAULT)

    stale_count = sweep_stale_markers(max_age_hours, dry_run=dry_run)

    signal_path = arbiter.signal_file()
    if not signal_path.exists():
        # No signal active, nothing to restore
        if stale_count > 0:
            log_signal_event("clear", f"stale-swept n={stale_count}")
            print(f"clear stale-swept n={stale_count}")
        return False

    # Check if any active markers remain
    active = get_active_session_markers(max_age_hours)
    if active:
        # Other sessions still waiting
        if stale_count > 0:
            log_signal_event("clear", f"stale-swept n={stale_count}")
            print(f"clear stale-swept n={stale_count}")
        return False

    # No active markers remain, restore
    devices = cfg.get("devices", [])
    if not devices:
        print("no devices in config", file=sys.stderr)
        return False

    default_cfg = cfg.get("default")

    if not acquire_lock(dry_run=dry_run):
        log_signal_event("clear", "lock-timeout")
        return False

    try:
        # Re-check under the lock
        if not signal_path.exists():
            log_signal_event("clear", "no-signal")
            print("no active signal; nothing to do")
            return False

        # Re-check for active markers under the lock (race condition fix).
        # A needs-input command may have written saved_state.json but not yet
        # its session marker; if we restored now we'd clear a signal that's
        # being set right now.
        active = get_active_session_markers(max_age_hours)
        if active:
            if stale_count > 0:
                log_signal_event("clear", f"stale-swept n={stale_count}")
                print(f"clear stale-swept n={stale_count}")
            return False

        saved = load_saved_state()
        try:
            restore_state(devices, signal_cfg, cfg, default_cfg=default_cfg, dry_run=dry_run, saved=saved)
        except OSError as e:
            print(f"warning: could not restore lights: {e}", file=sys.stderr)
            log_signal_event("clear", "oserror")
            return False
        delete_saved_state(dry_run=dry_run, quiet=not saved)
        delete_all_session_markers(dry_run=dry_run)
        log_signal_event("clear", "applied")
        print("signal cleared")
        return True
    finally:
        release_lock(dry_run=dry_run)


def is_unattended(env=None):
    """Check if the current session is unattended (background/dispatcher).

    Returns True when CLAUDE_CODE_SESSION_ATTENDED is set to "0".
    """
    if env is None:
        env = os.environ
    return env.get("CLAUDE_CODE_SESSION_ATTENDED") == "0"


def read_hook_input():
    """Read hook input JSON from stdin if available.

    Returns a dict with session_id, message, and notification_type if present,
    or an empty dict. Never fails if stdin is empty or not JSON.
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
            "notification_type": data.get("notification_type", ""),
        }
    except (json.JSONDecodeError, OSError):
        return {}


def log_signal_event(command, action, hook_input=None):
    """Append a log line to state/signal.log.

    Format: ISO timestamp, command, action, session_id, message, notification_type.
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
        notification_type = ""
        if hook_input:
            session_id = hook_input.get("session_id", "")
            message = hook_input.get("message", "")
            notification_type = hook_input.get("notification_type", "")

        line = f"{now} {command} {action}"
        if session_id:
            line += f" session={session_id}"
        if message:
            line += f" msg={message}"
        if notification_type:
            line += f" type={notification_type}"
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


def should_ignore_message(message, signal_cfg):
    """Check if a message matches any ignore pattern.

    Returns True if the message should be ignored (no signal).
    Invalid regex patterns are skipped with a warning to stderr.
    """
    patterns = signal_cfg.get("ignore_message_patterns", DEFAULT_SIGNAL["ignore_message_patterns"])
    for pattern in patterns:
        try:
            if re.search(pattern, message):
                return True
        except re.error as e:
            print(f"warning: invalid ignore pattern {pattern!r}: {e}", file=sys.stderr)
    return False


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
    answered = 0
    skipped = 0
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
            answered += 1
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
                skipped += 1
                print(f"info: {ip} already shows the signal colour; not saving it (clear will apply the default)", file=sys.stderr)
        else:
            print(f"warning: no status response from {ip}", file=sys.stderr)

    if answered == 0:
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


def restore_state(devices, signal_cfg, cfg, default_cfg=None, dry_run=False, saved=None):
    """Restore saved state. Returns True if state was restored, False if none.

    If saved is None, loads it from the saved state file.
    If the current mode is "off", turns all devices off instead of restoring.
    """
    if saved is None:
        saved = load_saved_state()

    if saved is not None:
        # Check current mode: if "off", turn all devices off instead of restoring
        mode = arbiter.get_mode()
        if mode == "off":
            if dry_run:
                for dev in devices:
                    print(f"[dry-run] would turn off {dev['ip']}")
            else:
                for attempt in range(3):
                    for dev in devices:
                        ip = dev["ip"]
                        try:
                            govee.turn(ip, False)
                        except OSError as e:
                            print(f"warning: failed to turn off {ip}: {e}", file=sys.stderr)
                    if attempt < 2:
                        time.sleep(0.2)
            print("mode is off; strips turned off")
            return True

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
    session_id = hook_input.get("session_id", "")
    message = hook_input.get("message", "")

    cfg = load_config(args.config)
    signal_cfg = get_signal_config(cfg)

    # Check if message matches any ignore pattern (before unattended check)
    # --force does NOT bypass this
    if message and should_ignore_message(message, signal_cfg):
        log_signal_event("needs-input", "skipped-ignored", hook_input)
        return

    # Check if unattended and not forced
    if not args.force and is_unattended():
        include_unattended = signal_cfg.get("include_unattended", False)
        if not include_unattended:
            log_signal_event("needs-input", "skipped-unattended", hook_input)
            return

    # Check if mode is "off" — off means dark, including the signal
    if arbiter.get_mode() == "off":
        log_signal_event("needs-input", "skipped-off", hook_input)
        return

    devices = cfg.get("devices", [])
    if not devices:
        print("no devices in config", file=sys.stderr)
        sys.exit(1)

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
        # Re-check mode under the lock (race condition fix)
        if arbiter.get_mode() == "off":
            log_signal_event("needs-input", "skipped-off", hook_input)
            return

        # Re-check under the lock (race condition fix)
        if not signal_path.exists() or args.dry_run:
            save_state(devices, signal_cfg, dry_run=args.dry_run)

        # Write session marker
        write_session_marker(session_id, dry_run=args.dry_run)

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
    session_id = hook_input.get("session_id", "")
    signal_path = arbiter.signal_file()

    # Handle --stale flag: sweep stale markers and restore if none remain
    stale_flag = getattr(args, "stale", False)
    if stale_flag is True:
        sweep_and_restore(config_path=args.config, dry_run=args.dry_run)
        return

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
    max_age_hours = signal_cfg.get("marker_max_age_hours", MARKER_MAX_AGE_HOURS_DEFAULT)

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

        # Remove this session's marker
        removed = remove_session_marker(session_id, dry_run=args.dry_run)

        # Check if other sessions still have active markers
        if not args.all and has_other_active_markers(session_id, max_age_hours):
            # Other sessions still waiting, keep the signal
            log_signal_event("clear", "kept-other-sessions", hook_input)
            print("signal kept (other sessions still waiting)")
            return

        # Load saved state once, without quiet, so warnings go to stderr
        saved = load_saved_state()

        try:
            restore_state(devices, signal_cfg, cfg, default_cfg=default_cfg, dry_run=args.dry_run, saved=saved)
        except OSError as e:
            print(f"warning: could not restore lights: {e}", file=sys.stderr)
            log_signal_event("clear", "oserror", hook_input)
            return
        delete_saved_state(dry_run=args.dry_run, quiet=not saved)
        # Delete all session markers so a future needs-input/clear cycle
        # isn't blocked by leftover markers from this cycle.
        delete_all_session_markers(dry_run=args.dry_run)
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
    parser.add_argument(
        "--all",
        action="store_true",
        help="clear all session markers and restore lights (manual escape hatch)",
    )
    parser.add_argument(
        "--stale",
        action="store_true",
        help="delete stale session markers (dead pid or too old) and restore if none remain",
    )

    args = parser.parse_args()

    if args.command == "needs-input":
        cmd_needs_input(args)
    elif args.command == "clear":
        cmd_clear(args)


if __name__ == "__main__":
    main()
