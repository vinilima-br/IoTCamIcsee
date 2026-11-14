@echo off
setlocal
cd /d "%~dp0"
title Instalador - Central de Cameras
REM ==================================================================
REM  Etapas 3 a 6 da instalacao (o bootstrap.bat faz a 1 e a 2):
REM    3) Python 3.12 em pacote zip, na pasta "python" AO LADO do projeto
REM       (ex.: C:\CentralCameras\python). A atualizacao automatica so
REM       mexe dentro da pasta do projeto, entao nunca toca nesse Python.
REM    4) Dependencias com o pip + teste de importacao
REM    5) Atalhos na Area de Trabalho e no menu Iniciar
REM    6) Abre a Central
REM  No PC de desenvolvimento (pasta com .git) usa o Python que ja existe.
REM  Tudo fica registrado em instalacao.log, ao lado da pasta do projeto.
REM ==================================================================

REM pasta acima do projeto - ex.: C:\CentralCameras
for %%I in ("%~dp0..") do set "BASE=%%~fI"
if "%BASE:~-1%"=="\" set "BASE=%BASE:~0,-1%"
REM Rodando sozinho (sem o bootstrap.bat): prepara o log e a marca de inicio.
REM Se nao der para gravar na pasta de cima, ficam dentro da pasta do projeto.
if defined CC_BOOTSTRAP goto log_ok
set "CC_INICIO_HORA=%time:~0,8%"
set "CC_LOG=%BASE%\instalacao.log"
set "CC_MARCA=%BASE%\_inicio.tmp"
if exist "%CC_MARCA%" del "%CC_MARCA%" >nul 2>nul
(>"%CC_MARCA%" echo %time%) 2>nul
if exist "%CC_MARCA%" goto log_ok
set "CC_LOG=%~dp0instalacao.log"
set "CC_MARCA=%~dp0_inicio.tmp"
(>"%CC_MARCA%" echo %time%) 2>nul
:log_ok

REM (sem bloco com parenteses: a pasta pode ter parenteses no nome)
if defined CC_BOOTSTRAP goto banner_ok
echo ===================================================
echo   INSTALADOR - Central de Cameras
echo   Log da instalacao: %CC_LOG%
echo ===================================================
:banner_ok
>>"%CC_LOG%" echo ==== INSTALAR.bat - %date% %time:~0,8% - pasta %~dp0

REM config.py deste PC (IPs e senhas): nasce do modelo, so na primeira vez
if not exist "%~dp0config.py" copy "%~dp0app\config_exemplo.py" "%~dp0config.py" >nul

REM ---------------- Etapa 3: Python ----------------
call :etapa 3 "Preparando o Python..."
if exist "%~dp0.git" goto python_dev

set "PYDIR=%BASE%\python"
set "PYZIP=%PYDIR%\tools\python.exe"
if not exist "%PYZIP%" goto python_baixar
REM ja existe: confere se esta inteiro - uma instalacao interrompida deixa pela metade
"%PYZIP%" -c "import encodings, ssl, zipfile" >>"%CC_LOG%" 2>&1
if errorlevel 1 goto python_baixar
echo     Python ja instalado em %PYDIR% - pulando o download.
>>"%CC_LOG%" echo     Python ja existia: %PYZIP%
goto python_pip

:python_baixar
echo     Baixando o Python 3.12.7 - pacote oficial em zip, sem instalador...
call :baixar "https://www.nuget.org/api/v2/package/python/3.12.7" "%BASE%\python-pkg.zip"
if errorlevel 1 goto falhou
echo     Extraindo o Python em %PYDIR%...
if not exist "%PYDIR%\" mkdir "%PYDIR%" >nul 2>nul
tar -xf "%BASE%\python-pkg.zip" -C "%PYDIR%" >>"%CC_LOG%" 2>&1
if errorlevel 1 (
  set "ERRO=Falha ao extrair o Python em %PYDIR%."
  goto falhou
)
del "%BASE%\python-pkg.zip" >nul 2>nul
if not exist "%PYZIP%" (
  set "ERRO=Extrai o Python, mas nao achei %PYZIP%."
  goto falhou
)

:python_pip
set "PY=%PYZIP%"
"%PY%" -m pip --version >>"%CC_LOG%" 2>&1
if not errorlevel 1 goto python_ok
echo     pip nao veio no pacote, instalando com ensurepip...
"%PY%" -m ensurepip --upgrade >>"%CC_LOG%" 2>&1
"%PY%" -m pip --version >>"%CC_LOG%" 2>&1
if errorlevel 1 (
  set "ERRO=Nao consegui deixar o pip funcionando."
  goto falhou
)
goto python_ok

:python_dev
echo     PC de desenvolvimento - pasta com .git: usando o Python que ja existe.
call "%~dp0app\_python.bat" >>"%CC_LOG%" 2>&1
if errorlevel 1 (
  set "ERRO=Python nao encontrado neste PC de desenvolvimento."
  goto falhou
)

:python_ok
REM confere que o _python.bat - usado pelo PAINEL e pelos outros .bat - acha o mesmo
set "PY_INST=%PY%"
call "%~dp0app\_python.bat" >nul 2>nul
if errorlevel 1 set "PY=%PY_INST%"
for /f "delims=" %%V in ('call "%PY%" -V 2^>^&1') do set "PY_VER=%%V"
echo     [OK] %PY_VER% em %PY%
>>"%CC_LOG%" echo     Python: %PY_VER% - %PY%

REM ---------------- Etapa 4: dependencias ----------------
call :etapa 4 "Instalando as dependencias com o pip..."
echo     Na primeira vez leva alguns minutos. Os maiores sao o opencv-python
echo     e o imageio-ffmpeg, cerca de 40 MB cada: acompanhe a barra abaixo.
echo.
"%PY%" -m pip install -r "%~dp0requirements.txt" --disable-pip-version-check --no-warn-script-location --log "%CC_LOG%"
if errorlevel 1 (
  set "ERRO=O pip nao conseguiu instalar as dependencias. Veja a mensagem acima."
  goto falhou
)
echo.
echo     Conferindo se todas as bibliotecas abrem...
"%PY%" -c "import cv2, numpy, flask, webview, edge_tts, Crypto, imageio_ffmpeg, clr" >>"%CC_LOG%" 2>&1
if errorlevel 1 (
  "%PY%" -c "import cv2, numpy, flask, webview, edge_tts, Crypto, imageio_ffmpeg, clr"
  set "ERRO=As dependencias foram instaladas, mas alguma nao abre. Veja a mensagem acima."
  goto falhou
)
echo     [OK] Dependencias prontas e testadas.
>>"%CC_LOG%" echo     teste de importacao OK

REM ---------------- Etapa 5: atalhos ----------------
call :etapa 5 "Criando os atalhos na Area de Trabalho e no menu Iniciar..."
call "%~dp0app\CRIAR_ATALHO.bat" /silencioso >>"%CC_LOG%" 2>&1
if errorlevel 1 (
  echo     [!] Nao criei o atalho. Da para criar depois com o app\CRIAR_ATALHO.bat.
) else (
  echo     [OK] Atalho "Central de Cameras" criado.
)
cd /d "%~dp0"

if not exist "%~dp0modelos\yolov8n.onnx" (
  echo     [!] Aviso: modelos\yolov8n.onnx nao encontrado.
  echo         O servidor sobe, mas a IA de deteccao so funciona com esse arquivo.
)

REM Versao instalada, lida do comentario do zip baixado pelo bootstrap.bat:
REM assim a atualizacao automatica nao baixa de novo o que acabou de vir.
if exist "%~dp0..\IoTCamIcsee.zip" (
  "%PY%" -c "import zipfile,sys,re; c=zipfile.ZipFile(sys.argv[1]).comment.decode('ascii','ignore').strip(); m=re.fullmatch('[0-9a-f]{40}', c); open(sys.argv[2],'w').write(m.group(0)+'\n') if m else None" "%~dp0..\IoTCamIcsee.zip" "%~dp0versao.txt" >>"%CC_LOG%" 2>&1
)

REM ---------------- Etapa 6: abrir ----------------
call :etapa 6 "Abrindo a Central - sessao das cameras + painel em janela propria..."
start "" "%~dp0PAINEL.bat"

echo.
echo ===================================================
echo  [OK] Instalacao concluida!
echo  Inicio: %CC_INICIO_HORA%   Fim: %time:~0,8%
"%PY%" -c "import os,sys,time; t=int(time.time()-os.path.getmtime(sys.argv[1])); m,s=divmod(t,60); print(' Tempo total:', m, 'min', str(s).zfill(2), 's')" "%CC_MARCA%" 2>nul
"%PY%" -c "import os,sys,time; t=int(time.time()-os.path.getmtime(sys.argv[1])); m,s=divmod(t,60); print('==== Instalacao concluida - tempo total:', m, 'min', str(s).zfill(2), 's ====')" "%CC_MARCA%" >>"%CC_LOG%" 2>nul
del "%CC_MARCA%" >nul 2>nul
echo.
echo  Das proximas vezes, abra pelo atalho
echo  "Central de Cameras" na Area de Trabalho.
echo  As cameras voce adiciona pela janela do painel,
echo  botao "+ Cameras" - ela ja procura na rede.
echo  No celular, mesma rede:  http://IP-DESTE-PC:5050
echo ===================================================
echo.
echo Esta janela fecha sozinha em 10 segundos...
timeout /t 10 >nul
exit

REM ==================================================================
REM  Sub-rotinas
REM ==================================================================

:etapa
REM %1 = numero da etapa, %2 = texto
echo.
echo [Etapa %~1 de 6] %time:~0,8%  %~2
>>"%CC_LOG%" echo [%time:~0,8%] Etapa %~1 de 6: %~2
exit /b 0

:baixar
REM %1 = endereco, %2 = arquivo de destino. A barra do curl fica na tela.
REM Em erro, deixa a explicacao em ERRO e sai com 1.
if exist "%~2" del "%~2" >nul 2>nul
curl.exe -L --fail --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 -o "%~2" "%~1"
set "RC=%errorlevel%"
REM curl antigo, sem --retry-all-errors, responde codigo 2: tenta sem essa opcao
if "%RC%"=="2" curl.exe -L --fail --retry 5 --retry-delay 3 --connect-timeout 30 -o "%~2" "%~1"
if "%RC%"=="2" set "RC=%errorlevel%"
>>"%CC_LOG%" echo     curl %~1 - codigo %RC%
if "%RC%"=="0" exit /b 0
set "ERRO=Falha no download de %~1 - curl codigo %RC%."
if "%RC%"=="6" set "ERRO=Sem internet ou sem DNS: nao achei o servidor de %~1. Confira a conexao e tente de novo."
if "%RC%"=="23" set "ERRO=Sem permissao para gravar em %~dp2"
if "%RC%"=="22" set "ERRO=O servidor respondeu com erro HTTP, ex.: 404, para %~1"
exit /b 1

:falhou
echo.
echo ===================================================
echo  [X] %ERRO%
echo  Hora: %time:~0,8%
echo  Log completo: %CC_LOG%
echo  Corrija e rode de novo: o que ja foi feito e aproveitado.
echo ===================================================
>>"%CC_LOG%" echo [X] %time:~0,8% ERRO: %ERRO%
echo.
pause
exit /b 1
