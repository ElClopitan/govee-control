#!/usr/bin/env python3
"""Music-reactive lighting.

Captures system audio via WASAPI loopback (Windows) or PulseAudio (Linux),
analyzes frequency bands, and maps them to colours sent to Govee strips.

Config keys (in config.json):
  "music": {
    "fps": 10,
    "smoothing": 0.5
  }

Usage:
  python music_sync.py [--config PATH] [--fps N] [--verbose] [--log-file PATH]
  python music_sync.py start
  python music_sync.py stop
  python music_sync.py toggle
  python music_sync.py status
"""

import argparse
import json
import logging
import logging.handlers
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import arbiter
import govee

# Heartbeat interval: refresh music_active.json at least this often
HEARTBEAT_INTERVAL = 5.0

logger = logging.getLogger(__name__)

# Default frame rate (frames per second)
DEFAULT_FPS = 10
MIN_FPS = 2
MAX_FPS = 20

# Smoothing factor for exponential moving average (0..1, higher = smoother)
DEFAULT_SMOOTHING = 0.5

# Minimum colour change threshold (Euclidean distance in RGB space)
# to send a new frame. Prevents flicker from tiny changes.
COLOR_CHANGE_THRESHOLD = 15

# Rate-limit interval for error logs (seconds)
ERROR_LOG_INTERVAL = 60

# State files for background process management
STATE_DIR = Path(__file__).parent / "state"
PID_FILE = STATE_DIR / "music_sync.pid"
STOP_FLAG_FILE = STATE_DIR / "music_stop"
LOG_FILE = STATE_DIR / "music_sync.log"


def analyze(samples, rate):
    """Analyze audio samples and return frequency band levels.

    Args:
        samples: List or array of float samples (mono mixdown).
        rate: Sample rate in Hz.

    Returns:
        dict with keys: level (0..1), bass (0..1), mid (0..1), treble (0..1)
    """
    n = len(samples)
    if n == 0:
        return {"level": 0.0, "bass": 0.0, "mid": 0.0, "treble": 0.0}

    # Try numpy FFT first
    try:
        import numpy as np
        return _analyze_numpy(samples, rate, n)
    except ImportError:
        pass

    # Pure-Python DFT fallback (good enough for 1024 samples)
    return _analyze_pure_python(samples, rate, n)


def _analyze_numpy(samples, rate, n):
    """FFT-based analysis using numpy."""
    import numpy as np

    arr = np.array(samples, dtype=np.float64)

    # Compute overall level (RMS)
    rms = np.sqrt(np.mean(arr ** 2))
    level = min(1.0, rms * 10.0)  # Scale to 0..1

    # FFT
    fft = np.fft.rfft(arr)
    magnitudes = np.abs(fft)
    freqs = np.fft.rfftfreq(n, d=1.0 / rate)

    # Band ranges (Hz)
    bass_mask = (freqs >= 20) & (freqs < 250)
    mid_mask = (freqs >= 250) & (freqs < 4000)
    treble_mask = (freqs >= 4000) & (freqs < 16000)

    bass = np.mean(magnitudes[bass_mask]) if np.any(bass_mask) else 0.0
    mid = np.mean(magnitudes[mid_mask]) if np.any(mid_mask) else 0.0
    treble = np.mean(magnitudes[treble_mask]) if np.any(treble_mask) else 0.0

    # Normalize bands to 0..1 relative to max
    max_band = max(bass, mid, treble, 1e-10)
    bass = min(1.0, bass / max_band)
    mid = min(1.0, mid / max_band)
    treble = min(1.0, treble / max_band)

    return {"level": level, "bass": bass, "mid": mid, "treble": treble}


def _analyze_pure_python(samples, rate, n):
    """Pure-Python DFT fallback for analysis.

    Uses a small number of DFT bins to estimate band energies.
    Good enough for 1024 samples without numpy.
    """
    # Compute overall level (RMS)
    sum_sq = 0.0
    for s in samples:
        sum_sq += s * s
    rms = math.sqrt(sum_sq / n)
    level = min(1.0, rms * 10.0)

    # DFT at specific frequencies to estimate band energies
    # Bass: 100 Hz, Mid: 1000 Hz, Treble: 8000 Hz
    bass_freq = 100.0
    mid_freq = 1000.0
    treble_freq = 8000.0

    bass_energy = _dft_magnitude(samples, bass_freq, rate, n)
    mid_energy = _dft_magnitude(samples, mid_freq, rate, n)
    treble_energy = _dft_magnitude(samples, treble_freq, rate, n)

    # Normalize to 0..1
    max_energy = max(bass_energy, mid_energy, treble_energy, 1e-10)
    bass = min(1.0, bass_energy / max_energy)
    mid = min(1.0, mid_energy / max_energy)
    treble = min(1.0, treble_energy / max_energy)

    return {"level": level, "bass": bass, "mid": mid, "treble": treble}


def _dft_magnitude(samples, freq, rate, n):
    """Compute DFT magnitude at a specific frequency."""
    real = 0.0
    imag = 0.0
    for i, s in enumerate(samples):
        angle = 2.0 * math.pi * freq * i / rate
        real += s * math.cos(angle)
        imag -= s * math.sin(angle)
    return math.sqrt(real * real + imag * imag)


def features_to_rgb(features, cfg):
    """Map audio features to RGB colour.

    Args:
        features: dict with level, bass, mid, treble (all 0..1)
        cfg: config dict (for max_brightness)

    Returns:
        (r, g, b) tuple with values 0..255
    """
    level = features["level"]
    bass = features["bass"]
    mid = features["mid"]
    treble = features["treble"]

    # Hue mapping: bass -> red/magenta, mid -> green/yellow, treble -> blue/cyan
    # Use weighted blend of band colours
    # Bass: red (255, 0, 128)
    # Mid: green (0, 255, 128)
    # Treble: blue (128, 0, 255)

    r = bass * 255.0 + treble * 128.0
    g = mid * 255.0 + bass * 0.0
    b = treble * 255.0 + mid * 128.0

    # Scale by overall level (with a dark floor of 10%)
    scale = 0.1 + 0.9 * level
    r = r * scale
    g = g * scale
    b = b * scale

    # Clamp to 0..255
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))

    # Ensure never all-zero (dark floor)
    if r == 0 and g == 0 and b == 0:
        r, g, b = 25, 25, 25

    return (r, g, b)


def smooth_features(prev, curr, alpha):
    """Exponential moving average smoothing of features.

    Args:
        prev: Previous features dict (or None)
        curr: Current features dict
        alpha: Smoothing factor (0..1, higher = less smoothing)

    Returns:
        Smoothed features dict
    """
    if prev is None:
        return dict(curr)

    result = {}
    for key in ["level", "bass", "mid", "treble"]:
        result[key] = prev[key] * (1.0 - alpha) + curr[key] * alpha
    return result


def color_distance(c1, c2):
    """Euclidean distance between two RGB colours."""
    dr = c1[0] - c2[0]
    dg = c1[1] - c2[1]
    db = c1[2] - c2[2]
    return math.sqrt(dr * dr + dg * dg + db * db)


def _ensure_state_dir():
    """Create state directory if it doesn't exist."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _is_process_alive(pid):
    """Check if a process with the given PID is alive (Windows)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and str(pid) in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def _get_running_pid():
    """Get the PID of the running music_sync process, or None.

    Checks: pid file exists, process is alive, and arbiter.music_active() is true.
    Cleans up stale pid files.
    """
    if not PID_FILE.exists():
        return None

    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        # Corrupt or unreadable pid file
        PID_FILE.unlink(missing_ok=True)
        return None

    if not _is_process_alive(pid):
        # Process is dead; clean up
        PID_FILE.unlink(missing_ok=True)
        arbiter.clear_music_active()
        return None

    if not arbiter.music_active():
        # Process alive but heartbeat stale
        PID_FILE.unlink(missing_ok=True)
        arbiter.clear_music_active()
        return None

    return pid


def _write_pid(pid):
    """Write the PID to the pid file."""
    _ensure_state_dir()
    PID_FILE.write_text(str(pid))


def _remove_pid():
    """Remove the pid file."""
    PID_FILE.unlink(missing_ok=True)


def _remove_stop_flag():
    """Remove the stop flag file."""
    STOP_FLAG_FILE.unlink(missing_ok=True)


def _raise_stop_flag():
    """Create the stop flag file to signal the running process to stop."""
    _ensure_state_dir()
    STOP_FLAG_FILE.write_text(str(time.time()))


def cmd_start():
    """Start music sync as a background process."""
    pid = _get_running_pid()
    if pid is not None:
        print(f"music mode already ON (pid {pid})")
        return 0

    _ensure_state_dir()
    _remove_stop_flag()

    # Find pythonw.exe next to sys.executable, fall back to sys.executable
    python_exe = sys.executable
    pythonw_exe = None
    if os.name == "nt":
        exe_dir = Path(python_exe).parent
        candidate = exe_dir / "pythonw.exe"
        if candidate.exists():
            pythonw_exe = str(candidate)

    if pythonw_exe is None:
        pythonw_exe = python_exe

    # Build command
    cmd = [
        pythonw_exe,
        str(Path(__file__).resolve()),
        "--log-file",
        str(LOG_FILE),
    ]

    # Start detached on Windows
    if os.name == "nt":
        CREATE_NO_WINDOW = 0x08000000
        DETACHED_PROCESS = 0x00000008
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        proc = subprocess.Popen(
            cmd,
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            startupinfo=startupinfo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    _write_pid(proc.pid)
    print(f"music mode ON (pid {proc.pid})")
    return 0


def cmd_stop():
    """Stop the running music sync process."""
    pid = _get_running_pid()
    if pid is None:
        print("music mode OFF")
        return 0

    # Signal the process to stop via flag file
    _raise_stop_flag()

    # Wait up to 5 seconds for it to exit
    for _ in range(50):
        if not _is_process_alive(pid):
            break
        time.sleep(0.1)

    # If still alive, force kill
    if _is_process_alive(pid):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid)],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Clean up
    _remove_pid()
    _remove_stop_flag()
    arbiter.clear_music_active()
    print("music mode OFF")
    return 0


def cmd_toggle():
    """Toggle music sync on/off."""
    pid = _get_running_pid()
    if pid is not None:
        return cmd_stop()
    else:
        return cmd_start()


def cmd_status():
    """Show music sync status."""
    pid = _get_running_pid()
    if pid is not None:
        print(f"music mode ON (pid {pid})")
    else:
        print("music mode OFF")
    return 0


def run(config, fps=None, verbose=False, log_file=None, time_fn=None):
    """Run the music sync loop.

    Args:
        config: Loaded config dict
        fps: Frames per second (None = use config default)
        verbose: Enable verbose logging
        log_file: Path to log file (None = stdout)
        time_fn: Optional time function for testability
    """
    if time_fn is None:
        time_fn = time.time

    # Setup logging
    log_level = logging.DEBUG if verbose else logging.INFO
    if log_file:
        handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=2
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(log_level)
    else:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(levelname)s %(message)s",
        )

    # Get music config
    music_cfg = config.get("music", {})
    if fps is None:
        fps = music_cfg.get("fps", DEFAULT_FPS)
    fps = max(MIN_FPS, min(MAX_FPS, fps))
    smoothing = music_cfg.get("smoothing", DEFAULT_SMOOTHING)

    devices = config.get("devices", [])
    if not devices:
        logger.error("No devices configured")
        sys.exit(1)

    # Try to import soundcard/numpy
    try:
        import soundcard as sc
        import numpy as np
    except ImportError:
        print("music mode needs: python -m pip install --user -r requirements-music.txt")
        sys.exit(2)

    # Find default microphone (loopback)
    mics = sc.all_microphones(include_loopback=True)
    if not mics:
        logger.error("No audio input devices found")
        sys.exit(1)

    # Prefer loopback device
    loopback = None
    for mic in mics:
        if "loopback" in mic.name.lower() or "stereo mix" in mic.name.lower():
            loopback = mic
            break
    if loopback is None:
        loopback = mics[0]

    logger.info("Using audio device: %s", loopback.name)

    # Record initial state for restoration
    initial_states = []
    for dev in devices:
        ip = dev["ip"]
        try:
            resp = govee.status(ip, timeout=2)
            if resp:
                initial_states.append({"ip": ip, "state": resp})
                logger.info("Recorded initial state for %s", ip)
            else:
                logger.warning("No response from %s, will not restore", ip)
                initial_states.append({"ip": ip, "state": None})
        except OSError as e:
            logger.warning("Failed to get status from %s: %s", ip, e)
            initial_states.append({"ip": ip, "state": None})

    # Set brightness once at start
    brightness = arbiter.cap_brightness(80, config)
    for dev in devices:
        ip = dev["ip"]
        try:
            govee.brightness(ip, brightness)
            logger.info("Set brightness %d on %s", brightness, ip)
        except OSError as e:
            logger.error("Failed to set brightness on %s: %s", ip, e)

    # Analysis parameters
    sample_rate = 44100
    frame_duration = 1.0 / fps
    samples_per_frame = int(sample_rate * frame_duration)

    # Smoothing state
    prev_features = None
    last_color = None
    last_frame_time = {}
    last_error_time = None
    last_heartbeat_time = 0.0
    signal_was_active = False

    logger.info("Music sync started (fps=%d, smoothing=%.2f)", fps, smoothing)
    logger.info("Press Ctrl+C to stop")

    # Mark music sync as active
    arbiter.set_music_active()

    try:
        while True:
            frame_start = time_fn()

            # Check for stop flag first (before signal check) so stop works
            # even while an agent signal is active
            if STOP_FLAG_FILE.exists():
                logger.info("stop flag detected; exiting")
                break

            # Refresh heartbeat at least every HEARTBEAT_INTERVAL seconds
            if frame_start - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                arbiter.set_music_active()
                last_heartbeat_time = frame_start

            # Check signal priority: if agent signal is active, don't send frames
            if arbiter.signal_active():
                if not signal_was_active:
                    logger.info("signal active; pausing music sync")
                signal_was_active = True
                # Don't send any frames while signal is active
                # Sleep to maintain frame rate
                elapsed = time_fn() - frame_start
                sleep_time = frame_duration - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                continue

            signal_was_active = False

            # Capture audio
            try:
                with loopback.recorder(samplerate=sample_rate, channels=1) as rec:
                    raw = rec.record(numframes=samples_per_frame)
            except OSError as e:
                if last_error_time is None or (frame_start - last_error_time) >= ERROR_LOG_INTERVAL:
                    logger.error("Audio capture error: %s", e)
                    last_error_time = frame_start
                time.sleep(frame_duration)
                continue

            # Mixdown to mono if needed
            if raw.ndim > 1 and raw.shape[1] > 1:
                samples = np.mean(raw, axis=1)
            else:
                samples = raw.flatten()

            # Normalize to -1..1
            if samples.dtype == np.int16:
                samples = samples.astype(np.float64) / 32768.0
            elif samples.dtype == np.int32:
                samples = samples.astype(np.float64) / 2147483648.0

            # Analyze
            features = analyze(samples, sample_rate)

            # Smooth
            features = smooth_features(prev_features, features, smoothing)
            prev_features = features

            # Map to colour
            rgb = features_to_rgb(features, config)

            # Check if colour changed enough
            if last_color is not None and color_distance(rgb, last_color) < COLOR_CHANGE_THRESHOLD:
                # Not enough change, skip send
                pass
            else:
                # Send to all devices
                for dev in devices:
                    ip = dev["ip"]
                    # Rate-limit per device
                    if ip in last_frame_time and (frame_start - last_frame_time[ip]) < frame_duration:
                        continue

                    try:
                        govee.color(ip, rgb[0], rgb[1], rgb[2])
                        last_frame_time[ip] = frame_start
                        logger.debug("Sent %s to %s (level=%.2f bass=%.2f mid=%.2f treble=%.2f)",
                                     "#{:02x}{:02x}{:02x}".format(*rgb), ip,
                                     features["level"], features["bass"],
                                     features["mid"], features["treble"])
                    except OSError as e:
                        if last_error_time is None or (frame_start - last_error_time) >= ERROR_LOG_INTERVAL:
                            logger.error("Failed to send to %s: %s", ip, e)
                            last_error_time = frame_start

                last_color = rgb

            # Sleep to maintain frame rate
            elapsed = time_fn() - frame_start
            sleep_time = frame_duration - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("Interrupted, restoring initial state")
    finally:
        # Clear music active state
        arbiter.clear_music_active()

        # Restore initial state
        for state in initial_states:
            ip = state["ip"]
            if state["state"] is None:
                continue
            try:
                data = state["state"].get("msg", {}).get("data", {})
                # Restore brightness
                if "brightness" in data:
                    govee.brightness(ip, data["brightness"])
                # Restore colour
                if "color" in data:
                    c = data["color"]
                    govee.color(ip, c.get("r", 255), c.get("g", 255), c.get("b", 255))
                logger.info("Restored state for %s", ip)
            except OSError as e:
                logger.error("Failed to restore %s: %s", ip, e)

        logger.info("Music sync stopped")


def main():
    parser = argparse.ArgumentParser(
        description="Music-reactive Govee lighting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python music_sync.py
  python music_sync.py --fps 15 --verbose
  python music_sync.py --log-file music.log
  python music_sync.py start
  python music_sync.py stop
  python music_sync.py toggle
  python music_sync.py status
""",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # start
    subparsers.add_parser("start", help="Start music sync in background")

    # stop
    subparsers.add_parser("stop", help="Stop music sync")

    # toggle
    subparsers.add_parser("toggle", help="Toggle music sync on/off")

    # status
    subparsers.add_parser("status", help="Show music sync status")

    # Legacy options (for running in foreground)
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.json"),
        help="Path to config.json",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=None,
        help="Frames per second (default: 10, range 2-20)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Log to this file with size rotation (1MB, 2 backups)",
    )

    args = parser.parse_args()

    # Handle subcommands
    if args.command == "start":
        sys.exit(cmd_start())
    elif args.command == "stop":
        sys.exit(cmd_stop())
    elif args.command == "toggle":
        sys.exit(cmd_toggle())
    elif args.command == "status":
        sys.exit(cmd_status())

    # No subcommand: run in foreground (legacy behavior)
    try:
        config = govee.load_config(args.config)
    except FileNotFoundError:
        logger.error("Config not found: %s", args.config)
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in config: %s", e)
        sys.exit(1)

    run(config, fps=args.fps, verbose=args.verbose, log_file=args.log_file)


if __name__ == "__main__":
    main()
