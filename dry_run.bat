@echo off
cd /d "%~dp0"
title CoC Bot - Dry Run
.venv\Scripts\python.exe -m coc_bot.main --dry-run %*
pause