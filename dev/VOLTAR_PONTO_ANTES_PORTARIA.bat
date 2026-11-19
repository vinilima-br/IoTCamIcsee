@echo off
setlocal
cd /d "%~dp0.."
title Ponto de restauracao do projeto
where git >nul 2>nul
if errorlevel 1 (
  echo [X] O Git nao esta no PATH do Windows.
  pause
  exit /b 1
)
echo ============================================================
echo  Ponto de restauracao do codigo
echo ============================================================
echo  1 = Voltar para ANTES da Portaria do Andre  (ponto-antes-portaria)
echo  2 = Ir para a versao COM a Portaria         (portaria-andre)
echo  0 = Cancelar
echo.
echo  config.py, gravacoes, rostos e a pasta data\ NAO sao apagados.
echo  Alteracoes de codigo que nao foram enviadas ao GitHub serao PERDIDAS.
echo ------------------------------------------------------------
git status --short --untracked-files=no
echo ------------------------------------------------------------
set "OPC="
set /p OPC=Escolha (1/2/0): 
if "%OPC%"=="1" set "ALVO=ponto-antes-portaria"
if "%OPC%"=="2" set "ALVO=portaria-andre"
if not defined ALVO (
  echo Cancelado.
  pause
  exit /b 0
)
set "OK="
set /p OK=Digite SIM para confirmar a troca para %ALVO%: 
if /i not "%OK%"=="SIM" (
  echo Cancelado.
  pause
  exit /b 0
)
git reset --hard %ALVO%
if errorlevel 1 (
  echo [X] Nao foi possivel trocar de versao.
  pause
  exit /b 1
)
echo.
echo [OK] Codigo agora esta em: %ALVO%
pause
endlocal
