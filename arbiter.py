"""Light-source priority arbiter.

Determines which light source (agent signal, music sync, game sync, weather sync)
should control the lights based on file-based state.

Priority: agent signal > music sync > game sync > weather sync.

State files:
- state/saved_state.json: exists when agent signal is active
- state/music_active.json: exists when music sync is active, contains {"pid": <pid>, "since": <ts>}
  The file's mtime is used as a heartbeat; if it's older than MUSIC_STALE_SECONDS,
  music_active() returns False so game/weather sync can resume.
- state/game_active.json: exists when game sync is active, contains {"profile": "<name>"}
  The file's mtime is used as a heartbeat; if it's older than GAME_STALE_SECONDS,
  game_active() returns False so weather sync can resume.
- state/mode.json: contains {"mode": "<mode>"} where mode is one of off/weather/game/music.
  The owner picks ONE mode by hand; only that mode may drive the strips.
"""

import json
import os
import threading
import time
from pathlib import Path

STATE_DIR = Path(__file__).parent / "state"

# game_active.json must be rewritten at least this often (by game_sync's loop)
# or it's considered stale and weather sync takes over.
GAME_STALE_SECONDS = 60

# music_active.json must be rewritten at least this often (by music_sync's loop)
# or it's considered stale and game/weather sync takes over.
MUSIC_STALE_SECONDS = 15

# Built-in default profile used when config has no "default" key or it is null.
# Used by game_sync (when no game is running) and agent_signal (when restoring
# a device that had no saved state).
BUILTIN_DEFAULT = {"color": "white", "brightness": 40}

# Default maximum brightness for automatic scripts (agent signal, game sync,
# weather sync). Manual CLI brightness commands are not capped.
MAX_BRIGHTNESS_DEFAULT = 80

# Mode switch: the owner picks ONE mode by hand.
# Only that mode may drive the strips (agent signal stays above everything).
MODES = ("off", "weather", "game", "music")


def cap_brightness(value, cfg, allow_flash=False):
    """Cap brightness to the configured maximum.

    Args:
        value: The requested brightness (0-100).
        cfg: The loaded config dict.
        allow_flash: If True, skip the cap (for explicit flashes like thunderstorms).

    Returns:
        The capped brightness, clamped to 1..100.
    """
    if allow_flash:
        return max(1, min(100, value))

    max_b = cfg.get("max_brightness", MAX_BRIGHTNESS_DEFAULT)
    if not isinstance(max_b, int):
        max_b = MAX_BRIGHTNESS_DEFAULT

    return max(1, min(100, min(value, max_b)))


def signal_file():
    """Return the path to the signal state file.

    This is the single source of truth for the signal file path,
    used by both arbiter and agent_signal.
    """
    return STATE_DIR / "saved_state.json"


def signal_active():
    """Check if agent signal is active.

    Returns True if state/saved_state.json exists.
    """
    return signal_file().exists()


def game_active():
    """Check if game sync is active.

    Returns True if state/game_active.json exists AND its mtime is within
    GAME_STALE_SECONDS. A stale file (e.g. left behind by a crashed game_sync)
    does not block weather sync.
    """
    path = STATE_DIR / "game_active.json"
    if not path.exists():
        return False
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    return time.time() - mtime <= GAME_STALE_SECONDS


def set_game_active(profile_name):
    """Mark game sync as active with the given profile name.

    Creates state directory if needed and writes game_active.json.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / "game_active.json", "w") as f:
        json.dump({"profile": profile_name}, f)


def clear_game_active():
    """Mark game sync as inactive.

    Deletes game_active.json if present; no error if missing.
    """
    path = STATE_DIR / "game_active.json"
    if path.exists():
        path.unlink()


def music_file():
    """Return the path to the music active state file."""
    return STATE_DIR / "music_active.json"


def music_active():
    """Check if music sync is active.

    Returns True if state/music_active.json exists, is valid JSON, and its mtime
    is within MUSIC_STALE_SECONDS. A stale or corrupt file (e.g. left behind by
    a crashed music_sync) does not block game or weather sync.
    """
    path = music_file()
    if not path.exists():
        return False
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    if time.time() - mtime > MUSIC_STALE_SECONDS:
        return False
    # Validate JSON content; a corrupt file means the process crashed mid-write
    try:
        with open(path, "r") as f:
            json.load(f)
    except (ValueError, OSError):
        return False
    return True


def set_music_active():
    """Mark music sync as active.

    Creates state directory if needed and writes music_active.json with
    the current process ID and timestamp. The file's mtime serves as the
    heartbeat that music_active() checks.

    Writes atomically via temp file + os.replace() so readers never see
    a partially-written or empty file.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    target = music_file()
    tmp = target.with_name(f"music_active.json.tmp.{os.getpid()}")
    with open(tmp, "w") as f:
        json.dump({"pid": os.getpid(), "since": time.time()}, f)
        f.flush()
        os.fsync(f.fileno())
    # Atomic replace; retry on Windows PermissionError (reader has file open)
    for attempt in range(3):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt < 2:
                time.sleep(0.01)
            else:
                # Fall back: update mtime of existing file
                if target.exists():
                    os.utime(target, None)
                else:
                    raise
                # Clean up the temp file that couldn't be replaced
                tmp.unlink(missing_ok=True)


def clear_music_active():
    """Mark music sync as inactive.

    Deletes music_active.json if present; no error if missing.
    """
    path = music_file()
    if path.exists():
        path.unlink()


def mode_file():
    """Return the path to the mode state file."""
    return STATE_DIR / "mode.json"


def get_mode():
    """Get the current mode from mode.json.

    Returns the mode string ("off", "weather", "game", or "music").
    Missing file, unreadable file, bad JSON, wrong shape, or unknown mode
    all return "off". Never raises.

    On Windows, if a reader opens mode.json while set_mode() is doing
    os.replace(), it gets PermissionError. Retry up to 5 times with a
    short sleep between tries before giving up.
    """
    path = mode_file()
    if not path.exists():
        return "off"
    for attempt in range(5):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except PermissionError:
            if attempt < 4:
                time.sleep(0.01)
                continue
            return "off"
        except (ValueError, OSError):
            return "off"
        if not isinstance(data, dict):
            return "off"
        mode = data.get("mode")
        if mode not in MODES:
            return "off"
        return mode
    return "off"


def set_mode(mode):
    """Set the current mode.

    Args:
        mode: One of "off", "weather", "game", "music".

    Raises:
        ValueError: If mode is not in MODES.
        PermissionError: If os.replace fails after 3 retries.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    target = mode_file()
    # Thread-unique temp name so concurrent set_mode calls don't collide
    tmp = target.with_name(f"mode.json.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        with open(tmp, "w") as f:
            json.dump({"mode": mode}, f)
            f.flush()
            os.fsync(f.fileno())
        # Atomic replace; retry on Windows PermissionError (reader has file open)
        for attempt in range(3):
            try:
                os.replace(tmp, target)
                return
            except PermissionError:
                if attempt < 2:
                    time.sleep(0.01)
                else:
                    # All retries failed; clean up and re-raise
                    tmp.unlink(missing_ok=True)
                    raise
    except BaseException:
        # Clean up temp file on any failure (disk full, fsync error, etc.)
        tmp.unlink(missing_ok=True)
        raise


def weather_blocked():
    """Check if weather sync should be blocked.

    Returns True if an agent signal is active or the selected mode is not "weather".
    This is the single place where weather sync checks for blocking.
    """
    return signal_active() or get_mode() != "weather"


def game_blocked():
    """Check if game sync should be blocked.

    Returns True if an agent signal is active or the selected mode is not "game".
    This is the single place where game sync checks for blocking.
    """
    return signal_active() or get_mode() != "game"
