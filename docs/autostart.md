# Autostart at logon

Run `weather_sync.py`, `game_sync.py`, and `tray.py` automatically when you log in
to Windows, hidden in the background (no console window).

## How it works

Three Windows scheduled tasks are registered for your user account:

- **Govee weather sync** — runs `pythonw.exe weather_sync.py` directly
- **Govee game sync** — runs `pythonw.exe game_sync.py` directly
- **Govee tray** — runs `pythonw.exe tray.py --config config.json` directly

All three tasks:
- Trigger at logon (current user only)
- Run hidden (no console window)
- Have no time limit
- Restart settings: up to 3 times, 1 minute apart (see Troubleshooting: not reliable when the script exits with an error)
- Don't start a second instance if one is already running
- Run with the repo root as the working directory

The install script is re-runnable: running it again replaces the existing tasks.

## Install

Before installing, install the tray dependencies:

```powershell
python -m pip install --user -r requirements-tray.txt
```

Then register the tasks:

```powershell
cd C:\path\to\Govee
powershell -NoProfile -File autostart\install.ps1
```

This registers the tasks and starts them immediately. The tasks will also run
at each logon.

Windows hides new tray icons under the "^" arrow in the taskbar; drag the icon
out to pin it.

To preview what would be installed without making changes:

```powershell
powershell -NoProfile -File autostart\install.ps1 -DryRun
```

To register the tasks but not start them immediately:

```powershell
powershell -NoProfile -File autostart\install.ps1 -NoStart
```

To use a specific pythonw.exe (useful if the first one on PATH is the Microsoft
Store stub or a different Python installation):

```powershell
powershell -NoProfile -File autostart\install.ps1 -PythonW C:\Python312\pythonw.exe
```

If the resolved pythonw.exe is the Microsoft Store stub
(`...\WindowsApps\pythonw.exe`), the script prints a warning suggesting you use
`-PythonW` to specify the real installation.

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

The weather and game sync tasks run with `--log-file` arguments, so their output
is written to log files with size rotation (1MB per file, 2 backups):

- `state/weather_sync.log` — weather sync log (weather fetches, colour changes, errors)
- `state/game_sync.log` — game sync log (profile switches, signal priority events, errors)

The tray task does not use `--log-file`. `tray.py` writes to `state/tray.log`
only when something fails (e.g., an exception in the tray loop).

The `autostart/run_tray.cmd` wrapper writes stdout/stderr to `state/tray.out.log`
while `tray.py`'s own error log is `state/tray.log`.

To see output in real time, run the scripts manually from a terminal:

```powershell
python weather_sync.py
python game_sync.py
python tray.py --config config.json
```

The `autostart/run_weather_sync.cmd`, `autostart/run_game_sync.cmd`, and
`autostart/run_tray.cmd` files remain as manual launchers that redirect output
to `state/*.out.log` files.

## Stop running scripts

The scheduled tasks run `pythonw.exe` processes. To stop them:

```powershell
# Find the processes (Get-CimInstance works on PowerShell 5.1)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*weather_sync*' -or $_.CommandLine -like '*game_sync*' -or $_.CommandLine -like '*tray.py*' } | Select-Object ProcessId, CommandLine

# Kill them (replace <ProcessId> with the actual ID from the output above)
Stop-Process -Id <ProcessId>
```

Or disable the tasks temporarily:

```powershell
Disable-ScheduledTask -TaskName "Govee weather sync"
Disable-ScheduledTask -TaskName "Govee game sync"
Disable-ScheduledTask -TaskName "Govee tray"
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
   - `state/tray.log`

3. If registration failed with "Access is denied", make sure you're running
   the install script as a normal user (not admin) and that the script is
   using the `-User` parameter with the AtLogOn trigger.

4. If the "Govee tray" task exits immediately with no icon appearing, pystray
   or Pillow may be missing. Check the task result:
   ```powershell
   Get-ScheduledTaskInfo -TaskName "Govee tray" | Format-List LastRunTime, LastTaskResult
   ```
   A `LastTaskResult` of 1 means the task failed. Install the tray dependencies:
   ```powershell
   python -m pip install --user -r requirements-tray.txt
   ```
   (Task Scheduler's RestartCount does not reliably restart a task that exits
   with a non-zero code, so the tray icon will not reappear automatically.)
