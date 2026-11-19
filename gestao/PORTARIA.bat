@echo off
setlocal
REM Modo ISOLADO da gestao (para desenvolver). No dia a dia ela abre dentro do
REM painel: aba Facial -> "Gestao de pessoas e acessos".
cd /d "%~dp0.."
title Portaria - Controle de acesso (modo isolado)

if exist "%CD%\Portaria.exe" (
  "%CD%\Portaria.exe"
  exit /b
)

REM Mesmo Python da Central de Cameras (acha sozinho, sem depender do PATH)
call "%CD%\app\_python.bat" || (pause & exit /b 1)

REM Painel e Portaria nao podem ficar abertos juntos: os dois abrem as cameras
"%PY%" -c "import socket,sys;sys.path.insert(0,'.');p=5050;exec('try:\n import config;p=getattr(config,\'WEB_PORTA\',5050)\nexcept Exception: pass');s=socket.socket();s.settimeout(0.5);sys.exit(1 if s.connect_ex(('127.0.0.1',p))==0 else 0)"
if errorlevel 1 (
  echo [X] A Central de Cameras ^(PAINEL^) esta aberta.
  echo     Feche o Painel antes de abrir a Portaria: os dois usam as mesmas cameras.
  pause
  exit /b 1
)

"%PY%" -c "import fastapi, sqlalchemy, uvicorn, websockets, python_multipart, webview" 2>nul
if errorlevel 1 (
  echo Instalando as dependencias da Portaria, so na primeira vez...
  "%PY%" -m pip install -r "%CD%\gestao\api\requirements.txt" pywebview --disable-pip-version-check --no-warn-script-location
  if errorlevel 1 (
    echo [X] Nao foi possivel instalar as dependencias. Veja as mensagens acima.
    pause
    exit /b 1
  )
)

if not exist "%CD%\config.py" (
  echo [!] config.py nao encontrado. A Portaria iniciara sem a integracao de cameras.
)

"%PY%" gestao\desktop_app.py
if errorlevel 1 (
  echo.
  echo [X] A Portaria foi encerrada com erro. Veja as mensagens acima.
  pause
)
endlocal
