@echo off
rem Run weather_sync.py hidden (pythonw), logging to state/weather_sync.out.log
rem %~dp0 is this script's directory; .. is the repo root.
cd /d "%~dp0.."
if not exist state mkdir state
pythonw weather_sync.py >> state\weather_sync.out.log 2>&1
