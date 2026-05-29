@echo off
chcp 65001 >nul
title Personal AI - Server Dashboard

cd /d "%~dp0"

python server_dashboard.py %*

if errorlevel 1 (
    echo.
    echo Oshibka. Nazhmite lyubuyu klavishu...
    pause > nul
)
