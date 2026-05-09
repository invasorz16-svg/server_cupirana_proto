@echo off
title VMC Control Center - Dashboard v4
echo.
echo ============================================================
echo   VMC Control Center - Dashboard Desktop v4
echo   Conectando a servidor local (localhost:8080)
echo ============================================================
echo.

REM Verificar Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no encontrado. Instala Python 3.10+ desde python.org
    pause
    exit /b 1
)

REM Instalar dependencias si es necesario
pip show requests >nul 2>&1
if %errorlevel% neq 0 (
    echo Instalando dependencias...
    pip install requests websocket-client
)

echo.
echo IMPORTANTE: Asegurate de ejecutar VMC-Server.bat primero
echo.

cd /d "%~dp0"
python vmc_desktop_v4.py

pause
