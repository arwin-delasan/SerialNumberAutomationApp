@echo off
start "SerialTracker" "\\172.16.0.4\Automation\Serial Number Automation\dist\SerialTracker\SerialTracker.exe"

:wait
curl -s --connect-timeout 1 --max-time 1 http://localhost:8000/login > nul 2>&1
if %errorlevel% neq 0 (
    timeout /t 1 /nobreak > nul
    goto wait
)
start "" http://localhost:8000
