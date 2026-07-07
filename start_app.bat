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

echo [1/3] Starting Backend Server (FastAPI - Port 8000)...
start "Manhwa Backend API" /d "%~dp0backend" /min .venv\Scripts\python.exe -m uvicorn src.main:app --reload --port 8000

echo [2/3] Starting Frontend Web (React Vite - Port 5173)...
start "Manhwa Frontend Web" /d "%~dp0frontend" /min cmd /c "npm run dev -- --host"

echo [3/3] Waiting for servers to initialize (3 seconds)...
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

echo [STOPPING] Shutting down all server processes...
taskkill /F /IM uvicorn.exe /T > nul 2>&1
taskkill /F /IM node.exe /T > nul 2>&1
echo [DONE] All servers stopped successfully. Good bye!
timeout /t 2 /nobreak > nul
