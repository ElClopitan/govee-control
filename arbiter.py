"""Light-source priority arbiter.

Determines which light source (agent signal, game sync, weather sync)
should control the lights based on file-based state.

Priority: agent signal > game sync > weather sync.

State files:
- state/saved_state.json: exists when agent signal is active
- state/game_active.json: exists when game sync is active, contains {"profile": "<name>"}
  The file's mtime is used as a heartbeat; if it's older than GAME_STALE_SECONDS,
  game_active() returns False so weather sync can resume.
"""

import json
import time
from pathlib import Path

STATE_DIR = Path(__file__).parent / "state"

# game_active.json must be rewritten at least this often (by game_sync's loop)
# or it's considered stale and weather sync takes over.
GAME_STALE_SECONDS = 60

# Built-in default profile used when config has no "default" key or it is null.
# Used by game_sync (when no game is running) and agent_signal (when restoring
# a device that had no saved state).
BUILTIN_DEFAULT = {"color": "white", "brightness": 40}


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
