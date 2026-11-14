@echo off
setlocal
title Central de Cameras - instalador
REM ==================================================================
REM  Instala a Central de Cameras num PC zerado, sem Git e sem Python.
REM  Baixe este arquivo e de dois cliques: ele baixa o projeto para
REM  C:\CentralCameras e chama o INSTALAR.bat, que faz o resto.
REM
REM  Este arquivo NAO usa rotulos nem goto de proposito: assim ele roda
REM  certo mesmo se chegar ao PC com quebra de linha do Linux (LF).
REM ==================================================================

REM Pasta fixa e sempre gravavel. Antes era a pasta do proprio .bat,
REM que pode ser somente leitura - pendrive, rede, Program Files...
set "DESTINO=C:\CentralCameras"
set "CC_LOG=%DESTINO%\instalacao.log"
set "CC_BOOTSTRAP=1"
set "ZIP_URL=https://github.com/vinilima-br/IoTCamIcsee/archive/refs/heads/main.zip"

REM Hora do inicio. O tempo total sai da data do arquivo _inicio.tmp,
REM calculado pelo Python no fim - nao depende do formato de hora do Windows.
set "CC_INICIO_HORA=%time:~0,8%"
set "CC_MARCA=%DESTINO%\_inicio.tmp"

echo ===================================================
echo   Central de Cameras - instalacao completa
echo   Pasta de instalacao: %DESTINO%
echo   Log da instalacao:   %CC_LOG%
echo   Inicio: %CC_INICIO_HORA%
echo ===================================================

if not exist "%DESTINO%\" mkdir "%DESTINO%" >nul 2>nul
if not exist "%DESTINO%\" (
  echo.
  echo [X] Nao consegui criar a pasta %DESTINO%.
  echo     Clique com o botao direito no bootstrap.bat e use Executar como administrador.
  pause
  exit /b 1
)
if exist "%CC_LOG%" del "%CC_LOG%" >nul 2>nul
(>"%CC_LOG%" echo ==== Instalacao da Central de Cameras - %date% %time:~0,8% ====) 2>nul
if exist "%CC_MARCA%" del "%CC_MARCA%" >nul 2>nul
(>"%CC_MARCA%" echo %time%) 2>nul
if not exist "%CC_MARCA%" (
  echo.
  echo [X] Sem permissao para gravar em %DESTINO%.
  echo     Clique com o botao direito no bootstrap.bat e use Executar como administrador.
  pause
  exit /b 1
)
cd /d "%DESTINO%"

REM ---------------- Etapa 1: baixar o projeto ----------------
echo.
echo [Etapa 1 de 6] %time:~0,8%  Baixando o projeto do GitHub...
>>"%CC_LOG%" echo [%time:~0,8%] Etapa 1 de 6: baixando %ZIP_URL%
if exist "%DESTINO%\IoTCamIcsee.zip" del "%DESTINO%\IoTCamIcsee.zip" >nul 2>nul
curl.exe -L --fail --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 -o "%DESTINO%\IoTCamIcsee.zip" "%ZIP_URL%"
set "RC=%errorlevel%"
REM curl antigo, sem --retry-all-errors, responde codigo 2: tenta sem essa opcao
if "%RC%"=="2" curl.exe -L --fail --retry 5 --retry-delay 3 --connect-timeout 30 -o "%DESTINO%\IoTCamIcsee.zip" "%ZIP_URL%"
if "%RC%"=="2" set "RC=%errorlevel%"
>>"%CC_LOG%" echo     curl terminou com codigo %RC%
set "MSG=Falha no download do projeto - curl codigo %RC%."
if "%RC%"=="6" set "MSG=Sem internet ou sem DNS: nao achei o github.com. Confira a conexao e tente de novo."
if "%RC%"=="23" set "MSG=Sem permissao para gravar o arquivo em %DESTINO%."
if "%RC%"=="22" set "MSG=O GitHub respondeu com erro HTTP, ex.: 404. Confira se o repositorio esta publico."
if not "%RC%"=="0" (
  echo.
  echo [X] %MSG%
  echo     Log: %CC_LOG%
  >>"%CC_LOG%" echo [X] %MSG%
  pause
  exit /b 1
)
for %%A in ("%DESTINO%\IoTCamIcsee.zip") do echo     [OK] Projeto baixado - %%~zA bytes.

REM ---------------- Etapa 2: descompactar ----------------
echo.
echo [Etapa 2 de 6] %time:~0,8%  Descompactando...
>>"%CC_LOG%" echo [%time:~0,8%] Etapa 2 de 6: descompactando
tar -xf "%DESTINO%\IoTCamIcsee.zip" -C "%DESTINO%" >>"%CC_LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo [X] Falha ao descompactar o projeto. O arquivo pode ter vindo incompleto: rode de novo.
  echo     Log: %CC_LOG%
  >>"%CC_LOG%" echo [X] tar falhou
  pause
  exit /b 1
)
if not exist "%DESTINO%\IoTCamIcsee-main\INSTALAR.bat" (
  echo.
  echo [X] Descompactei, mas nao achei %DESTINO%\IoTCamIcsee-main\INSTALAR.bat
  echo     Log: %CC_LOG%
  >>"%CC_LOG%" echo [X] INSTALAR.bat nao encontrado depois do tar
  pause
  exit /b 1
)
echo     [OK] Projeto em %DESTINO%\IoTCamIcsee-main
cd /d "%DESTINO%\IoTCamIcsee-main"

REM config.py deste PC - IPs e senhas: nasce do modelo, so na primeira vez
if not exist "config.py" copy "app\config_exemplo.py" "config.py" >nul

REM Etapas 3 a 6: Python, dependencias, atalhos e abrir a Central
call INSTALAR.bat
