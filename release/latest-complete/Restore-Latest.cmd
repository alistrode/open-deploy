@echo off
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0Restore-Latest.ps1" %*
exit /b %errorlevel%
