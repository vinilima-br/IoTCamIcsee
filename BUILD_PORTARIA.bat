@echo off
setlocal
cd /d "%~dp0"
title Preparar pacote offline da Portaria

set "PY=%~dp0python\python.exe"
if not exist "%PY%" set "PY=%~dp0python\tools\python.exe"
if not exist "%PY%" (
  echo [X] Python portatil nao encontrado.
  exit /b 1
)

if not exist portaria_ui\node_modules (
  echo Instalando dependencias locais do frontend...
  pushd portaria_ui
  call npm install
  if errorlevel 1 (popd & exit /b 1)
  popd
)
pushd portaria_ui
call npm run build
if errorlevel 1 (popd & exit /b 1)
popd

echo Instalando dependencias para compilacao...
"%PY%" -m pip install -r requirements.txt -r portaria_api\requirements.txt pyinstaller
if errorlevel 1 exit /b 1

echo Gerando Portaria.exe...
"%PY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name Portaria ^
  --add-data "portaria_ui\dist;portaria_ui\dist" ^
  --collect-all uvicorn --collect-all sqlalchemy --collect-all webview ^
  --collect-all cv2 --collect-all numpy ^
  --hidden-import imageio_ffmpeg --hidden-import Crypto.Cipher ^
  desktop_app.py
if errorlevel 1 exit /b 1

echo Incluindo os modulos e modelos locais das cameras...
xcopy app dist\Portaria\app /E /I /Y >nul
if errorlevel 1 exit /b 1
xcopy modelos dist\Portaria\modelos /E /I /Y >nul
if errorlevel 1 exit /b 1
xcopy sons dist\Portaria\sons /E /I /Y >nul
if errorlevel 1 exit /b 1
copy /Y PORTARIA.bat dist\Portaria\PORTARIA.bat >nul

echo.
echo Pacote criado em dist\Portaria\Portaria.exe
echo Copie config.py para dist\Portaria\config.py e configure as cameras.
echo Para operar sem rede, mantenha toda a pasta dist\Portaria no PC da guarita.
endlocal
