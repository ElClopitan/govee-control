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
game's configured colour. When no game is running, it restores a default.

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
- `state/game_active.json` — exists when game sync is active (contains the profile name)

When a higher-priority source becomes inactive, the next source in the priority chain re-applies its colour on the next sync cycle.
