@echo off
cd /d "%~dp0"
:restart
"runtime\node.exe" "app\start.cjs" >nul 2>>"data\errors.log"
ping.exe -n 11 127.0.0.1 >nul
goto restart
