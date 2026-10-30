@echo off
rem Double-click to install the fix together with the improvements (mouse-wheel zoom of the map).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" -Improvements %*
echo.
pause
