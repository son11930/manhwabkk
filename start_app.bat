@echo off
chcp 65001 > nul
title MANHWA.THAI - AI Translation System Launcher

echo ===============================================================================
echo 🚀 MANHWA.THAI - AI Manga ^& Manhua Translation Platform (Local Launcher)
echo ===============================================================================
echo.

:: Check if .env file exists
if not exist "%~dp0.env" (
    echo ⚠️  ไม่พบไฟล์ .env ในโฟลเดอร์หลัก!
    echo กรุณาคัดลอกไฟล์ .env.example เป็น .env และใส่รหัส Cloudflare R2 / Groq API ให้เรียบร้อยก่อนครับ
    echo.
    pause
    exit /b 1
)

echo [1/3] 🔌 กำลังเริ่มต้นระบบหลังบ้าน (Backend FastAPI - Port 8000)...
start "Manhwa Backend API (Port 8000)" /min cmd /c "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn src.main:app --reload --port 8000"

echo [2/3] 💻 กำลังเริ่มต้นระบบหน้าบ้าน (Frontend React Vite - Port 5173)...
start "Manhwa Frontend Web (Port 5173)" /min cmd /c "cd /d "%~dp0frontend" && npm run dev -- --host"

echo [3/3] ⏳ กำลังรอให้ระบบเซิร์ฟเวอร์เตรียมพร้อม (ประมาณ 3 วินาที)...
timeout /t 3 /nobreak > nul

echo.
echo ===============================================================================
echo ✅ ระบบเปิดทำงานเรียบร้อยแล้ว!
echo 🌐 หน้าเว็บอ่านการ์ตูน : http://localhost:5173
echo ⚙️  API Documentation  : http://localhost:8000/docs
echo ===============================================================================
echo.
echo * หน้าต่างเซิร์ฟเวอร์กำลังทำงานในพื้นหลัง (Background Windows)
echo * หากต้องการปิดระบบ ให้กดปุ่มใดๆ ในหน้าต่างนี้เพื่อสั่งปิดเซิร์ฟเวอร์ทั้งหมดครับ
echo.
pause > nul

echo 🛑 กำลังปิดระบบเซิร์ฟเวอร์ทั้งหมด...
taskkill /F /IM uvicorn.exe /T > nul 2>&1
taskkill /F /IM node.exe /T > nul 2>&1
echo 🏁 ปิดระบบเรียบร้อยแล้วครับ!
timeout /t 2 /nobreak > nul
