@echo off
setlocal
cd /d "%~dp0"
title Central de Cameras - instalar (sem Git)

echo ===================================================
echo   Central de Cameras - baixar do GitHub e instalar
echo ===================================================
echo.

REM ---------- Python (instala sozinho se faltar) ----------
where python >nul 2>nul
if not errorlevel 1 goto baixar

echo [*] Python nao encontrado. Vou tentar instalar sozinho (winget)...
where winget >nul 2>nul
if errorlevel 1 (
  echo [X] Este Windows nao tem o winget.
  echo     Instale o Python a mao, marcando "Add Python to PATH":
  echo     https://www.python.org/downloads/
  echo     Depois rode este arquivo de novo.
  echo.
  pause
  exit /b 1
)
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
echo.
echo ===================================================
echo  Python instalado. FECHE esta janela e rode o
echo  bootstrap.bat DE NOVO (pra ele enxergar o Python).
echo ===================================================
echo.
pause
exit /b 0

:baixar
echo [1/3] Baixando o projeto do GitHub...
curl -L -o IoTCamIcsee.zip https://github.com/vinilima-br/IoTCamIcsee/archive/refs/heads/main.zip
if errorlevel 1 (
  echo [X] Falha ao baixar. Confira a internet (e se o repositorio esta PUBLICO).
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

if not exist "config.py" copy config_exemplo.py config.py >nul

echo [3/3] Instalando e subindo...
echo.
call INSTALAR.bat
