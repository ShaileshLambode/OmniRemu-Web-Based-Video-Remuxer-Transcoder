@echo off
title Stop OmniRemux Server
cd /d "%~dp0"
echo Stopping OmniRemux server...

set STOPPED=0

if exist ".omni.pid" (
    set /p OMNI_PID=<.omni.pid
    if defined OMNI_PID (
        echo Stopping OmniRemux process (PID %OMNI_PID%)...
        taskkill /f /pid %OMNI_PID% 2>nul
        if not errorlevel 1 set STOPPED=1
        del /f /q ".omni.pid" 2>nul
    )
)

if "%STOPPED%"=="0" (
    echo Checking for running OmniRemux server instances...
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*server.py*' -and $_.Name -like '*python*' }; foreach ($p in $procs) { Write-Host 'Stopping OmniRemux PID' $p.ProcessId; Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }" 2>nul
)

if exist ".omni.pid" del /f /q ".omni.pid" 2>nul

echo.
echo OmniRemux server has been stopped.
timeout /t 2 >nul
