@echo off
setlocal
cd /d "%~dp0"
title Instalador - Central de Cameras

echo ===================================================
echo    INSTALADOR - Central de Cameras
echo ===================================================
echo.

REM ---------- 1) Python ----------
where python >nul 2>nul
if errorlevel 1 (
  echo [X] Python 3 nao encontrado neste PC.
  echo     Instale em: https://www.python.org/downloads/
  echo     IMPORTANTE: marque "Add Python to PATH" na instalacao.
  echo     Depois, rode este arquivo de novo.
  echo.
  pause
  exit /b 1
)
echo [OK] Python encontrado.
echo.

REM ---------- 2) Dependencias ----------
echo [1/3] Instalando dependencias (pode demorar na primeira vez)...
python -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo [X] Falha ao instalar as dependencias. Veja a mensagem acima.
  pause
  exit /b 1
)
echo [OK] Dependencias prontas.
echo.

if not exist "modelos\yolov8n.onnx" (
  echo [!] Aviso: modelos\yolov8n.onnx nao encontrado.
  echo     O servidor sobe, mas a IA de deteccao so funciona com esse arquivo.
  echo.
)

REM ---------- 3) Camera nova (opcional) ----------
echo [2/3] Camera nova
echo     Antes de responder "s": a camera deve estar RECEM-configurada no app
echo     do fabricante (janela do admin aberta) e com IP FIXO no roteador.
echo.
set "RESP="
set /p "RESP=Configurar uma camera nova agora? (s/n): "
if /i not "%RESP%"=="s" goto subir

set "IP="
set "EMAIL="
set "FIXA="
set /p "IP=  IP da camera (ex 192.168.3.50): "
set /p "EMAIL=  E-mail do app da camera: "
set /p "FIXA=  Senha FIXA que a camera vai passar a usar: "
echo.
echo Provisionando... (vai pedir a senha do app; ela NAO aparece ao digitar)
python ferramentas\provisionar.py %IP% %EMAIL% --senha-fixa %FIXA% --gravar
echo.
echo (Se deu erro acima, da para configurar depois com o provisionar.py.
echo  O servidor sobe do mesmo jeito.)
echo.

:subir
echo [3/3] Subindo a Central (sessao das cameras + servidor)...
start "" "%~dp0INICIAR.bat"
echo.
echo ===================================================
echo  Pronto! O painel abre em:  http://localhost:5050
echo  No celular (mesma rede):   http://IP-DESTE-PC:5050
echo ===================================================
echo.
pause
endlocal
