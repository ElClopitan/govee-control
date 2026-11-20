@echo off
rem Run tray.py hidden (pythonw), logging to state/tray.out.log
rem %~dp0 is this script's directory; .. is the repo root.
cd /d "%~dp0.."
if not exist state mkdir state
pythonw tray.py --config config.json >> state\tray.out.log 2>&1
