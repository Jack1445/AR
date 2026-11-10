@echo off
cd /d "%~dp0"
if not exist "%~dp0web\data.js" (
  echo Local data is missing. Run python ar.py pull --all-tables in your Conda PowerShell first.
  pause
  exit /b 1
)
set "AR_URL=http://127.0.0.1:38479/"
set "AR_PYTHONW=D:\Miniconda3\pythonw.exe"
curl.exe -fsS --noproxy "*" --max-time 1 "%AR_URL%health" >nul 2>nul
if errorlevel 1 (
  if not exist "%AR_PYTHONW%" (
    echo Python was not found at D:\Miniconda3\pythonw.exe. Run python web_server.py in your Conda PowerShell.
    pause
    exit /b 1
  )
  start "" "%AR_PYTHONW%" "%~dp0web_server.py"
  for /l %%I in (1,1,10) do (
    timeout /t 1 /nobreak >nul
    curl.exe -fsS --noproxy "*" --max-time 1 "%AR_URL%health" >nul 2>nul
    if not errorlevel 1 goto browser_ready
  )
  echo AR local server did not start. Run python web_server.py in your Conda PowerShell to see the error.
  pause
  exit /b 1
)
:browser_ready
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" (
  start "" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" "%AR_URL%"
  exit /b 0
)
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" (
  start "" "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" "%AR_URL%"
  exit /b 0
)
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
  start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" "%AR_URL%"
  exit /b 0
)
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
  start "" "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" "%AR_URL%"
  exit /b 0
)
echo Edge or Chrome was not found. Open %AR_URL% in your browser.
pause
exit /b 1
