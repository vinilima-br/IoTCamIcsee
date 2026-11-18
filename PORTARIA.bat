@echo off
setlocal
cd /d "%~dp0"
title Portaria - Controle de acesso

if exist "%~dp0Portaria.exe" (
  "%~dp0Portaria.exe"
  exit /b
)

set "PY=%~dp0python\python.exe"
if not exist "%PY%" set "PY=%~dp0python\tools\python.exe"
if not exist "%PY%" (
  echo [X] Python portatil nao encontrado em python\python.exe.
  echo     Instale o runtime local antes de iniciar a Portaria.
  pause
  exit /b 1
)

"%PY%" -c "import fastapi, sqlalchemy, uvicorn, webview" 2>nul
if errorlevel 1 (
  echo [X] Dependencias da Portaria ausentes no Python portatil.
  echo     Rode BUILD_PORTARIA.bat na maquina de preparo e copie o pacote offline.
  pause
  exit /b 1
)

if not exist "%~dp0config.py" (
  echo [!] config.py nao encontrado. A Portaria iniciara sem a integracao de cameras.
)

"%PY%" desktop_app.py
if errorlevel 1 (
  echo.
  echo [X] A Portaria foi encerrada com erro.
  pause
)
endlocal
