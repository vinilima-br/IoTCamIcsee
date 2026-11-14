@echo off
setlocal
cd /d "%~dp0"
title Central de Cameras - instalar sem Git

echo ===================================================
echo   Central de Cameras - baixar do GitHub e instalar
echo ===================================================
echo.

REM O Python (se faltar) e instalado pelo INSTALAR.bat, logo depois de baixar.

:baixar
echo [1/3] Baixando o projeto do GitHub...
curl.exe -L -o IoTCamIcsee.zip https://github.com/vinilima-br/IoTCamIcsee/archive/refs/heads/main.zip
if errorlevel 1 (
  echo [X] Falha ao baixar. Confira a internet e se o repositorio esta publico.
  pause
  exit /b 1
)

echo [2/3] Descompactando...
tar -xf IoTCamIcsee.zip
if errorlevel 1 (
  echo [X] Falha ao descompactar.
  pause
  exit /b 1
)
cd IoTCamIcsee-main

if not exist "config.py" copy "app\config_exemplo.py" "config.py" >nul

echo [3/3] Instalando e subindo...
echo.
call INSTALAR.bat
