@echo off
title Repasse Telegram - Iniciando...
cd /d "%~dp0"
echo ===================================================
echo Iniciando o Repasse Telegram no ambiente virtual...
echo ===================================================
.venv\Scripts\python.exe main.py
if %errorlevel% neq 0 (
    echo.
    echo Ocorreu um erro ao iniciar a aplicacao.
    pause
)
