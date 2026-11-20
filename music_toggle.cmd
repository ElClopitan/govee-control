@echo off
rem Turn on music mode. Double-click to use, or pin to taskbar/Stream Deck.
rem Music mode stays on even when silent or no audio device (lights go black).
cd /d "%~dp0"
python mode.py set music
if errorlevel 1 pause
