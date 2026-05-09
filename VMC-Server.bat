@echo off
title VMC Control Center - Servidor Local v2.0
echo.
echo ============================================================
echo   VMC Control Center - Servidor Local v2.0
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
echo Verificando dependencias...
pip show fastapi >nul 2>&1
if %errorlevel% neq 0 (
    echo Instalando FastAPI...
    pip install fastapi uvicorn aiosqlite
)

echo.
echo Iniciando servidor en http://localhost:8080
echo API Docs en http://localhost:8080/docs
echo.
echo Presiona Ctrl+C para detener el servidor
echo.

cd /d "%~dp0"
python vmc_server.py

pause
