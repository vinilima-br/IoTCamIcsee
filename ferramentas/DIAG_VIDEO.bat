@echo off
REM Mede a CPU gasta para decodificar o video Alta (CPU x placa de video).
REM FECHE O PAINEL ANTES. Resultado em logs\diag_video_*.txt
cd /d "%~dp0.."
title Diagnostico do video
call "%CD%\app\_python.bat" || (pause & exit /b 1)
echo Feche o painel antes de continuar (os dois disputam a CPU).
pause
echo Medindo... (uns 30 segundos)
"%PY%" ferramentas\diag_video.py %1
echo.
pause
