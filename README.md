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
