"""Light-source priority arbiter.

Determines which light source (agent signal, game sync, weather sync)
should control the lights based on file-based state.

Priority: agent signal > game sync > weather sync.

State files:
- state/saved_state.json: exists when agent signal is active
- state/game_active.json: exists when game sync is active, contains {"profile": "<name>"}
"""

import json
from pathlib import Path

STATE_DIR = Path(__file__).parent / "state"


def signal_active():
    """Check if agent signal is active.

    Returns True if state/saved_state.json exists.
    """
    return (STATE_DIR / "saved_state.json").exists()


def game_active():
    """Check if game sync is active.

    Returns True if state/game_active.json exists.
    """
    return (STATE_DIR / "game_active.json").exists()


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
