@echo off
chcp 65001 >nul
title Personal AI

set "MY_AI=C:\Users\ACER\Desktop\cloude\my_personal_ai"
set "BYBIT_BOT=C:\Users\ACER\Desktop\cloude\bybit-bot"
set "PY=%BYBIT_BOT%\venv\Scripts\python.exe"
set "PYTHONPATH=%MY_AI%;%BYBIT_BOT%"
set "PYTHONIOENCODING=utf-8"

cd /d "%MY_AI%"
if not exist logs mkdir logs

echo.
echo  Personal AI - Zapusk sistemy...
echo  Podozhdite 15-20 sekund, okno poyavitsya avtomaticheski.
echo.

"%PY%" launch.py --no-telegram

if errorlevel 1 (
    echo.
    echo  [!] Oshibka:
    type logs\startup_err.log 2>nul
    pause
)
