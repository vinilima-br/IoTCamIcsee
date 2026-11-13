@echo off
REM Sobe a Central de Cameras. Para desligar: Ctrl+C nesta janela.
REM A sessao das cameras (INICIAR_SESSAO.bat) abre sozinha em outra janela
REM se ainda nao estiver rodando - e continua aberta quando o servidor fecha.
cd /d "%~dp0"
call "%~dp0_python.bat" || (pause & exit /b 1)
"%PY%" sessao_xm.py --checar
if errorlevel 1 (
  echo Abrindo a sessao das cameras em outra janela...
  start "Sessao das cameras" "%~dp0INICIAR_SESSAO.bat"
  timeout /t 4 /nobreak >nul
)
title Central de Cameras
"%PY%" servidor.py
echo.
echo O servidor parou. Pressione uma tecla para fechar.
pause >nul
