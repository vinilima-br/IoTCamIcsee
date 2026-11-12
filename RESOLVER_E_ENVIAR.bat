@echo off
cd /d "%~dp0"
title Resolver e enviar para o GitHub

echo ===================================================
echo   Juntando o que ja esta no GitHub com o nosso
echo   e enviando tudo. (Nao apaga nada.)
echo ===================================================
echo.
echo [1/2] Trazendo o README que o GitHub criou...
git pull origin main --allow-unrelated-histories --no-edit

echo.
echo [2/2] Enviando o projeto para o GitHub...
git push -u origin main

echo.
echo ===================================================
echo  Se apareceu "main -^> main" acima, DEU CERTO.
echo  Senao, tire um print e me mande.
echo ===================================================
echo.
pause
