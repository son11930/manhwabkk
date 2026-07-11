@echo off
title MANHWA.THAI - AI Translation System Stopper

echo ===============================================================================
echo MANHWA.THAI - Stopping AI Manga Translation Platform
echo ===============================================================================

echo [1/3] Closing launcher and terminal windows...
taskkill /F /FI "WINDOWTITLE eq Manhwa Backend API*" /T > nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Manhwa Frontend Web*" /T > nul 2>&1

echo [2/3] Terminating processes listening on ports 8000 (Backend) and 5173 (Frontend)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8000, 5173 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" > nul 2>&1

echo [3/3] Cleaning up orphaned uvicorn and vite background worker processes...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn src.main:app*' -or $_.CommandLine -like '*vite*' -and $_.Name -in 'node.exe','python.exe' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" > nul 2>&1

echo.
echo ===============================================================================
echo [SUCCESS] All MANHWA.THAI server processes and ports have been cleanly stopped!
echo ===============================================================================
echo.
timeout /t 3 /nobreak > nul
