@echo off
rem Double-click to install the Windows 10/11 fix for The Entente Gold (Steam).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
echo.
pause
