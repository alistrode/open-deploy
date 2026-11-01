@echo off
cd /d "%~dp0"
"%~dp0OpenDeploy.exe" --run --stage=drivers --plan "%~dp0plan.json"
exit /b %errorlevel%
