@echo off
rem Toggle music mode on/off. Double-click to use, or pin to taskbar/Stream Deck.
cd /d "%~dp0"
python music_sync.py toggle
