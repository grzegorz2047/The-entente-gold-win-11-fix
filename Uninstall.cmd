@echo off
rem Double-click to remove the fix and restore the original game files.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\uninstall.ps1" %*
echo.
pause
