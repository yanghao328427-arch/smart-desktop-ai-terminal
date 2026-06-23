@echo off
setlocal
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_defense_demo.ps1" %*
if errorlevel 1 (
  echo.
  echo Defense demo launcher exited with error %errorlevel%.
  pause
)
