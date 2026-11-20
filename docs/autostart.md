# Autostart at logon

Run `weather_sync.py` and `game_sync.py` automatically when you log in to Windows,
hidden in the background (no console window).

## How it works

Two Windows scheduled tasks are registered for your user account:

- **Govee weather sync** — runs `weather_sync.py` via `pythonw.exe`
- **Govee game sync** — runs `game_sync.py` via `pythonw.exe`

Both tasks:
- Trigger at logon (current user only)
- Run hidden (no console window)
- Have no time limit
- Restart up to 3 times on failure (1 minute apart)
- Don't start a second instance if one is already running

## Install

```powershell
cd C:\path\to\Govee
powershell -NoProfile -File autostart\install.ps1
```

To preview what would be installed without making changes:

```powershell
powershell -NoProfile -File autostart\install.ps1 -DryRun
```

## Uninstall

```powershell
powershell -NoProfile -File autostart\install.ps1 -Uninstall
```

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

Output from both scripts is appended to log files in the `state/` directory:

- `state/weather_sync.out.log`
- `state/game_sync.out.log`

These files are not tracked by git.

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
