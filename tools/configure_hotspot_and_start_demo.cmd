@echo off
setlocal
cd /d "%~dp0\.."
call "%~dp0start_defense_demo.cmd" -ConfigureHotspot %*
