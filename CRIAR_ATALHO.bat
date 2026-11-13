@echo off
REM Cria o atalho "Central de Cameras" (com o icone da Central) que abre o PAINEL.bat:
REM   - na Area de Trabalho
REM   - no menu Iniciar (dai da pra fixar na barra de tarefas)
REM   - aqui na pasta do projeto
REM Rode de novo se mudar a pasta de lugar.
REM O INSTALAR.bat chama este arquivo sozinho (com /silencioso = sem pausa no fim).
cd /d "%~dp0"
if not exist "icone.ico" (
  echo [X] Nao achei o icone.ico nesta pasta.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$pasta = (Get-Location).Path;" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$destinos = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'), $pasta);" ^
  "foreach ($d in $destinos) {" ^
  "  $a = $ws.CreateShortcut((Join-Path $d 'Central de Cameras.lnk'));" ^
  "  $a.TargetPath = (Join-Path $pasta 'PAINEL.bat');" ^
  "  $a.WorkingDirectory = $pasta;" ^
  "  $a.IconLocation = (Join-Path $pasta 'icone.ico') + ',0';" ^
  "  $a.Description = 'Central de Cameras';" ^
  "  $a.WindowStyle = 7;" ^
  "  $a.Save();" ^
  "  Write-Host ('  [OK] ' + $d)" ^
  "}"
if errorlevel 1 (
  echo [X] Nao consegui criar o atalho.
  pause
  exit /b 1
)
if /i "%~1"=="/silencioso" exit /b 0
echo.
echo Pronto! Atalho "Central de Cameras" criado nos lugares acima.
echo Para fixar na barra de tarefas: menu Iniciar ^> Central de Cameras ^>
echo botao direito ^> Fixar na barra de tarefas.
echo.
pause
