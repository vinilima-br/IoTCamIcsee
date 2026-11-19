@echo off
setlocal
cd /d "%~dp0.."
title Preparar pacote offline da Portaria

call "%CD%\app\_python.bat" || exit /b 1

if not exist gestao\ui\node_modules (
  echo Instalando dependencias locais do frontend...
  pushd gestao\ui
  call npm install
  if errorlevel 1 (popd & exit /b 1)
  popd
)
pushd gestao\ui
call npm run build
if errorlevel 1 (popd & exit /b 1)
popd

echo Instalando dependencias para compilacao...
"%PY%" -m pip install -r requirements.txt -r gestao\api\requirements.txt pyinstaller
if errorlevel 1 exit /b 1

echo Gerando Portaria.exe...
"%PY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name Portaria ^
  --add-data "gestao\ui\dist;gestao\ui\dist" ^
  --collect-all uvicorn --collect-all sqlalchemy --collect-all webview ^
  --collect-all cv2 --collect-all numpy ^
  --hidden-import imageio_ffmpeg --hidden-import Crypto.Cipher ^
  gestao\desktop_app.py
if errorlevel 1 exit /b 1

echo Incluindo os modulos e modelos locais das cameras...
xcopy app dist\Portaria\app /E /I /Y >nul
if errorlevel 1 exit /b 1
xcopy modelos dist\Portaria\modelos /E /I /Y >nul
if errorlevel 1 exit /b 1
xcopy sons dist\Portaria\sons /E /I /Y >nul
if errorlevel 1 exit /b 1
copy /Y gestao\PORTARIA.bat dist\Portaria\PORTARIA.bat >nul

echo.
echo Pacote criado em dist\Portaria\Portaria.exe
echo Copie config.py para dist\Portaria\config.py e configure as cameras.
echo Para operar sem rede, mantenha toda a pasta dist\Portaria no PC da guarita.
endlocal
