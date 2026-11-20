#!/usr/bin/env python3
"""Windows tray icon for Govee mode switching.

Right-click the tray icon to pick Off / Weather / Game / Music.
The icon colour reflects the current mode.
"""

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import arbiter
import govee
import mode

MODE_LABELS = [("off", "Off"), ("weather", "Weather"), ("game", "Game"), ("music", "Music")]
MODE_COLOURS = {
    "off": (128, 128, 128),
    "weather": (40, 120, 255),
    "game": (220, 40, 200),
    "music": (40, 200, 80),
}


def log_path():
    """Return the path to the tray log file."""
    return arbiter.STATE_DIR / "tray.log"


def log(msg):
    """Append a timestamped line to the tray log."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def choose(mode_name, config_path, icon):
    """Switch to the given mode, logging errors but never raising."""
    try:
        if mode_name == "off":
            config = govee.load_config(config_path)
        else:
            config = None
        mode.switch(mode_name, config)
    except Exception as e:
        log(f"switch to {mode_name} failed: {e}")
    refresh(icon)


def refresh(icon):
    """Update the icon's title, image, and menu to reflect the current mode."""
    m = arbiter.get_mode()
    icon.title = f"Govee: {m}"
    icon.icon = make_icon_image(m)
    icon.update_menu()


def make_icon_image(mode_name):
    """Create a 64x64 RGBA icon image with a filled circle in the mode's colour."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    colour = MODE_COLOURS[mode_name]
    draw.ellipse([8, 8, 56, 56], fill=colour)
    return img


def build_menu(pystray, config_path):
    """Build the right-click context menu."""
    items = []
    for mode_name, label in MODE_LABELS:
        checked = lambda item, m=mode_name: arbiter.get_mode() == m
        action = lambda icon, item, m=mode_name: choose(m, config_path, icon)
        items.append(pystray.MenuItem(label, action, checked=checked, radio=True))
    items.append(pystray.Menu.SEPARATOR)
    items.append(pystray.MenuItem("Quit", lambda icon, item: icon.stop()))
    return pystray.Menu(*items)


def poll(icon, stop_event, interval=5.0):
    """Periodically refresh the icon to reflect mode changes made elsewhere."""
    while not stop_event.wait(interval):
        try:
            refresh(icon)
        except Exception as e:
            log(f"poll refresh failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Govee tray icon")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.json"),
        help="path to config.json",
    )
    args = parser.parse_args()

    try:
        import pystray
    except ImportError:
        print("tray needs: python -m pip install --user -r requirements-tray.txt", file=sys.stderr)
        sys.exit(1)

    m = arbiter.get_mode()
    icon = pystray.Icon(
        "govee",
        make_icon_image(m),
        f"Govee: {m}",
        build_menu(pystray, args.config),
    )

    stop_event = threading.Event()
    poll_thread = threading.Thread(target=poll, args=(icon, stop_event), daemon=True)
    poll_thread.start()

    icon.run()
    stop_event.set()


if __name__ == "__main__":
    main()
