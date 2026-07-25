@echo off
cd /d "%~dp0"
title CoC Bot - Calibracao
.venv\Scripts\python.exe scripts\calibrate.py %*
pause