@echo off
rem Start with NO window (same path the logon autostart uses). Safe to double-click twice.
cd /d "%~dp0"
if exist ".stopped" del ".stopped"
wscript //nologo autostart.vbs
echo Started in background. Check status: curl http://127.0.0.1:8787/health
timeout /t 2 >nul
