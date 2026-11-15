@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_portal.ps1" -Role alumni
if errorlevel 1 pause
