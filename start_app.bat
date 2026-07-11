@echo off
title MANHWA.THAI - AI Translation System Launcher

echo ===============================================================================
echo MANHWA.THAI - AI Manga and Manhua Translation Platform (Local Launcher)
echo ===============================================================================

if not exist "%~dp0.env" (
    echo [WARNING] .env file not found in root directory!
    echo Please copy .env.example to .env and configure your Cloudflare R2 / Groq API keys.

    pause
    exit /b 1
)

echo [1/3] Clearing old server processes on ports 8000 and 5173...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8000, 5173 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" > nul 2>&1

echo [2/3] Starting Backend Server (FastAPI - Port 8000)...
start "Manhwa Backend API" /d "%~dp0backend" /min .venv\Scripts\python.exe -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

echo [3/3] Starting Frontend Web (React Vite - Port 5173)...
start "Manhwa Frontend Web" /d "%~dp0frontend" /min cmd /c "npm run dev -- --host"

echo Waiting for servers to initialize (3 seconds)...
timeout /t 3 /nobreak > nul

echo.
echo ===============================================================================
echo [SUCCESS] System is now running!
echo Web Reader       : http://localhost:5173
echo API Docs         : http://localhost:8000/docs
echo ===============================================================================

echo * Server processes are running in background windows.
echo * Press any key in this window to stop all servers and exit cleanly.

pause > nul

call "%~dp0stop.bat"
timeout /t 2 /nobreak > nul
