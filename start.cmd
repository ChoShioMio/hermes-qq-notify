@echo off
rem Foreground start WITH watchdog. Closing this window stops the service.
cd /d "%~dp0"
if exist ".stopped" del ".stopped"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" supervisor.py
