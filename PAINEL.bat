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
set "COD=%errorlevel%"
REM codigo 3 = a Central pediu para subir de novo (camera adicionada/removida)
if "%COD%"=="3" goto abrir
REM codigo 0 = fechou normal (X da janela ou atualizacao): fecha esta janela tambem
if "%COD%"=="0" exit
echo.
echo A Central fechou com erro (codigo %COD%). Veja as mensagens acima.
pause
exit
