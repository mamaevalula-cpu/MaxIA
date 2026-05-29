@echo off
chcp 65001 >nul
title Personal AI
cd /d "%~dp0"

if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [!] Создан .env — заполни ключи и запусти снова
        pause
        exit /b
    )
)

echo [*] Запуск Personal AI...
python main.py %*
pause
