@echo off
title Stop OmniRemux Server
echo Stopping OmniRemux server running on port 5050...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5050" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a 2>nul
)
echo.
echo OmniRemux server has been stopped successfully.
timeout /t 3 >nul
