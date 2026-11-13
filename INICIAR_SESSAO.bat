@echo off
REM Sessao PERMANENTE com as cameras iCSee (porta 34567).
REM Deixe esta janela aberta. O servidor pode ser reiniciado a vontade.
REM Para fechar: Ctrl+C nesta janela (logout limpo nas cameras).
cd /d "%~dp0"
title Sessao das cameras (34567) - deixe aberta
call "%~dp0_python.bat" || (pause & exit /b 1)
"%PY%" sessao_xm.py
REM codigo 5 = saiu para a atualizacao automatica (a Central abre a sessao nova)
if "%errorlevel%"=="5" exit
echo.
echo A sessao parou. Pressione uma tecla para fechar.
pause >nul
