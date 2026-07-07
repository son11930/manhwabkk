@echo off
chcp 65001 > nul
title MANHWA.THAI - 1-Click Updater

echo ===============================================================================
echo MANHWA.THAI - ระบบอัปเดตโค้ดอัตโนมัติ (1-Click Git Updater)
echo ===============================================================================

echo [1/3] Pulling latest code from GitHub (git pull)...
git pull
if %ERRORLEVEL% neq 0 (
    echo [ERROR] เกิดข้อผิดพลาดในการดึงโค้ดจาก Git!
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
echo [SUCCESS] อัปเดตระบบเสร็จสมบูรณ์ 100%%! คุณสามารถคลิกเปิด start_app.bat เพื่อใช้งานได้ทันทีครับ
echo ===============================================================================

pause
