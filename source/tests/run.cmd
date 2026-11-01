@echo off
cd /d "%~dp0.."
set "GOCACHE=%CD%\vendor\go-cache"
set "GOPATH=%CD%\vendor\go-work"
set "GOMAXPROCS=1"
set "GOMEMLIMIT=192MiB"
set "GOGC=25"
set "CGO_ENABLED=0"
set "GOFLAGS=-mod=mod"
vendor\go-runtime\go\bin\go.exe test -p 1 -v ./src > evidence\tests.txt 2>&1
set "testResult=%errorlevel%"
type evidence\tests.txt
if not "%testResult%"=="0" exit /b %testResult%
vendor\go-runtime\go\bin\go.exe build -p 1 -o OpenDeploy.exe ./src
if errorlevel 1 exit /b 1
OpenDeploy.exe --self-test > evidence\flow-test.txt 2>&1
set "flowResult=%errorlevel%"
type evidence\flow-test.txt
exit /b %flowResult%
