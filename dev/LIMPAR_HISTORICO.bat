@echo off
setlocal
REM ==================================================================
REM  So para o PC de desenvolvimento (o que tem a pasta .git).
REM  Republica o projeto no GitHub SO com o estado de agora, apagando
REM  o historico antigo (senhas de teste, sons e atalhos de versoes velhas).
REM
REM  - Os arquivos desta pasta NAO sao mexidos.
REM  - O historico antigo fica guardado SO neste PC, no ramo
REM    "antes-da-limpeza" - nao vai para o GitHub.
REM  - Os PCs instalados continuam se atualizando normalmente.
REM  Rode UMA vez. Depois, use o ENVIAR_PARA_GITHUB.bat como sempre.
REM ==================================================================
cd /d "%~dp0.."
title Limpar o historico do GitHub

where git >nul 2>nul
if errorlevel 1 goto sem_git
if not exist ".git" goto sem_repo

set "RAMO="
for /f "delims=" %%R in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "RAMO=%%R"
if /i not "%RAMO%"=="main" goto ramo_errado

echo ===================================================
echo   LIMPAR O HISTORICO DO GITHUB
echo ===================================================
echo.
echo  O que vai acontecer:
echo   1. O GitHub passa a ter SO a versao de agora do projeto.
echo   2. Todo o historico antigo some de la.
echo   3. Uma copia do historico fica so neste PC.
echo.
echo  Antes de continuar, troque as senhas das cameras que
echo  apareciam no historico - a limpeza nao apaga copias que
echo  alguem ja tenha baixado.
echo.
set "RESP="
set /p RESP="Digite LIMPAR e aperte Enter para continuar: "
if /i not "%RESP%"=="LIMPAR" goto cancelado

echo.
echo [1 de 5] Guardando o historico antigo neste PC...
REM so cria a copia se ainda nao existe: rodar de novo nao apaga a copia boa
git rev-parse -q --verify refs/heads/antes-da-limpeza >nul 2>nul
if errorlevel 1 git branch antes-da-limpeza HEAD
git rev-parse -q --verify refs/heads/antes-da-limpeza >nul 2>nul
if errorlevel 1 goto falhou

echo [2 de 5] Montando a versao limpa...
git checkout -q --orphan versao-limpa
if errorlevel 1 goto falhou
git rm -r -q --cached --ignore-unmatch "*.lnk" >nul 2>nul
git add --renormalize . >nul 2>nul
git add -A
if errorlevel 1 goto desfaz
git commit -q -m "versao limpa do projeto"
if errorlevel 1 goto desfaz

echo [3 de 5] Trocando o ramo principal...
git branch -M versao-limpa main
if errorlevel 1 goto falhou

echo [4 de 5] Enviando para o GitHub - substitui o que esta la...
git push --force -u origin main
if errorlevel 1 goto push_falhou

echo [5 de 5] Conferindo...
set "N="
for /f "delims=" %%N in ('git rev-list --count origin/main 2^>nul') do set "N=%%N"
echo.
echo ===================================================
if "%N%"=="1" echo  [OK] Pronto: o GitHub agora tem 1 unico envio, o de agora.
if not "%N%"=="1" echo  [!] O GitHub ficou com %N% envios - tire um print e me mande.
echo.
echo  O historico antigo ficou so neste PC, no ramo antes-da-limpeza.
echo  O GitHub ainda pode guardar os envios antigos por um tempo para
echo  quem souber o endereco exato deles - por isso a troca das senhas.
echo ===================================================
echo.
pause
exit /b 0

:desfaz
echo.
echo [X] Nao consegui montar a versao limpa. Voltando ao que era...
git checkout -q -f main
git branch -D versao-limpa >nul 2>nul
goto fim_erro

:push_falhou
echo.
echo [X] O envio falhou - internet ou login do GitHub.
echo     Nada mudou no GitHub. Neste PC o ramo principal ja e a versao limpa:
echo     rode este arquivo de novo quando a internet voltar.
goto fim_erro

:falhou
echo.
echo [X] O Git recusou o comando acima. Nada foi enviado ao GitHub.
goto fim_erro

:sem_git
echo [X] O Git nao esta no PATH do Windows.
goto fim_erro

:sem_repo
echo [X] Esta pasta nao tem .git - rode no PC de desenvolvimento.
goto fim_erro

:ramo_errado
echo [X] O ramo atual e "%RAMO%", nao "main". Nao mexi em nada.
goto fim_erro

:cancelado
echo.
echo Cancelado. Nada foi mexido.
echo.
pause
exit /b 0

:fim_erro
echo.
echo Tire um print desta janela e me mande, se precisar.
pause
exit /b 1
