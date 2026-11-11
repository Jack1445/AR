@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_ar.ps1"
set "AR_SETUP_EXIT=%ERRORLEVEL%"
pause
exit /b %AR_SETUP_EXIT%
