# Autostart at logon

Run `weather_sync.py` and `game_sync.py` automatically when you log in to Windows,
hidden in the background (no console window).

## How it works

Two Windows scheduled tasks are registered for your user account:

- **Govee weather sync** — runs `pythonw.exe weather_sync.py` directly
- **Govee game sync** — runs `pythonw.exe game_sync.py` directly

Both tasks:
- Trigger at logon (current user only)
- Run hidden (no console window)
- Have no time limit
- Restart up to 3 times on failure (1 minute apart)
- Don't start a second instance if one is already running
- Run with the repo root as the working directory

The install script is re-runnable: running it again replaces the existing tasks.

## Install

```powershell
cd C:\path\to\Govee
powershell -NoProfile -File autostart\install.ps1
```

This registers the tasks and starts them immediately. The tasks will also run
at each logon.

To preview what would be installed without making changes:

```powershell
powershell -NoProfile -File autostart\install.ps1 -DryRun
```

To register the tasks but not start them immediately:

```powershell
powershell -NoProfile -File autostart\install.ps1 -NoStart
```

## Uninstall

```powershell
powershell -NoProfile -File autostart\install.ps1 -Uninstall
```

This stops any running tasks and removes them.

## Check status

List the tasks:

```powershell
Get-ScheduledTask -TaskName "Govee*" | Format-Table TaskName, State, LastRunTime
```

Start a task manually (useful for testing):

```powershell
Start-ScheduledTask -TaskName "Govee weather sync"
```

## Logs

The scheduled tasks run `pythonw.exe` directly with `--log-file` arguments,
so output is written to log files with size rotation (1MB per file, 2 backups):

- `state/weather_sync.log` — weather sync log
- `state/game_sync.log` — game sync log

Both scripts use Python's `logging` module. `weather_sync.py` logs weather
fetches, colour changes, and errors. `game_sync.py` logs profile switches,
signal priority events, and errors.

To see output in real time, run the scripts manually from a terminal:

```powershell
python weather_sync.py
python game_sync.py
```

The `autostart/run_weather_sync.cmd` and `autostart/run_game_sync.cmd` files
remain as manual launchers that redirect output to `state/*.out.log` files.

## Stop running scripts

The scheduled tasks run `pythonw.exe` processes. To stop them:

```powershell
# Find the processes
Get-Process pythonw | Where-Object { $_.CommandLine -like "*weather_sync*" -or $_.CommandLine -like "*game_sync*" }

# Kill them (replace PID with actual process ID)
Stop-Process -Id <PID>
```

Or disable the tasks temporarily:

```powershell
Disable-ScheduledTask -TaskName "Govee weather sync"
Disable-ScheduledTask -TaskName "Govee game sync"
```

Re-enable with `Enable-ScheduledTask`.

## Troubleshooting

If the tasks don't seem to be running:

1. Check that the tasks are registered and enabled:
   ```powershell
   Get-ScheduledTask -TaskName "Govee*" | Format-Table TaskName, State, Enabled
   ```

2. Check the log files for errors:
   - `state/weather_sync.log`
   - `state/game_sync.log`

3. If registration failed with "Access is denied", make sure you're running
   the install script as a normal user (not admin) and that the script is
   using the `-User` parameter with the AtLogOn trigger.
