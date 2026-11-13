@echo off
REM Abre a Central de Cameras numa JANELA PROPRIA (sem navegador).
REM Fechar a janela = desligar o servidor (logout limpo nas cameras).
cd /d "%~dp0"
title Central de Cameras - janela
call "%~dp0_python.bat" || (pause & exit /b 1)
"%PY%" -c "import webview" 2>nul
if errorlevel 1 (
  echo Instalando a janela propria ^(pywebview^), so na primeira vez...
  "%PY%" -m pip install pywebview --disable-pip-version-check
)
"%PY%" sessao_xm.py --checar
if errorlevel 1 (
  echo Abrindo a sessao das cameras em outra janela...
  start "Sessao das cameras" /min "%~dp0INICIAR_SESSAO.bat"
  timeout /t 4 /nobreak >nul
)
:abrir
"%PY%" janela.py
REM codigo 3 = a Central pediu para subir de novo (camera adicionada/removida)
if "%errorlevel%"=="3" goto abrir
if errorlevel 1 pause
