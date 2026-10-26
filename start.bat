@echo off
title OmniRemux - Video Converter & Remuxer
echo Starting OmniRemux Local Web Server...
cd /d "%~dp0"
start http://localhost:5050
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe server.py 5050
) else (
    python server.py 5050
)
pause
