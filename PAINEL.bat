@echo off
REM Abre a Central de Cameras numa JANELA PROPRIA (sem navegador).
REM Fechar a janela = desligar o servidor (logout limpo nas cameras).
cd /d "%~dp0"
python -c "import webview" 2>nul
if errorlevel 1 (
  echo Instalando a janela propria ^(pywebview^), so na primeira vez...
  python -m pip install pywebview
)
python sessao_xm.py --checar
if errorlevel 1 (
  echo Abrindo a sessao das cameras em outra janela...
  start "Sessao das cameras" "%~dp0INICIAR_SESSAO.bat"
  timeout /t 4 /nobreak >nul
)
title Central de Cameras - janela
python janela.py
if errorlevel 1 pause
