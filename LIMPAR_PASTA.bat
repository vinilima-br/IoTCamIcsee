@echo off
cd /d "%~dp0"
title Organizar pasta - mover descartaveis para _lixo

set "DEST=_lixo"
if not exist "%DEST%" mkdir "%DEST%"
if not exist "%DEST%\ferramentas" mkdir "%DEST%\ferramentas"

echo ===================================================
echo   Movendo arquivos descartaveis para a pasta _lixo
echo   NADA e apagado. Voce confere e apaga depois.
echo ===================================================
echo.

echo [*] Pastas de teste / descartaveis...
for %%D in (historico cache __pycache__ logs sd_baixados vozes_teste vozes_teste2 vozes_teste3 diag_bloqueio) do if exist "%%D" move "%%D" "%DEST%\" >nul 2>nul
if exist "rostos\testes"    move "rostos\testes"    "%DEST%\" >nul 2>nul
if exist "rostos\removidos" move "rostos\removidos" "%DEST%\" >nul 2>nul
if exist "sons\.cache"      move "sons\.cache"      "%DEST%\" >nul 2>nul

echo [*] Arquivos soltos de teste / backup...
for %%F in (dump_elsys.txt ft1.png) do if exist "%%F" move "%%F" "%DEST%\" >nul 2>nul
move config.py.bak_* "%DEST%\" >nul 2>nul

echo [*] Capturas e scripts de pesquisa em ferramentas...
move ferramentas\*.bin            "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\*.b64            "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\*.pcap           "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\elsys_*.json     "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\elsys_*.txt      "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\*_material.json  "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\teste_*.py       "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\forja_*.py       "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\cracka_*.py      "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\confirma_*.py    "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\diag_elsys_audio.py     "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\diag_pubkey_elsys.py    "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\diag_handshake_elsys.py "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\dump_configs_elsys.py   "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\get_conta_elsys.py      "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\recupera_conta_elsys.py "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\elsys_conta_rapido.py   "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\elsys_users.py          "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\fala_elsys.py           "%DEST%\ferramentas\" >nul 2>nul
move ferramentas\inverter_imagem.py      "%DEST%\ferramentas\" >nul 2>nul

echo.
echo ===================================================
echo  Pronto. Tudo foi para a pasta  _lixo
echo  1) Abra o sistema e veja se funciona normal.
echo  2) Se estiver tudo certo, apague a pasta _lixo
echo     - clique nela, Shift+Delete, ou mande para a Lixeira.
echo ===================================================
echo.
pause
