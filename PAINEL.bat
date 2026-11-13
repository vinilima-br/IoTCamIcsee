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
"%PY%" janela.py
if errorlevel 1 pause
