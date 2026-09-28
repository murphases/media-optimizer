@echo off
cd /d "%~dp0"
title Media Optimizer
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocorreu um erro ao executar o aplicativo.
    pause
)
