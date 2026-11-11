@echo off
rem Stop BOTH watchdog and notifier, scoped to this directory.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
exit /b %errorlevel%
