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
import contextlib
import ctypes
import importlib.util
import json
import logging
import logging.handlers
import math
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import arbiter
import govee

# Heartbeat interval: refresh music_active.json at least this often
HEARTBEAT_INTERVAL = 5.0

# Interval to check if the default speaker has changed (e.g., headphones plugged in)
DEVICE_CHECK_INTERVAL = 5.0

# Grace period after start: if the pid file is younger than this, treat the
# process as running even if the heartbeat hasn't been written yet.
START_GRACE_SECONDS = 20

# Silence detection: turn off after this many seconds of silence
DEFAULT_SILENCE_SECONDS = 2.0

# Default config path (used by cmd_stop and main)
DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.json"

# Silence level threshold (below this = silent)
SILENCE_LEVEL_THRESHOLD = 0.05

logger = logging.getLogger(__name__)


def pick_loopback(sc):
    """Pick the loopback microphone for the default speaker.

    Tries to get the loopback device for the default speaker by id.
    Falls back to the first microphone with isloopback=True, then to None.

    Args:
        sc: The soundcard module.

    Returns:
        A soundcard Microphone object, or None if no loopback found.
    """
    try:
        speaker = sc.default_speaker()
        mic = sc.get_microphone(speaker.id, include_loopback=True)
        if not getattr(mic, "isloopback", False):
            logger.warning("get_microphone returned non-loopback for speaker id %s", speaker.id)
        else:
            return mic
    except Exception as e:
        logger.warning("Could not get loopback for default speaker: %s", e)

    # Fallback: first mic with isloopback=True
    try:
        mics = sc.all_microphones(include_loopback=True)
        for mic in mics:
            if getattr(mic, "isloopback", False):
                return mic
    except Exception as e:
        logger.warning("Could not list microphones: %s", e)

    return None


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


def _turn_all(devices, on):
    """Turn all devices on or off. Returns True only if every device succeeded."""
    all_ok = True
    for dev in devices:
        ip = dev["ip"]
        try:
            govee.turn(ip, on)
        except OSError as e:
            logger.warning("turn %s failed for %s: %s", "on" if on else "off", ip, e)
            all_ok = False
    return all_ok


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
    """Check if a process with the given PID is alive (Windows).

    Also verifies the image name is python.exe or pythonw.exe to avoid
    matching a stale PID that Windows has reused for another program.
    """
    try:
        CREATE_NO_WINDOW = 0x08000000
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return False
        # Parse CSV output: each line is "image","pid","session","mem"
        # Compare the PID column exactly to avoid matching 123 inside 1234
        for line in result.stdout.strip().splitlines():
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    pid_col = int(parts[1].strip().strip('"'))
                    if pid_col == pid:
                        # Verify image name is a Python executable
                        image = parts[0].strip().strip('"').lower()
                        if image in ("python.exe", "pythonw.exe"):
                            return True
                        # PID reused by another program -> treat as dead
                        return False
                except ValueError:
                    continue
        return False
    except (subprocess.TimeoutExpired, OSError):
        return False


def _process_create_time(pid):
    """Return the process creation time as a Unix timestamp (float), or None.

    Uses Windows API via ctypes. Returns None on any failure or when not on Windows.
    """
    if os.name != "nt":
        return None
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetProcessTimes.restype = wintypes.BOOL
        k32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_ft = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            if not k32.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(exit_ft),
                                       ctypes.byref(kernel), ctypes.byref(user)):
                return None
            ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            # Windows FILETIME is 100ns intervals since 1601-01-01; Unix epoch is 1970-01-01
            return ticks / 1e7 - 11644473600
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def _kill_process(pid):
    """Kill a process by PID (Windows)."""
    try:
        CREATE_NO_WINDOW = 0x08000000
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


def _get_running_pid(kill_hung=True):
    """Get the PID of the running music_sync process, or None.

    Checks: pid file exists, process is alive, and arbiter.music_active() is true.
    Cleans up stale pid files.

    Grace period: if the process is alive but the heartbeat is missing/stale,
    and the pid file is younger than START_GRACE_SECONDS, treat it as running
    (the background process may not have written its first heartbeat yet).

    Args:
        kill_hung: If True (default), kill a hung process (alive but no heartbeat
            outside grace period). If False, just report it as running (used by
            cmd_status so status doesn't have side effects).
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

    # Check if the PID was reused by another process.
    # cmd_start writes the PID file AFTER Popen, so our process was created
    # before the file. If the process creation time is after the file mtime
    # (plus a small margin), the PID was reused.
    created = _process_create_time(pid)
    try:
        mtime = PID_FILE.stat().st_mtime
    except OSError:
        mtime = None

    if created is not None and mtime is not None and created > mtime + 2.0:
        # PID was reused by another process; treat as dead
        PID_FILE.unlink(missing_ok=True)
        arbiter.clear_music_active()
        return None

    if not arbiter.music_active():
        # Process alive but heartbeat stale. Check if we're in the grace period.
        try:
            pid_age = time.time() - PID_FILE.stat().st_mtime
        except OSError:
            pid_age = float("inf")

        if pid_age < START_GRACE_SECONDS:
            # Within grace period: process just started, heartbeat not written yet
            return pid

        if kill_hung:
            # Outside grace period: process is hung, kill it
            # Only kill if we confirmed the process identity (created is not None)
            if created is not None:
                _kill_process(pid)
            PID_FILE.unlink(missing_ok=True)
            arbiter.clear_music_active()
            return None
        else:
            # Don't kill; report as running (hung)
            return pid

    return pid


def _write_pid(pid):
    """Write the PID to the pid file."""
    _ensure_state_dir()
    PID_FILE.write_text(str(pid))


def _remove_pid():
    """Remove the pid file."""
    PID_FILE.unlink(missing_ok=True)


def _remove_own_pid_file():
    """Remove the PID file only if it contains our own PID.

    Safe to call on every exit path; ignores errors.
    """
    try:
        if PID_FILE.exists():
            content = PID_FILE.read_text().strip()
            if content == str(os.getpid()):
                PID_FILE.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def _remove_stop_flag():
    """Remove the stop flag file."""
    STOP_FLAG_FILE.unlink(missing_ok=True)


def _raise_stop_flag():
    """Create the stop flag file to signal the running process to stop."""
    _ensure_state_dir()
    STOP_FLAG_FILE.write_text(str(time.time()))


def cmd_start(config_path=DEFAULT_CONFIG_PATH):
    """Start music sync as a background process."""
    pid = _get_running_pid()
    if pid is not None:
        print(f"music mode already ON (pid {pid})")
        return 0

    # Check for required dependencies before spawning
    missing = []
    if importlib.util.find_spec("soundcard") is None:
        missing.append("soundcard")
    if importlib.util.find_spec("numpy") is None:
        missing.append("numpy")
    if missing:
        print("music mode needs: python -m pip install --user -r requirements-music.txt",
              file=sys.stderr)
        return 2

    # Remember previous mode so we can restore it if Popen fails
    previous = arbiter.get_mode()

    # Select music mode before spawning the background process
    try:
        arbiter.set_mode("music")
    except OSError as e:
        print(f"music mode: cannot set mode: {e}", file=sys.stderr)
        return 1

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
        "--config",
        str(config_path),
        "--log-file",
        str(LOG_FILE),
    ]

    # Start detached on Windows
    try:
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
    except OSError as e:
        # Popen failed; restore previous mode
        try:
            arbiter.set_mode(previous)
        except OSError:
            pass
        print(f"music mode: cannot start: {e}", file=sys.stderr)
        return 1

    _write_pid(proc.pid)
    print(f"music mode ON (pid {proc.pid})")
    return 0


def cmd_stop(config_path=DEFAULT_CONFIG_PATH):
    """Stop the running music sync process and set mode to off."""
    pid = _get_running_pid()
    if pid is not None:
        # Signal the process to stop via flag file
        _raise_stop_flag()

        # Wait up to 5 seconds for it to exit
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not _is_process_alive(pid):
                break
            time.sleep(0.1)

        # If still alive, force kill
        if _is_process_alive(pid):
            _kill_process(pid)

        # Clean up
        _remove_pid()
        _remove_stop_flag()
        arbiter.clear_music_active()

    # Set mode to "off" so music mode doesn't stay active.
    # Use mode.switch() to actually turn the strips off (not just set the mode).
    try:
        import mode as mode_mod
        mode_mod.switch("off", govee.load_config(config_path))
    except (OSError, ValueError) as e:
        print(f"warning: failed to switch to off: {e}", file=sys.stderr)
        try:
            arbiter.set_mode("off")
        except OSError as e2:
            print(f"warning: failed to set mode to off: {e2}", file=sys.stderr)

    print("music mode OFF")
    return 0


def cmd_toggle(config_path=DEFAULT_CONFIG_PATH):
    """Toggle music sync on/off."""
    pid = _get_running_pid()
    if pid is not None:
        return cmd_stop(config_path)
    else:
        return cmd_start(config_path)


def cmd_status():
    """Show music sync status."""
    pid = _get_running_pid(kill_hung=False)
    if pid is not None:
        # Check if the process is hung (alive but no heartbeat)
        if not arbiter.music_active():
            print(f"music mode ON (pid {pid}, no heartbeat)")
        else:
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

    try:
        # Get music config
        music_cfg = config.get("music", {})
        if fps is None:
            fps = music_cfg.get("fps", DEFAULT_FPS)
        fps = max(MIN_FPS, min(MAX_FPS, fps))
        smoothing = music_cfg.get("smoothing", DEFAULT_SMOOTHING)
        silence_seconds = music_cfg.get("silence_seconds", DEFAULT_SILENCE_SECONDS)

        devices = config.get("devices", [])
        if not devices:
            logger.error("No devices configured")
            sys.exit(1)

        # Try to import soundcard/numpy
        try:
            import soundcard as sc
            import numpy as np
        except ImportError:
            msg = "music mode needs: python -m pip install --user -r requirements-music.txt"
            print(msg)
            logger.error(msg)
            sys.exit(2)

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

        # Silence detection state
        silence_start_time = None
        lights_on = True

        # No-device state: track if we've already turned off due to no device
        no_device_off_sent = False

        # Track exit reason to decide whether to restore
        exit_due_to_mode_change = False
        exit_due_to_stop_flag = False

        # Track if we were in silence before signal became active
        was_silent_before_signal = False

        logger.info("Music sync started (fps=%d, smoothing=%.2f, silence_seconds=%.1f)",
                    fps, smoothing, silence_seconds)
        logger.info("Press Ctrl+C to stop")

        # Clear any leftover stop flag from a previous run
        _remove_stop_flag()

        # Check mode before touching the strips: if not "music", exit immediately
        # without sending status/brightness queries or marking ourselves active.
        current_mode = arbiter.get_mode()
        if current_mode != "music":
            logger.info("mode is %s, not music; not starting", current_mode)
            return

        # Mark music sync as active BEFORE reading initial state, so weather/game
        # don't send during the status/brightness queries
        arbiter.set_music_active()

        # Recorder is opened lazily; None means "not currently open"
        rec = None
        rec_device_id = None
        last_device_check = 0.0

        try:
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

            # Re-check mode before touching strips: if the owner picked Off (or
            # another mode) during the status queries, don't override it.
            if arbiter.get_mode() == "music" and not arbiter.signal_active():
                # Set brightness once at start
                brightness = arbiter.cap_brightness(80, config)
                for dev in devices:
                    ip = dev["ip"]
                    try:
                        govee.brightness(ip, brightness)
                        logger.info("Set brightness %d on %s", brightness, ip)
                    except OSError as e:
                        logger.error("Failed to set brightness on %s: %s", ip, e)

                # Turn all strips on at start (they may have been off from a previous mode)
                _turn_all(devices, True)

            while True:
                frame_start = time_fn()

                # Check for stop flag first (before signal check) so stop works
                # even while an agent signal is active
                if STOP_FLAG_FILE.exists():
                    logger.info("stop flag detected; exiting")
                    exit_due_to_stop_flag = True
                    break

                # Check mode: if not "music", exit cleanly (new mode's script will light strips)
                current_mode = arbiter.get_mode()
                if current_mode != "music":
                    logger.info("mode changed to %s; exiting music sync", current_mode)
                    exit_due_to_mode_change = True
                    break

                # Refresh heartbeat at least every HEARTBEAT_INTERVAL seconds
                if frame_start - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                    arbiter.set_music_active()
                    last_heartbeat_time = frame_start

                # Check signal priority: if agent signal is active, don't send frames
                if arbiter.signal_active():
                    if not signal_was_active:
                        logger.info("signal active; pausing music sync")
                        # Remember if we were in silence before signal became active
                        was_silent_before_signal = (silence_start_time is not None)
                    signal_was_active = True
                    # Don't send any frames while signal is active
                    # Sleep to maintain frame rate
                    elapsed = time_fn() - frame_start
                    sleep_time = frame_duration - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    continue

                # Signal just cleared: if we were in silence before signal became active, send off now
                if signal_was_active and was_silent_before_signal:
                    logger.info("signal cleared during silence; turning lights off")
                    if _turn_all(devices, False):
                        lights_on = False
                    # Reset silence tracking since we just sent off
                    silence_start_time = None

                signal_was_active = False

                # Check if the default speaker has changed (e.g., headphones plugged in)
                if rec is not None and frame_start - last_device_check >= DEVICE_CHECK_INTERVAL:
                    last_device_check = frame_start
                    try:
                        current_id = sc.default_speaker().id
                    except Exception:
                        current_id = None
                    if current_id is not None and current_id != rec_device_id:
                        logger.info("default speaker changed; reopening recorder")
                        try:
                            rec.__exit__(None, None, None)
                        except Exception:
                            pass
                        rec = None
                        continue

                # If no recorder is open, try to open one
                if rec is None:
                    new_loopback = pick_loopback(sc)
                    if new_loopback is not None:
                        logger.info("Opening recorder on %s", new_loopback.name)
                        try:
                            rec = new_loopback.recorder(
                                samplerate=sample_rate, channels=1
                            ).__enter__()
                            rec_device_id = new_loopback.id
                            # Device found again; reset no-device state
                            no_device_off_sent = False
                        except Exception as enter_err:
                            if last_error_time is None or (frame_start - last_error_time) >= ERROR_LOG_INTERVAL:
                                logger.error("Failed to enter recorder: %s", enter_err)
                                last_error_time = frame_start
                            # No device: turn off once, keep running
                            if not no_device_off_sent:
                                logger.info("no audio device; turning lights off")
                                if _turn_all(devices, False):
                                    no_device_off_sent = True
                                    lights_on = False
                            time.sleep(1.0)
                            continue
                    else:
                        if last_error_time is None or (frame_start - last_error_time) >= ERROR_LOG_INTERVAL:
                            logger.error("No loopback device found")
                            last_error_time = frame_start
                        # No device: turn off once, keep running
                        if not no_device_off_sent:
                            logger.info("no audio device; turning lights off")
                            if _turn_all(devices, False):
                                no_device_off_sent = True
                                lights_on = False
                        time.sleep(1.0)
                        continue

                # Capture audio
                try:
                    raw = rec.record(numframes=samples_per_frame)
                except Exception as e:
                    if last_error_time is None or (frame_start - last_error_time) >= ERROR_LOG_INTERVAL:
                        logger.error("Audio capture error: %s", e)
                        last_error_time = frame_start
                    time.sleep(1.0)
                    # Exit the old recorder and forget it
                    try:
                        rec.__exit__(None, None, None)
                    except Exception:
                        pass
                    rec = None
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

                # Silence detection - timer update only (no sends yet)
                if features["level"] < SILENCE_LEVEL_THRESHOLD:
                    if silence_start_time is None:
                        silence_start_time = frame_start
                else:
                    # Sound detected
                    if silence_start_time is not None:
                        logger.info("sound detected after %.1fs of silence",
                                    frame_start - silence_start_time)
                    silence_start_time = None

                # Re-check signal before sending (signal may have become active
                # during audio capture/analysis). If active, skip all sends
                # (silence off/on and colour) for this loop iteration.
                if arbiter.signal_active():
                    # Don't set signal_was_active here; that's only for the
                    # top-of-loop check. Setting it here would cause the
                    # "signal cleared during silence" code to run in the next
                    # iteration even though the signal was never active at the
                    # top of the loop.
                    # Don't send this frame; sleep to maintain frame rate
                    elapsed = time_fn() - frame_start
                    sleep_time = frame_duration - elapsed
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    continue

                # Re-check mode before sending (mode may have changed during
                # audio capture/analysis). If not "music", exit cleanly.
                current_mode = arbiter.get_mode()
                if current_mode != "music":
                    logger.info("mode changed to %s; exiting music sync", current_mode)
                    exit_due_to_mode_change = True
                    break

                # Silence detection - sends (only if signal is not active)
                if features["level"] < SILENCE_LEVEL_THRESHOLD:
                    if frame_start - silence_start_time >= silence_seconds:
                        # Silent long enough: turn off
                        if lights_on:
                            logger.info("silence detected; turning lights off")
                            if _turn_all(devices, False):
                                lights_on = False
                else:
                    # If lights were off, turn them back on
                    if not lights_on:
                        logger.info("turning lights back on")
                        if _turn_all(devices, True):
                            lights_on = True

                # Map to colour
                rgb = features_to_rgb(features, config)

                # Only send colour if lights are on (not in silence)
                if lights_on and silence_start_time is None:
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
            # Exit the recorder if it's open
            if rec is not None:
                try:
                    rec.__exit__(None, None, None)
                except Exception:
                    pass

            # Clear music active state (wrap in try/except so PID cleanup and
            # restore still run even if this fails, e.g. PermissionError on
            # Windows when another process has the file open)
            try:
                arbiter.clear_music_active()
            except OSError as e:
                logger.warning("could not clear music heartbeat: %s", e)

            # Don't restore over an active signal (agent_signal clear will handle it)
            # Also don't restore when exiting due to mode change (new mode's script will light strips)
            # Also don't restore when exiting due to stop flag (cmd_stop will turn strips off)
            if arbiter.signal_active():
                logger.info("signal active; not restoring (agent_signal clear will)")
            elif exit_due_to_mode_change:
                logger.info("exiting due to mode change; not restoring (new mode will light strips)")
            elif exit_due_to_stop_flag:
                logger.info("stop requested; turning strips off")
                _turn_all(devices, False)
            else:
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
    finally:
        # Clean up our own PID file on every exit path
        _remove_own_pid_file()


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
        default=str(DEFAULT_CONFIG_PATH),
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
        sys.exit(cmd_start(args.config))
    elif args.command == "stop":
        sys.exit(cmd_stop(args.config))
    elif args.command == "toggle":
        sys.exit(cmd_toggle(args.config))
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
