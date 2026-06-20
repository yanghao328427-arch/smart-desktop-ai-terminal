@echo off
setlocal
cd /d "%~dp0\.."
python -u tools\laptop_realtime_listener.py
if errorlevel 1 (
  echo.
  echo laptop_realtime_listener exited with error %errorlevel%.
  pause
)
