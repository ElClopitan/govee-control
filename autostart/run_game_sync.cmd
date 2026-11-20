@echo off
rem Run game_sync.py hidden (pythonw), logging to state/game_sync.out.log
rem %~dp0 is this script's directory; .. is the repo root.
cd /d "%~dp0.."
if not exist state mkdir state
pythonw game_sync.py >> state\game_sync.out.log 2>&1
