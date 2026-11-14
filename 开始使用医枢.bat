@echo off
setlocal
cd /d "%~dp0mednexus"
title MedNexus
rem If the app is already running on port 7860, just open the browser instead of starting a second copy.
netstat -ano | findstr /R /C:"LISTENING" | findstr /C:":7860 " >nul 2>nul
if not errorlevel 1 (
  echo MedNexus is already running. Opening http://127.0.0.1:7860 ...
  start "" http://127.0.0.1:7860
  goto end
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 server.py --open
  goto end
)
where python >nul 2>nul
if not errorlevel 1 (
  python server.py --open
  goto end
)
echo Python 3.10 or later is required. Install it from https://www.python.org/downloads/
:end
if errorlevel 1 pause
endlocal