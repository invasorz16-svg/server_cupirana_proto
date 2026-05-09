@echo off
title VMC Control Center
cd /d "%~dp0"
python vmc_desktop.py
if errorlevel 1 (
    echo.
    echo Error iniciando la app. Verifica que Python este instalado.
    pause
)
