# Music mode

Music mode makes the Govee strips react to music playing on the PC. It captures
system audio via WASAPI loopback (Windows) or PulseAudio (Linux), analyzes the
frequency content, and maps it to colours.

## How it works

1. **Audio capture**: Captures system audio at 44.1 kHz, mono mixdown.
2. **Analysis**: Uses FFT (numpy) or a pure-Python DFT fallback to compute
   energy in three bands:
   - Bass: 20-250 Hz
   - Mid: 250-4000 Hz
   - Treble: 4000-16000 Hz
3. **Smoothing**: Exponential moving average reduces flicker from rapid changes.
4. **Colour mapping**:
   - Bass-dominant → warm red/magenta
   - Mid-dominant → green/yellow
   - Treble-dominant → blue/cyan
   - Overall volume scales brightness (with a 10% dark floor)
5. **Frame rate limiting**: Sends at most `fps` frames per second (default 10).
   Small colour changes are filtered to prevent flicker.

## Setup

Install optional dependencies:

```bash
python -m pip install --user -r requirements-music.txt
```

Test audio capture:

```bash
python tools/audio_probe.py --selftest
```

## Usage

### Toggle on/off (recommended)

Music mode is a toggled mode — it starts only when you turn it on and stays on
until you turn it off. It never starts automatically.

```bash
# Toggle on/off
python music_sync.py toggle

# Or use the double-clickable shortcut
music_toggle.cmd
```

### Other commands

```bash
# Start in background
python music_sync.py start

# Stop
python music_sync.py stop

# Check status
python music_sync.py status
```

### Foreground mode (legacy)

```bash
# Run music sync (foreground, stops on Ctrl+C)
python music_sync.py

# Custom frame rate
python music_sync.py --fps 15

# Verbose logging
python music_sync.py --verbose

# Log to file
python music_sync.py --log-file music.log
```

## Configuration

Add to `config.json`:

```json
{
  "music": {
    "fps": 10,
    "smoothing": 0.5
  }
}
```

- `fps`: frames per second (default 10, clamped to 2-20)
- `smoothing`: EMA factor (0-1, higher = less smoothing, default 0.5)

## State restoration

On exit (Ctrl+C or error), music_sync restores each strip to the colour and
brightness it had when it started. It queries `govee.status` for each device
before making changes and saves the state for later restoration.

## Priority

Music mode participates in the priority system:
**agent signal > music sync > game sync > weather sync**.

When music_sync is running, it writes a heartbeat file (`state/music_active.json`)
at least every 5 seconds. Game sync and weather sync check this file and yield
to music while it's active. If music_sync crashes or exits without clearing the
file, it becomes stale after 15 seconds and game/weather sync resume.

When an agent signal becomes active (e.g., `needs-input`), music_sync pauses
sending frames and lets the signal colour show. When the signal clears, music
sync resumes on the next frame.

Music sync clears its heartbeat file on every exit path (Ctrl+C, error, or
normal exit), so game/weather sync can take over immediately.

## Log file

When started via `start` or `toggle`, music sync logs to `state/music_sync.log`
(1 MB, rotated to 2 backups).

## Desktop shortcut / hotkey

To make it easy to toggle music mode:

1. Right-click `music_toggle.cmd` in the repo root
2. Select "Send to" → "Desktop (create shortcut)"
3. Optionally rename the shortcut to "Music Mode"
4. To bind a hotkey: right-click the shortcut → Properties → Hotkey field → press a key combo

You can also pin the shortcut to your taskbar or use it with a Stream Deck button.
