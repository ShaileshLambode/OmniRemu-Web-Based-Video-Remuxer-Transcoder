@echo off
title Stop OmniRemux Server
cd /d "%~dp0"
echo Stopping OmniRemux server...

if exist ".omni.pid" (
    set /p OMNI_PID=<.omni.pid
    if defined OMNI_PID (
        echo Stopping PID %OMNI_PID% from .omni.pid...
        taskkill /f /pid %OMNI_PID% 2>nul
        del /f /q ".omni.pid" 2>nul
    )
)

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5050" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a 2>nul
)

echo.
echo OmniRemux server has been stopped.
timeout /t 3 >nul
