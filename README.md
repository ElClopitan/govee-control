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
game's configured colour. When no game is running, it restores a default,
unless config has `"default": null`, in which case it sends nothing and leaves
the lights to weather_sync or manual control.

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

### Leaving lights to weather when no game is running

Set `"default": null` in your config to have game_sync send nothing when no game
is running. This lets weather_sync (or manual settings) control the lights
between games. When a game starts, its profile is applied as usual.

```json
{
  "devices": [...],
  "default": null,
  "games": [...]
}
```

### Game profiles

Two game profiles are included out of the box:

| Game | Executable | Colour | Brightness |
|------|------------|--------|------------|
| Cyberpunk 2077 | `Cyberpunk2077.exe` | Neon magenta `#ff00aa` | 80% |
| Ghost of Tsushima | `GhostOfTsushima.exe` | Sunset orange-red `#ff4500` | 70% |

To change a game's colour or brightness, edit its entry in `config.json`.
To add more games, copy an existing entry and change the `name`, `exe`, `color`, and `brightness` fields.

### Start at logon (Task Scheduler)

To run game sync automatically when you log in, create a scheduled task:

```powershell
schtasks /create /tn "Govee Game Sync" /tr "pythonw.exe C:\path\to\Govee\game_sync.py --interval 5" /sc onlogon
```

Use `pythonw.exe` (not `python.exe`) to avoid a console window. To remove the
task later:

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

While a signal or game is active, weather_sync re-checks every 10 seconds
(`weather_sync.BLOCKED_POLL_SECONDS`) and resumes as soon as the higher-priority
source clears.

### Brightness cap

All automatic scripts (agent signal, game sync, weather sync) cap brightness at
the configured `max_brightness` (default 80). This keeps the strips from running
at full brightness all the time. Manual CLI brightness commands (`govee.py
brightness N`) are not capped — if you type it, you get it.

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

- **Cloudy** (WMO codes 2-3): slow drift between grey tones (40s cycle)
- **Rain** (WMO codes 51-67, 80-82): wave pattern between blue tones (8s cycle),
  with strips out of phase for a rippling effect

All other weather conditions use static colours.

Configuration options in the `weather` section:

```json
{
  "weather": {
    "latitude": 51.5074,
    "longitude": -0.1278,
    "brightness": 50,
    "patterns_enabled": true,
    "frame_interval": 1.0,
    "patterns": {
      "cloudy": {
        "type": "drift",
        "color1": "#b0bec5",
        "color2": "#eceff1",
        "period": 40.0,
        "brightness": 75,
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
- `patterns`: override default pattern definitions for cloudy/rain

Weather is fetched every `interval` seconds (default 900), not every frame.
Between fetches, the last known weather data is used for animation.

### Colour mapping

Weather conditions are mapped to colours using WMO weather codes:

| WMO codes | Condition | Day colour | Night colour |
|-----------|-----------|------------|--------------|
| 0-1 | Clear sky | Warm yellow `#ffd27f` | Deep blue `#1a237e` |
| 2-3 | Partly/mostly cloudy | Grey `#b0bec5` | Grey `#b0bec5` |
| 45-48 | Fog | Light grey `#cfd8dc` | Light grey `#cfd8dc` |
| 51-67 | Drizzle/rain | Blue `#1e88e5` | Blue `#1e88e5` |
| 71-77 | Snow | Pale blue `#e3f2fd` | Pale blue `#e3f2fd` |
| 80-82 | Showers | Blue `#1e88e5` | Blue `#1e88e5` |
| 85-86 | Snow showers | Pale blue `#e3f2fd` | Pale blue `#e3f2fd` |
| 95-99 | Thunderstorm | Purple `#7b1fa2` | Purple `#7b1fa2` |
| Other | Unknown | White `#ffffff` | White `#ffffff` |

## Priority

When multiple light sources are active, they follow this priority order:

1. **Agent signal** (highest) — `agent_signal.py needs-input` sets the lights to the signal colour. While active, game sync and weather sync do not send any commands.
2. **Game sync** — When a game is running, `game_sync.py` sets the lights to the game's colour. Weather sync does not send commands while a game is active.
3. **Weather sync** (lowest) — `weather_sync.py` sets the lights based on current weather conditions.

The priority system uses file-based state in the `state/` directory:
- `state/saved_state.json` — exists when an agent signal is active
- `state/signal_sessions/` — per-session marker files; one file per Claude session that raised the signal
- `state/game_active.json` — exists when game sync is active (contains the profile name); game sync rewrites this file every loop iteration as a heartbeat, and if it's older than 60 seconds it's considered stale so weather sync can resume
- `state/agent_signal.lock` — lock file used to serialise concurrent agent signal hooks

Concurrent `needs-input` and `clear` hooks are serialised with `state/agent_signal.lock` to prevent race conditions where multiple Claude sessions run the hooks simultaneously.

When a higher-priority source becomes inactive, the next source in the priority chain re-applies its colour on the next sync cycle.

### Per-session signal markers

When multiple Claude sessions are running, each session that raises the signal
writes a marker file to `state/signal_sessions/<session_id>`. When a session
clears the signal, only its own marker is removed. The lights stay orange until
the last session's marker is removed.

- Markers older than 8 hours (configurable via `signal.marker_max_age_hours`)
  are considered stale and are automatically deleted.
- If `saved_state.json` exists but the marker directory is empty or missing
  (legacy state from before this feature), the next `clear` restores the lights
  as before.
- `agent_signal.py clear --all` is a manual escape hatch that restores the
  lights regardless of remaining markers.

### Clear fallback

When `agent_signal.py clear` runs, it restores each strip that has saved state. For any configured strip that has no saved state — for example, a strip that did not answer `devStatus` when the signal was raised, or every strip when the saved-state marker is `[]` — it applies the config's `"default"` profile. If `"default"` is missing or `null`, it falls back to white at 40%. The lights never stay in the signal colour after `clear`. A strip whose saved colour equals the signal colour is treated as a stale reading and gets the default too, so a strip that really was set to the signal colour comes back as the default after clear.

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

Configuration in `config.json`:

```json
{
  "music": {
    "fps": 10,
    "smoothing": 0.5
  }
}
```

- `fps`: frames per second (default 10, clamped to 2-20)
- `smoothing`: exponential moving average factor (0-1, higher = less smoothing, default 0.5)

On exit (Ctrl+C), music_sync restores each strip to the colour/brightness it had
when it started.

## Autostart

Run weather sync and game sync automatically at Windows logon (hidden, no console
window). See [docs/autostart.md](docs/autostart.md) for install, uninstall, and
troubleshooting instructions.
