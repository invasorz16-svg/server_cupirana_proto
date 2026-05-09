@echo off
title VMC Control Center v3
cd /d "%~dp0"
python vmc_desktop_v3.py
if errorlevel 1 (
    echo.
    echo Error iniciando la app.
    pause
)
