@echo off
cd /d "%~dp0"
title Atualizar o GitHub

echo ===================================================
echo   Salvando as mudancas no GitHub
echo ===================================================
echo.
git add -A
git commit -m "atualiza config exemplo e scripts de instalacao"
echo.
git push
echo.
echo ===================================================
echo  Se apareceu "main -^> main", DEU CERTO.
echo ===================================================
echo.
pause
