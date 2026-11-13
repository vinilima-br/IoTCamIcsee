@echo off
cd /d "%~dp0"
title Atualizar o GitHub

where git >nul 2>nul
if errorlevel 1 (
  echo [X] O Git nao esta no PATH do Windows.
  pause
  exit /b 1
)

echo ===================================================
echo   Salvando as mudancas no GitHub
echo ===================================================
echo.
echo Arquivos mudados:
git status --short
echo.
set "MSG="
set /p MSG="O que mudou? (Enter = 'atualizacao do projeto'): "
if "%MSG%"=="" set "MSG=atualizacao do projeto"
echo.
git add -A
git commit -m "%MSG%"
echo.
git push
echo.
echo ===================================================
echo  Se apareceu "main -^> main", DEU CERTO.
echo  Se apareceu erro em vermelho, tire um print e me mande.
echo ===================================================
echo.
pause
