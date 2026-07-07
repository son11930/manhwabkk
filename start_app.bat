@echo off
chcp 65001 > nul
title MANHWA.THAI - AI Translation System Launcher

echo ===============================================================================
echo MANHWA.THAI - AI Manga and Manhua Translation Platform (Local Launcher)
echo ===============================================================================

if not exist "%~dp0.env" (
    echo [WARNING] ไม่พบไฟล์ .env ในโฟลเดอร์หลัก!
    echo กรุณาคัดลอกไฟล์ .env.example เป็น .env และใส่รหัส Cloudflare R2 / Groq API ให้เรียบร้อยก่อนครับ

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
echo [SUCCESS] ระบบเปิดทำงานเรียบร้อยแล้ว!
echo Web Reader       : http://localhost:5173
echo API Docs         : http://localhost:8000/docs
echo ===============================================================================

echo * เซิร์ฟเวอร์กำลังทำงานในพื้นหลัง (Background Windows)
echo * หากต้องการปิดระบบ ให้กดปุ่มใดๆ ในหน้าต่างนี้เพื่อสั่งปิดเซิร์ฟเวอร์ทั้งหมดครับ

pause > nul

echo [STOPPING] กำลังปิดระบบเซิร์ฟเวอร์ทั้งหมด...
taskkill /F /IM uvicorn.exe /T > nul 2>&1
taskkill /F /IM node.exe /T > nul 2>&1
echo [DONE] ปิดระบบเรียบร้อยแล้วครับ!
timeout /t 2 /nobreak > nul
