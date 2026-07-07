@echo off
title MANHWA.THAI - 1-Click Updater

echo ===============================================================================
echo MANHWA.THAI - Automated System Updater (1-Click Git Updater)
echo ===============================================================================

echo [1/3] Pulling latest code from GitHub (git pull)...
git pull
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to pull code from Git repository!
    pause
    exit /b 1
)

echo.
echo [2/3] Updating Backend python dependencies...
cd /d "%~dp0backend"
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet

echo.
echo [3/3] Building new Frontend Web package...
cd /d "%~dp0frontend"
call npm install --silent
call npm run build

echo.
echo ===============================================================================
echo [SUCCESS] Update completed 100%%! You can now run start_app.bat to start.
echo ===============================================================================

pause
