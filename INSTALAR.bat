@echo off
setlocal
cd /d "%~dp0"
title Instalador - Central de Cameras

echo ===================================================
echo    INSTALADOR - Central de Cameras
echo ===================================================
echo.

REM ---------- 1) Python (instala sozinho se faltar) ----------
call "%~dp0app\_python.bat" >nul 2>nul
if not errorlevel 1 goto tem_python

echo [*] Python nao encontrado. Vou instalar agora...
where winget >nul 2>nul
if errorlevel 1 goto baixa_python
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
goto confere_python

:baixa_python
echo     Baixando o instalador oficial do Python...
curl.exe -L -o python-setup.exe https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe
if errorlevel 1 (
  echo [X] Falha ao baixar o Python. Confira a internet.
  pause
  exit /b 1
)
echo     Instalando o Python em modo silencioso, aguarde cerca de 1 minuto...
python-setup.exe /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1
del python-setup.exe >nul 2>nul

:confere_python
REM acha o Python recem-instalado pela pasta (nao precisa reabrir a janela)
call "%~dp0app\_python.bat" >nul 2>nul
if not errorlevel 1 goto tem_python
echo.
echo ===================================================
echo  Python instalado, mas nao consegui acha-lo ainda.
echo  FECHE esta janela e rode o INSTALAR.bat DE NOVO.
echo ===================================================
echo.
pause
exit /b 0

:tem_python
echo [OK] Python encontrado: %PY%
echo.

REM config.py deste PC (IPs e senhas): nasce do modelo, so na primeira vez
if not exist "config.py" copy "app\config_exemplo.py" "config.py" >nul

REM ---------- 2) Dependencias ----------
echo [1/3] Instalando dependencias (pode demorar na primeira vez)...
"%PY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo [X] Falha ao instalar as dependencias. Veja a mensagem acima.
  pause
  exit /b 1
)
echo [OK] Dependencias prontas.
echo.

REM ---------- Atalho com icone (Area de Trabalho + menu Iniciar) ----------
echo [*] Criando o atalho "Central de Cameras" na Area de Trabalho...
call "%~dp0app\CRIAR_ATALHO.bat" /silencioso
if errorlevel 1 echo [!] Nao criei o atalho. Da para criar depois com o app\CRIAR_ATALHO.bat.
echo.

if not exist "modelos\yolov8n.onnx" (
  echo [!] Aviso: modelos\yolov8n.onnx nao encontrado.
  echo     O servidor sobe, mas a IA de deteccao so funciona com esse arquivo.
  echo.
)

REM ---------- Versao instalada (a atualizacao automatica nao refaz o que acabou de baixar) ----------
if exist "%~dp0..\IoTCamIcsee.zip" (
  "%PY%" -c "import zipfile,sys,re; c=zipfile.ZipFile(sys.argv[1]).comment.decode('ascii','ignore').strip(); m=re.fullmatch('[0-9a-f]{40}', c); open('versao.txt','w').write(m.group(0)+'\n') if m else None" "%~dp0..\IoTCamIcsee.zip" 2>nul
)

REM ---------- 3) Cameras ----------
REM As cameras agora sao adicionadas pela JANELA do painel (botao "+ Cameras"):
REM ela busca as cameras na rede e abre sozinha quando o PC ainda nao tem nenhuma.
echo [2/3] Cameras: voce adiciona pela janela do painel (botao "+ Cameras").
echo       Ela abre sozinha e ja procura as cameras da rede.
echo.

:subir
echo [3/3] Abrindo a Central (sessao das cameras + painel em janela propria)...
start "" "%~dp0PAINEL.bat"
echo.
echo ===================================================
echo  Pronto! Das proximas vezes, abra pelo atalho
echo  "Central de Cameras" na Area de Trabalho.
echo  No navegador deste PC:   http://localhost:5050
echo  No celular, mesma rede:  http://IP-DESTE-PC:5050
echo ===================================================
echo.
echo Esta janela fecha sozinha em 8 segundos...
timeout /t 8 >nul
exit
