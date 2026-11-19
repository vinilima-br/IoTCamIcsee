@echo off
REM Mede quanto custa a analise do rosto NESTE PC (salva em logs\diag_facial_*.txt).
cd /d "%~dp0.."
title Diagnostico do reconhecimento facial
call "%CD%\app\_python.bat" || (pause & exit /b 1)
echo Medindo... (leva menos de 1 minuto)
echo.
"%PY%" ferramentas\diag_facial.py
echo.
pause
