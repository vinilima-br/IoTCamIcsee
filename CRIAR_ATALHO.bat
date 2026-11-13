@echo off
REM Cria o atalho "Central de Cameras" (com o icone da Central) que abre o PAINEL.bat:
REM   - na Area de Trabalho
REM   - no menu Iniciar (dai da pra fixar na barra de tarefas)
REM Rode de novo se mudar a pasta de lugar.
REM O INSTALAR.bat chama este arquivo sozinho (com /silencioso = sem pausa no fim).
cd /d "%~dp0"
REM atalho antigo que ficava dentro da pasta (apontava para outro PC): some
if exist "Central de Cameras.lnk" del "Central de Cameras.lnk" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ferramentas\criar_atalho.ps1" -Pasta "%~dp0."
if errorlevel 1 (
  echo [X] Nao consegui criar o atalho ^(veja a mensagem acima^).
  if /i not "%~1"=="/silencioso" pause
  exit /b 1
)
if /i "%~1"=="/silencioso" exit /b 0
echo.
echo Pronto! Atalho "Central de Cameras" criado nos lugares acima.
echo Para fixar na barra de tarefas: menu Iniciar ^> Central de Cameras ^>
echo botao direito ^> Fixar na barra de tarefas.
echo.
pause
