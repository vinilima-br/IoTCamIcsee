@echo off
REM Sobe a Central de Cameras. Para desligar: Ctrl+C nesta janela.
REM A sessao das cameras (INICIAR_SESSAO.bat) abre sozinha em outra janela
REM se ainda nao estiver rodando - e continua aberta quando o servidor fecha.
cd /d "%~dp0.."
call "%~dp0_python.bat" || (pause & exit /b 1)
"%PY%" app\sessao_xm.py --checar
if errorlevel 1 (
  echo Abrindo a sessao das cameras em outra janela...
  start "Sessao das cameras" "%~dp0INICIAR_SESSAO.bat"
  timeout /t 4 /nobreak >nul
)
title Central de Cameras
:subir
"%PY%" app\servidor.py
REM codigo 3 = a Central pediu para subir de novo (camera adicionada/removida)
if "%errorlevel%"=="3" goto subir
REM codigo 0 = desligou normal (ex.: fechou a janela do painel): fecha esta janela tambem
if "%errorlevel%"=="0" exit
echo.
echo O servidor parou. Pressione uma tecla para fechar.
pause >nul
