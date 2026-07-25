@echo off
cd /d "%~dp0"
title Instalando dependencias
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
echo Instalacao concluida!
pause