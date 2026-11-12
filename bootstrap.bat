@echo off
setlocal
cd /d "%~dp0"
title Baixar e instalar a Central de Cameras

echo ===================================================
echo   Central de Cameras - baixar do GitHub e instalar
echo ===================================================
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo [X] Git nao encontrado neste PC.
  echo     Instale: https://git-scm.com/download/win
  echo     Depois rode este arquivo de novo.
  echo.
  pause
  exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
  echo [X] Python 3 nao encontrado neste PC.
  echo     Instale (marque "Add Python to PATH"):
  echo     https://www.python.org/downloads/
  echo     Depois rode este arquivo de novo.
  echo.
  pause
  exit /b 1
)

if exist "IoTCamIcsee\.git" (
  echo Projeto ja esta aqui. Atualizando do GitHub...
  cd IoTCamIcsee
  git pull
) else (
  echo Baixando o projeto do GitHub ^(pode pedir login do GitHub^)...
  git clone https://github.com/vinilima-br/IoTCamIcsee.git
  if errorlevel 1 (
    echo [X] Nao consegui baixar. Confira o login do GitHub e a internet.
    pause
    exit /b 1
  )
  cd IoTCamIcsee
)

if not exist "config.py" copy config_exemplo.py config.py >nul

echo.
echo Abrindo o instalador...
echo.
call INSTALAR.bat
