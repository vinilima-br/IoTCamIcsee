@echo off
REM ------------------------------------------------------------------
REM  Acha o Python deste PC e guarda em %PY% (e %PYW% = sem janela).
REM  Os outros .bat fazem:  call "%~dp0_python.bat" || exit /b 1
REM  Nao depende do PATH: tenta python, py -3 e as pastas de instalacao.
REM ------------------------------------------------------------------
set "PY="
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
if defined PY if exist "%PY%" goto _py_ok
set "PY="
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%P"
if defined PY if exist "%PY%" goto _py_ok
set "PY="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if defined PY goto _py_ok
for /d %%D in ("%ProgramFiles%\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if defined PY goto _py_ok
for /d %%D in ("C:\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if defined PY goto _py_ok
echo [X] Python nao encontrado neste PC. Rode o INSTALAR.bat.
exit /b 1

:_py_ok
for %%F in ("%PY%") do set "PYW=%%~dpFpythonw.exe"
if not exist "%PYW%" set "PYW=%PY%"
exit /b 0
