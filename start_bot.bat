@echo off
cd /d "%~dp0"
title CoC Donation Bot

echo ============================================
echo    CoC Donation Bot - LDPlayer
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found!
    pause
    exit /b 1
)

set ADB_PATH=
if exist "C:\LDPlayer\LDPlayer9\adb.exe" set "ADB_PATH=C:\LDPlayer\LDPlayer9"
if exist "D:\LDPlayer\LDPlayer9\adb.exe" set "ADB_PATH=D:\LDPlayer\LDPlayer9"
if defined ADB_PATH set "PATH=%ADB_PATH%;%PATH%"

echo Starting bot...
.venv\Scripts\python.exe -m coc_bot.main %*

echo Bot stopped.
pause