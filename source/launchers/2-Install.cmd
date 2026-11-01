@echo off
cd /d "%~dp0"
"%~dp0OpenDeploy.exe" --run --stage=install --plan "%~dp0plan.json"
exit /b %errorlevel%
