@echo off
cd /d "%~dp0"
title Subir projeto para o GitHub

where git >nul 2>nul
if errorlevel 1 (
  echo [X] O Git nao esta no PATH do Windows.
  echo     Abra o Git Bash e me avise - a gente faz por la.
  echo.
  pause
  exit /b 1
)

echo ===================================================
echo   Enviando o projeto para o GitHub (so o essencial)
echo ===================================================
echo.
echo [1/4] Tirando do envio os arquivos pesados (modelos, fotos, sons)...
git rm -r --cached --ignore-unmatch modelos/sherpa-onnx-whisper-small modelos/vosk-model-small-pt-0.3 rostos/eventos rostos/pessoas rostos/removidos rostos/testes rostos/historico.csv rostos/pessoas.json sons diag_bloqueio >nul

echo [2/4] Atualizando a lista de ignorados...
git add .gitignore

echo [3/4] Refazendo o commit sem o peso...
git commit --amend -m "primeira versao"

echo.
echo [4/4] Enviando para o GitHub (pode levar alguns segundos)...
git push -u origin main

echo.
echo ===================================================
echo  Se apareceu "main -^> main" acima, DEU CERTO.
echo  Se apareceu erro em vermelho, tire um print e me mande.
echo ===================================================
echo.
pause
