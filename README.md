# Govee control

Local automation for two Govee COB strip lights (Windows PC).
Project board: Govee (epiq), parent ticket Z6KCSBZ.

Planned pieces: LAN client + CLI (`govee.py`), game-process colour sync,
Stream Deck wrappers, weather sync, "agent needs input" signal.

Verified on real hardware: H1AB3 and H1AB2 (LAN Control enabled).

Setup: copy `config.example.json` to `config.json` and fill in device IPs.
In the Govee Home app, enable **LAN Control** on each strip (device settings).

## Network interface handling

On multi-homed hosts (e.g., WSL with multiple virtual adapters), `govee.py scan`
automatically sends the discovery multicast on every non-loopback, non-link-local
IPv4 interface and merges the replies. If you want to restrict scanning to a
specific interface, use `--iface-ip`:

```bash
# Auto-detect all interfaces (default)
python govee.py scan

# Scan on a specific interface only
python govee.py scan --iface-ip 192.168.1.10
```

## CLI usage

```bash
# Discover devices on the LAN
python govee.py scan

# Turn on/off (uses all devices in config, or --ip to target specific)
python govee.py on
python govee.py off --ip 192.168.1.50

# Set brightness (1-100)
python govee.py brightness 50

# Set colour (hex or name: red, green, blue, white, orange, purple, yellow, cyan, pink)
python govee.py color red
python govee.py color #ff8800

# Query status
python govee.py status --ip 192.168.1.50

# Use a different config file
python govee.py on --config myconfig.json

# Bind multicast to a specific interface (useful on WSL/multi-homed hosts)
python govee.py scan --iface-ip 192.168.1.10
```

## Game sync

`game_sync.py` watches for running game processes and sets the lights to each
game's configured colour. In game mode with no game running, the lights are
turned off. When a game starts, the lights turn on with the game's profile.
The `"default"` profile is only used by `--once` mode (not in the continuous
loop).

```bash
# Run once and exit (useful for testing)
python game_sync.py --once

# Dry-run: print what would be sent without sending
python game_sync.py --once --dry-run

# Run continuously, checking every 10 seconds
python game_sync.py --interval 10

# Use a specific config file
python game_sync.py --config myconfig.json
```

### Configuration

Add `default` and `games` sections to your `config.json`:

```json
{
  "devices": [...],
  "default": {
    "color": "white",
    "brightness": 40
  },
  "games": [
    {
      "name": "Cyberpunk 2077",
      "exe": "Cyberpunk2077.exe",
      "color": "#ff00aa",
      "brightness": 80
    },
    {
      "name": "Ghost of Tsushima",
      "exe": "GhostOfTsushima.exe",
      "color": "#ff4500",
      "brightness": 70
    }
  ]
}
```

The `exe` field is matched case-insensitively against running process names.
When multiple games match, the first one in config order wins.

### Default profile in --once mode

The `"default"` profile is only used when running `game_sync.py --once` with no
game running. In continuous loop mode, no game means the lights are turned off.

```json
{
  "devices": [...],
  "default": {
    "color": "white",
    "brightness": 40
  },
  "games": [...]
}
```

Set `"default": null` to have `--once` mode turn the lights off instead of
applying a default profile.

### Game profiles

Two game profiles are included out of the box:

| Game | Executable | Colour | Brightness |
|------|------------|--------|------------|
| Cyberpunk 2077 | `Cyberpunk2077.exe` | Neon magenta `#ff00aa` | 80% |
| Ghost of Tsushima | `GhostOfTsushima.exe` | Sunset orange-red `#ff4500` | 70% |

To change a game's colour or brightness, edit its entry in `config.json`.
To add more games, copy an existing entry and change the `name`, `exe`, `color`, and `brightness` fields.

### Start at logon

Use the autostart installer to register weather sync, game sync, and the tray
icon as Windows scheduled tasks that run at logon (hidden, no console window).
See [docs/autostart.md](docs/autostart.md) for install, uninstall, and
troubleshooting instructions.

If you created the older manual task, remove it:

```powershell
schtasks /delete /tn "Govee Game Sync" /f
```

## Weather sync

`weather_sync.py` fetches current weather from the free, keyless Open-Meteo API
and sets the lights to a colour that reflects the conditions.

```bash
# Run once and exit (useful for testing)
python weather_sync.py --once

# Dry-run: print what would be sent without sending
python weather_sync.py --once --dry-run

# Run continuously, checking every 15 minutes (default)
python weather_sync.py

# Custom interval (in seconds)
python weather_sync.py --interval 600
```

### Configuration

Add a `weather` section to your `config.json`:

```json
{
  "devices": [...],
  "weather": {
    "latitude": 51.5074,
    "longitude": -0.1278,
    "brightness": 50
  }
}
```

The script refuses to run (exit code 2) if both latitude and longitude are 0.0.

While an agent signal is active or another mode is selected, weather_sync
re-checks every 10 seconds (`weather_sync.BLOCKED_POLL_SECONDS`) and resumes
as soon as the signal clears and the mode is "weather" again.

### Brightness cap

All automatic scripts (agent signal, game sync, weather sync) cap brightness at
the configured `max_brightness` (default 80). This keeps the strips from running
at full brightness all the time. Manual CLI brightness commands (`govee.py
brightness N`) are not capped — if you type it, you get it.

If `max_brightness` is not a number (or is a boolean), the default of 80 is used.
If a script passes a non-numeric brightness value, it falls back to the cap with
a warning on stderr.

```json
{
  "devices": [...],
  "max_brightness": 80,
  ...
}
```

Set `max_brightness` to 100 to disable the cap. Values are clamped to 1–100.

### Weather patterns

When `patterns_enabled` is true (default), weather_sync uses animated patterns
for certain weather conditions instead of static colours:

- **Cloudy** (WMO codes 2-3): slow drift between blue-grey tones (40s cycle)
- **Rain** (WMO codes 51-67, 80-82): wave pattern between blue tones (8s cycle),
  with strips out of phase for a rippling effect
- **Thunderstorm** (WMO codes 95-99): purple pulse between #4a148c and #7b1fa2
  (12s cycle, brightness 60-80) with random white lightning flashes every 6-20s
  (flashes may exceed max_brightness)

Thunderstorm pattern config keys (`weather.patterns.thunderstorm`):

```json
{
  "type": "thunderstorm",
  "color1": "#4a148c",
  "color2": "#7b1fa2",
  "period": 12.0,
  "brightness": 80,
  "brightness_min": 60,
  "phase_offset": 0.0,
  "flash_every": [6, 20],
  "flash_duration": 0.15,
  "flash_color": "#ffffff",
  "flash_brightness": 100,
  "double_flash_prob": 0.3,
  "flash_both_prob": 0.5
}
```

An override only needs the keys you want to change; missing keys keep their
defaults. For example, `{"thunderstorm": {"flash_every": [3, 8]}}` changes only
the flash interval while keeping the default colours and brightness.

All other weather conditions use static colours.

At night (is_day=0), different colours are used for a more atmospheric look,
and base-frame brightness is capped at `night_brightness` (default 30).
`night_brightness` is a ceiling: if a pattern's own brightness is lower, that
wins (e.g. a `cloudy_night` pattern with `"brightness": 15` stays at 15).
Thunderstorm has no night variant — it uses the same pattern day and night,
with base frames capped at `night_brightness` and flashes keeping their own
`flash_brightness` (100).

Configuration options in the `weather` section:

```json
{
  "weather": {
    "latitude": 51.5074,
    "longitude": -0.1278,
    "brightness": 50,
    "night_brightness": 30,
    "patterns_enabled": true,
    "frame_interval": 1.0,
    "patterns": {
      "cloudy": {
        "type": "drift",
        "color1": "#546e7a",
        "color2": "#90a4ae",
        "period": 40.0,
        "brightness": 75,
        "phase_offset": 0.0
      },
      "cloudy_night": {
        "type": "drift",
        "color1": "#37474f",
        "color2": "#5c6bc0",
        "period": 40.0,
        "brightness": 30,
        "phase_offset": 0.0
      },
      "rain": {
        "type": "wave",
        "color1": "#1e88e5",
        "color2": "#0d47a1",
        "period": 8.0,
        "brightness": 80,
        "phase_offset": 4.0
      }
    }
  }
}
```

- `patterns_enabled`: enable/disable animated patterns (default: true)
- `frame_interval`: seconds between animation frames (default: 1.0, min: 0.5)
- `night_brightness`: brightness at night (default: 30)
- `fetch_on_the_hour`: fetch weather at the top of every hour (default: true);
  set to false for interval-based fetching
- `fetch_offset_seconds`: seconds after the hour boundary to fetch (default: 120);
  avoids SSL handshake timeouts that occur at exactly HH:00:00; clamped to 0–3000
- `fetch_retry_seconds`: seconds to wait before retrying a failed fetch (default: 60);
  doubles on each consecutive failure up to the interval (900s); resets on success
- `patterns`: override default pattern definitions for cloudy/rain/thunderstorm
  (use `_night` suffix for night variants, e.g. `cloudy_night`; thunderstorm
  has no night variant — it uses the same pattern day and night)

Weather is fetched 2 minutes after the top of every hour by default
(`fetch_on_the_hour: true`, `fetch_offset_seconds: 120`), not every frame.
The offset avoids SSL handshake timeouts that occur at exactly HH:00:00.
Between fetches, the last known weather data is used for animation.
When is_day changes (day to night or vice versa), the pattern and brightness
switch immediately at the next fetch.

To use the old interval-based behaviour, set `fetch_on_the_hour: false` in the
`weather` config section. Weather will then be fetched every `interval` seconds
(default 900).

### Colour mapping

Weather conditions are mapped to colours using WMO weather codes:

| WMO codes | Condition | Day colour | Night colour |
|-----------|-----------|------------|--------------|
| 0-1 | Clear sky | Warm yellow `#ffd27f` | Deep blue `#1a237e` |
| 2-3 | Partly/mostly cloudy | Blue-grey `#546e7a` | Dark blue-grey `#37474f` |
| 45-48 | Fog | Light grey `#cfd8dc` | Dark grey `#455a64` |
| 51-67 | Drizzle/rain | Blue `#1e88e5` | Dark blue `#0d47a1` |
| 71-77 | Snow | Pale blue `#e3f2fd` | Indigo `#3949ab` |
| 80-82 | Showers | Blue `#1e88e5` | Dark blue `#0d47a1` |
| 85-86 | Snow showers | Pale blue `#e3f2fd` | Indigo `#3949ab` |
| 95-99 | Thunderstorm | Purple pulse `#4a148c`↔`#7b1fa2` + flashes | Purple pulse `#4a148c`↔`#7b1fa2` + flashes |
| Other | Unknown | White `#ffffff` | Dark grey `#37474f` |

## Modes

The owner picks ONE mode by hand; only that mode may drive the strips. The agent
signal (orange) stays above everything.

```bash
# Get the current mode
python mode.py get

# Set a mode
python mode.py set weather
python mode.py set game
python mode.py set music
python mode.py set off

# Dry-run (print what would be done without doing it)
python mode.py set off --dry-run
```

Modes:
- `off` — no mode drives the strips; turns lights off even if an active orange signal is showing
- `weather` — weather_sync.py may drive the strips
- `game` — game_sync.py may drive the strips
- `music` — music_sync.py may drive the strips

Exit codes of `mode.py`:
- `0` — done
- `1` — config unreadable (only for `set off`) or the mode file could not be written
- `2` — unknown mode or bad arguments

If `state/mode.json` is missing, unreadable, or contains an unknown mode, the
current mode is treated as `off`.

### Off mode suppresses the signal

When the mode is `off`, the agent signal is suppressed: `needs-input` hooks
return immediately without turning the strips orange. This means the lights
stay dark when the owner has explicitly switched them off. The signal works
normally in `weather`, `game`, and `music` modes. The `--force` flag does not
bypass this.

### Per-session signal markers

When multiple Claude sessions are running, each session that raises the signal
writes a marker file to `state/signal_sessions/<session_id>`. When a session
clears the signal, only its own marker is removed. The lights stay orange until
the last session's marker is removed.

The signal is cleared by three Claude Code hook events:
- `Notification` → `needs-input` (turns the signal on)
- `UserPromptSubmit` → `clear` (user responded)
- `SessionEnd` → `clear` (session ended while waiting, so the marker is removed)

- Markers older than 2 hours (configurable via `signal.marker_max_age_hours`)
  are considered stale and are automatically deleted.
- If `saved_state.json` exists but the marker directory is empty or missing
  (legacy state from before this feature), the next `clear` restores the lights
  as before.
- `agent_signal.py clear --all` is a manual escape hatch that restores the
  lights regardless of remaining markers.

### Ignoring background-job notifications

Background jobs that finish send a `Notification` hook with a message like
`DFR9Y86 Govee control (Parent, continued from 0BN23PQ) finished`. By default,
these are ignored so the strips don't turn orange for completed work.

The `signal.ignore_message_patterns` config key is a list of regex patterns
(matched with `re.search`). If the hook's `message` matches any pattern, the
signal is skipped and logged as `skipped-ignored`. The default patterns are
`[" finished$", "\\bcompleted$"]`.

Real "needs input" notifications (e.g., `Claude needs your permission`,
`Claude is waiting for your input`, or `<ref> <title> needs your input: ...`)
do not match these patterns and will still trigger the signal.

The `--force` flag does not bypass ignore patterns.

### Clear fallback

When `agent_signal.py clear` runs, it restores each strip that has saved state. For any configured strip that has no saved state — for example, a strip that did not answer `devStatus` when the signal was raised, or every strip when the saved-state marker is `[]` — it applies the config's `"default"` profile. If `"default"` is missing or `null`, it falls back to white at 40%. The lights never stay in the signal colour after `clear`. A strip whose saved colour equals the signal colour is treated as a stale reading and gets the default too, so a strip that really was set to the signal colour comes back as the default after clear.

### State files

The mode system uses file-based state in the `state/` directory:
- `state/saved_state.json` — exists when an agent signal is active
- `state/signal_sessions/` — per-session marker files; one file per Claude session that raised the signal
- `state/music_active.json` — exists when music sync is active (contains pid and timestamp); music sync rewrites this file at least every 5 seconds as a heartbeat, and if it's older than 15 seconds it's considered stale
- `state/game_active.json` — exists when game sync is active (contains the profile name); game sync rewrites this file every loop iteration as a heartbeat, and if it's older than 60 seconds it's considered stale
- `state/mode.json` — contains the currently selected mode (weather | game | music | off); if it is missing the mode is "off"
- `state/music_sync.pid` — pid of the background music process started by `music_sync.py start` / the tray
- `state/music_stop` — stop flag; `music_sync.py stop` creates it and the music process exits when it sees it
- `state/music_sync.log` — log of the background music process (rotated at 1 MB, 2 backups)
- `state/signal.log` — log of agent signal hooks
- `state/tray.log` — tray errors (failed mode switches, refresh errors)
- `state/agent_signal.lock` — lock file used to serialise concurrent agent signal hooks

Concurrent `needs-input` and `clear` hooks are serialised with `state/agent_signal.lock` to prevent race conditions where multiple Claude sessions run the hooks simultaneously.

## Music mode (optional)

Music mode makes the strips follow the music playing on this PC. It requires
optional dependencies that are not installed by default:

```bash
python -m pip install --user soundcard numpy
```

Or install from the requirements file:

```bash
python -m pip install --user -r requirements-music.txt
```

To test that audio capture works:

```bash
python tools/audio_probe.py --selftest
```

This plays a test tone and verifies it's captured via WASAPI loopback.

### Switching to music mode

Music mode is switched on with `python mode.py set music` (or `music_toggle.cmd`).
It is switched off by picking another mode (`python mode.py set off`, `weather`,
or `game`). When music mode is selected, `music_sync.py` runs in the background
and drives the strips.

If there is no audio device, the strips are turned off but music mode stays
selected and retries. If there is silence for more than `music.silence_seconds`
(default 2.0 seconds), the strips are turned off until audio resumes.

### Music sync

`music_sync.py` captures system audio, analyzes frequency bands (bass, mid,
treble), and maps them to colours sent to the strips. Bass-dominant music
produces warm red/magenta colours, mid-dominant produces green/yellow, and
treble-dominant produces blue/cyan. The overall volume scales brightness.

```bash
# Run music sync (foreground, stops on Ctrl+C)
python music_sync.py

# Custom frame rate (default 10 fps, range 2-20)
python music_sync.py --fps 15

# Verbose logging
python music_sync.py --verbose

# Log to file with rotation
python music_sync.py --log-file music.log
```

Debugging commands (these also switch modes):

```bash
# Start music sync in background (selects music mode)
python music_sync.py start

# Stop music sync (sets mode to off)
python music_sync.py stop

# Toggle music sync on/off
python music_sync.py toggle

# Show music sync status
python music_sync.py status
```

Configuration in `config.json`:

```json
{
  "music": {
    "fps": 10,
    "smoothing": 0.5,
    "silence_seconds": 2.0
  }
}
```

- `fps`: frames per second (default 10, clamped to 2-20)
- `smoothing`: exponential moving average factor (0-1, higher = less smoothing, default 0.5)
- `silence_seconds`: seconds of silence before turning strips off (default 2.0)

On exit (Ctrl+C), music_sync restores each strip to the colour/brightness it had
when it started.

## Tray icon

A Windows notification-area (tray) icon lets you switch modes by right-clicking.

Install the dependencies (not installed by default):

```bash
python -m pip install --user -r requirements-tray.txt
```

Start the tray icon (no console window):

```bash
pythonw tray.py
```

Right-click the icon to pick Off / Weather / Game / Music. The icon colour
reflects the current mode (grey=off, blue=weather, purple=game, green=music).
"Quit" exits the tray icon without changing the mode.

Windows hides new tray icons under the "^" arrow in the taskbar; drag the icon
out to pin it. Errors are logged to `state/tray.log`.

## Autostart

Run weather sync, game sync, and the tray icon automatically at Windows logon
(hidden, no console window). See [docs/autostart.md](docs/autostart.md) for
install, uninstall, and troubleshooting instructions.
