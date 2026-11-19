# Govee control

Local automation for two Govee COB strip lights (Windows PC).
Project board: Govee (epiq), parent ticket Z6KCSBZ.

Planned pieces: LAN client + CLI (`govee.py`), game-process colour sync,
Stream Deck wrappers, weather sync, "agent needs input" signal.

Setup: copy `config.example.json` to `config.json` and fill in device IPs.
In the Govee Home app, enable **LAN Control** on each strip (device settings).
