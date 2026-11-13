@echo off
setlocal
cd /d "%~dp0"
title Instalador - Central de Cameras

echo ===================================================
echo    INSTALADOR - Central de Cameras
echo ===================================================
echo.

REM ---------- 1) Python (instala sozinho se faltar) ----------
call "%~dp0_python.bat" >nul 2>nul
if not errorlevel 1 goto tem_python

echo [*] Python nao encontrado. Vou instalar agora...
where winget >nul 2>nul
if errorlevel 1 goto baixa_python
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
goto confere_python

:baixa_python
echo     Baixando o instalador oficial do Python...
curl.exe -L -o python-setup.exe https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe
if errorlevel 1 (
  echo [X] Falha ao baixar o Python. Confira a internet.
  pause
  exit /b 1
)
echo     Instalando o Python em modo silencioso, aguarde cerca de 1 minuto...
python-setup.exe /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1
del python-setup.exe >nul 2>nul

:confere_python
REM acha o Python recem-instalado pela pasta (nao precisa reabrir a janela)
call "%~dp0_python.bat" >nul 2>nul
if not errorlevel 1 goto tem_python
echo.
echo ===================================================
echo  Python instalado, mas nao consegui acha-lo ainda.
echo  FECHE esta janela e rode o INSTALAR.bat DE NOVO.
echo ===================================================
echo.
pause
exit /b 0

:tem_python
echo [OK] Python encontrado: %PY%
echo.

REM ---------- 2) Dependencias ----------
echo [1/3] Instalando dependencias (pode demorar na primeira vez)...
"%PY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo [X] Falha ao instalar as dependencias. Veja a mensagem acima.
  pause
  exit /b 1
)
echo [OK] Dependencias prontas.
echo.

REM ---------- Atalho com icone (Area de Trabalho + menu Iniciar) ----------
echo [*] Criando o atalho "Central de Cameras" na Area de Trabalho...
call "%~dp0CRIAR_ATALHO.bat" /silencioso
if errorlevel 1 echo [!] Nao criei o atalho. Da para criar depois com o CRIAR_ATALHO.bat.
echo.

if not exist "modelos\yolov8n.onnx" (
  echo [!] Aviso: modelos\yolov8n.onnx nao encontrado.
  echo     O servidor sobe, mas a IA de deteccao so funciona com esse arquivo.
  echo.
)

REM ---------- 3) Camera nova (opcional) ----------
echo [2/3] Camera nova
echo     Antes de responder "s": a camera deve estar RECEM-configurada no app
echo     do fabricante, com a janela do admin aberta, e com IP FIXO no roteador.
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
echo Provisionando... a senha do app sera pedida e nao aparece ao digitar.
"%PY%" ferramentas\provisionar.py %IP% %EMAIL% --senha-fixa %FIXA% --gravar
echo.
echo Se deu erro acima, da para configurar depois com o provisionar.py.
echo O servidor sobe do mesmo jeito.
echo.

:subir
echo [3/3] Abrindo a Central (sessao das cameras + painel em janela propria)...
start "" "%~dp0PAINEL.bat"
echo.
echo ===================================================
echo  Pronto! Das proximas vezes, abra pelo atalho
echo  "Central de Cameras" na Area de Trabalho.
echo  No navegador deste PC:   http://localhost:5050
echo  No celular, mesma rede:  http://IP-DESTE-PC:5050
echo ===================================================
echo.
pause
