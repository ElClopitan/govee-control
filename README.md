# Govee control

Local automation for two Govee COB strip lights (Windows PC).
Project board: Govee (epiq), parent ticket Z6KCSBZ.

Planned pieces: LAN client + CLI (`govee.py`), game-process colour sync,
Stream Deck wrappers, weather sync, "agent needs input" signal.

Setup: copy `config.example.json` to `config.json` and fill in device IPs.
In the Govee Home app, enable **LAN Control** on each strip (device settings).

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
    }
  ]
}
```

The `exe` field is matched case-insensitively against running process names.
When multiple games match, the first one in config order wins.

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
