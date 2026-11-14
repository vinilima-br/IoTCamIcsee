# -*- coding: utf-8 -*-
"""
atualizador.py  -  A Central se atualiza sozinha pelo GitHub.

- De tempos em tempos pergunta ao GitHub qual é o último commit do ramo main.
- Tem novidade (e nada gravando)? Baixa o .zip daquele commit, confere se
  todo .py compila, guarda backup do que vai trocar e copia por cima.
  Os .bat são trocados pelo ajudante (ferramentas/terminar_atualizacao.py)
  DEPOIS que a Central fecha (o Windows lê o .bat enquanto roda), e ele
  mesmo abre a Central de novo.
- NUNCA mexe no que não está no GitHub: config.py, gravações, fotos,
  rostos, ajustes (*.json) - nada disso vai pro repositório.
- PC com a pasta .git (o PC de onde você manda as mudanças): não se
  atualiza sozinho (use o git). Lá só mostra a versão.
- Arquivo que SAIU do projeto: liste em ferramentas/obsoletos.txt. Ao subir,
  cada PC instalado move esses arquivos para _atualizacao/obsoletos/.

Ligar/desligar: no painel, ⚙ Config -> "Atualizar sozinho" (padrão: LIGADO).
A escolha fica em atualizacao.json (de cada PC; não vai pro GitHub).

config.py (opcional):
    ATUALIZACAO_REPO = "vinilima-br/IoTCamIcsee"
    ATUALIZACAO_RAMO = "main"
"""
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

import config

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_VERSAO = os.path.join(PASTA, "versao.txt")
ARQ_ESCOLHA = os.path.join(PASTA, "atualizacao.json")
PASTA_TRAB = os.path.join(PASTA, "_atualizacao")
REPO = getattr(config, "ATUALIZACAO_REPO", "vinilima-br/IoTCamIcsee")
RAMO = getattr(config, "ATUALIZACAO_RAMO", "main")
INTERVALO_S = 30 * 60
PRIMEIRA_S = 45

# trocados só pelo ajudante, com a Central fechada
DEPOIS = (".bat", ".cmd", ".ps1")
# se mudar um destes, a sessão das câmeras (sessao_xm.py) também reinicia
DA_SESSAO = {"sessao_xm.py", "camera_xm.py", "elsys_xm.py", "cliente_xm.py", "config_exemplo.py"}
NUNCA = {"config.py", "versao.txt", "atualizacao.json"}

URL_API = getattr(config, "ATUALIZACAO_URL_API", "https://api.github.com/repos/{repo}/commits/{ramo}")
URL_ZIP = getattr(config, "ATUALIZACAO_URL_ZIP", "https://github.com/{repo}/archive/{sha}.zip")

_trava = threading.Lock()


def le_automatica():
    """Atualizar sozinho? Padrão: SIM (sem arquivo = ligado)."""
    try:
        with open(ARQ_ESCOLHA, "r", encoding="utf-8") as f:
            return bool(json.load(f).get("automatica", True))
    except (OSError, ValueError, AttributeError):
        return True


def grava_automatica(ligada):
    temp = ARQ_ESCOLHA + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump({"automatica": bool(ligada)}, f)
    os.replace(temp, ARQ_ESCOLHA)
    estado["automatica"] = bool(ligada)
    _log("atualizar sozinho: {}".format("LIGADO" if ligada else "desligado"))
    return estado["automatica"]


estado = {"local": None, "remoto": None, "mensagem": "", "data": "", "disponivel": False,
          "dev": os.path.isdir(os.path.join(PASTA, ".git")), "automatica": le_automatica(),
          "verificado_em": None, "erro": None, "aplicando": False, "ultima": None}


def _log(msg):
    linha = "[atualizacao] " + msg
    print(linha)
    try:
        os.makedirs(os.path.join(PASTA, "logs"), exist_ok=True)
        with open(os.path.join(PASTA, "logs", "atualizacao.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def versao_local():
    try:
        with open(ARQ_VERSAO, "r", encoding="utf-8") as f:
            v = f.read().strip()
            return v or None
    except OSError:
        return None


def _baixa(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "CentralDeCameras",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def verificar():
    """Pergunta ao GitHub o último commit. Atualiza e devolve o estado."""
    with _trava:
        estado["local"] = versao_local()
        try:
            d = json.loads(_baixa(URL_API.format(repo=REPO, ramo=RAMO)).decode("utf-8"))
            estado["remoto"] = d["sha"]
            commit = d.get("commit") or {}
            estado["mensagem"] = (commit.get("message") or "").strip().splitlines()[0][:120] if commit.get("message") else ""
            estado["data"] = ((commit.get("committer") or {}).get("date") or "")[:16].replace("T", " ")
            estado["erro"] = None
        except Exception as e:  # noqa: BLE001
            estado["erro"] = "não consegui falar com o GitHub: {}".format(e)
        estado["verificado_em"] = time.strftime("%H:%M")
        # instalação nova (sem versao.txt): acabou de baixar a versão do GitHub -> só registra,
        # não "atualiza" no meio da primeira configuração
        if estado["remoto"] and not estado["local"] and not estado["dev"]:
            try:
                with open(ARQ_VERSAO, "w", encoding="utf-8") as f:
                    f.write(estado["remoto"] + "\n")
                estado["local"] = estado["remoto"]
                _log("primeira verificação: versão {} registrada como a instalada".format(estado["remoto"][:7]))
            except OSError:
                pass
        estado["disponivel"] = bool(estado["remoto"]) and estado["remoto"] != estado["local"] and not estado["dev"]
        return dict(estado)


def _conferir_e_copiar(sha):
    """Baixa o zip do commit, confere e copia (menos os .bat). Devolve o plano do ajudante."""
    os.makedirs(PASTA_TRAB, exist_ok=True)
    dados = _baixa(URL_ZIP.format(repo=REPO, sha=sha), timeout=120)
    staging = tempfile.mkdtemp(prefix="novo_", dir=PASTA_TRAB)
    caminho_zip = os.path.join(staging, "versao.zip")
    with open(caminho_zip, "wb") as f:
        f.write(dados)
    raiz_nova = os.path.join(staging, "arquivos")
    with zipfile.ZipFile(caminho_zip) as z:
        nomes = [n for n in z.namelist() if not n.endswith("/")]
        if not nomes:
            raise RuntimeError("o zip veio vazio")
        prefixo = nomes[0].split("/", 1)[0] + "/"
        for n in nomes:
            rel = n[len(prefixo):] if n.startswith(prefixo) else n
            if not rel or ".." in rel.split("/") or rel.startswith("/"):
                continue
            destino = os.path.join(raiz_nova, *rel.split("/"))
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with z.open(n) as src, open(destino, "wb") as dst:
                shutil.copyfileobj(src, dst)

    arquivos = []
    for base, _dirs, fs in os.walk(raiz_nova):
        for f in fs:
            arquivos.append(os.path.relpath(os.path.join(base, f), raiz_nova))
    if "servidor.py" not in arquivos:
        raise RuntimeError("o zip não parece ser da Central (sem servidor.py)")

    # 1) todo .py novo tem que compilar - senão não troca nada
    for rel in arquivos:
        if rel.endswith(".py"):
            try:
                py_compile.compile(os.path.join(raiz_nova, rel), cfile=os.path.join(staging, "chk.pyc"),
                                   doraise=True)
            except py_compile.PyCompileError as e:
                linha = getattr(e.exc_value, "lineno", None)
                raise RuntimeError("a versão nova tem erro em {}{} - nada foi trocado".format(
                    rel.replace("\\", "/"), " (linha {})".format(linha) if linha else ""))

    # 2) o que mudou de verdade
    mudou = []
    for rel in arquivos:
        if os.path.basename(rel) in NUNCA and os.path.dirname(rel) == "":
            continue
        novo, atual = os.path.join(raiz_nova, rel), os.path.join(PASTA, rel)
        try:
            with open(novo, "rb") as a, open(atual, "rb") as b:
                if a.read().replace(b"\r\n", b"\n") == b.read().replace(b"\r\n", b"\n"):
                    continue
        except OSError:
            pass
        mudou.append(rel)

    # 3) backup + cópia (os .bat ficam pro ajudante)
    backup = os.path.join(PASTA_TRAB, "backup_" + time.strftime("%Y%m%d_%H%M%S"))
    depois = []
    for rel in mudou:
        atual = os.path.join(PASTA, rel)
        if os.path.exists(atual):
            os.makedirs(os.path.dirname(os.path.join(backup, rel)), exist_ok=True)
            shutil.copy2(atual, os.path.join(backup, rel))
        if rel.lower().endswith(DEPOIS):
            depois.append(rel)
            continue
        os.makedirs(os.path.dirname(atual) or PASTA, exist_ok=True)
        shutil.copy2(os.path.join(raiz_nova, rel), atual)
    with open(ARQ_VERSAO, "w", encoding="utf-8") as f:
        f.write(sha + "\n")
    _limpa_backups()
    nomes_mudados = {os.path.basename(r) for r in mudou}
    return {"staging": raiz_nova, "pasta_trab": staging, "depois": depois, "mudou": mudou,
            "pip": "requirements.txt" in mudou,
            "sessao": bool(nomes_mudados & DA_SESSAO), "backup": backup}


def _limpa_backups(manter=3):
    try:
        bks = sorted(d for d in os.listdir(PASTA_TRAB) if d.startswith("backup_"))
        for d in bks[:-manter]:
            shutil.rmtree(os.path.join(PASTA_TRAB, d), ignore_errors=True)
    except OSError:
        pass


def aplicar(lancador, ao_fechar):
    """Baixa, confere, copia e chama o ajudante. ao_fechar(): fecha a Central (código 0).
    Devolve (ok, mensagem)."""
    if estado["dev"]:
        return False, "este PC tem a pasta .git (é o PC de desenvolvimento): atualize com o git"
    if estado["aplicando"]:
        return False, "já está atualizando"
    if not estado["remoto"]:
        verificar()
    sha = estado["remoto"]
    if not sha:
        return False, estado["erro"] or "não sei qual é a versão nova"
    estado["aplicando"] = True
    try:
        plano = _conferir_e_copiar(sha)
    except Exception as e:  # noqa: BLE001
        for d in os.listdir(PASTA_TRAB) if os.path.isdir(PASTA_TRAB) else []:
            if d.startswith("novo_"):
                shutil.rmtree(os.path.join(PASTA_TRAB, d), ignore_errors=True)
        estado["aplicando"] = False
        estado["erro"] = "atualização cancelada: {}".format(e)
        _log(estado["erro"])
        return False, estado["erro"]
    _log("versão {} aplicada ({} arquivo(s) novo(s)/mudado(s){}{})".format(
        sha[:7], len(plano["mudou"]), ", pip" if plano["pip"] else "",
        ", reinicia a sessão" if plano["sessao"] else ""))
    estado["ultima"] = sha
    plano.update({"esperar_pid": os.getpid(), "pai_pid": os.getppid(), "lancador": lancador,
                  "pasta": PASTA, "python": sys.executable})
    arq_plano = os.path.join(plano["pasta_trab"], "plano.json")
    with open(arq_plano, "w", encoding="utf-8") as f:
        json.dump(plano, f, indent=2)
    ajudante = os.path.join(PASTA, "ferramentas", "terminar_atualizacao.py")
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, ajudante, arq_plano], cwd=PASTA, close_fds=True,
                     creationflags=flags, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ao_fechar()
    return True, "atualizando para {}".format(sha[:7])


ARQ_OBSOLETOS = os.path.join(PASTA, "ferramentas", "obsoletos.txt")
# o que nunca sai da pasta, mesmo que alguém ponha na lista por engano
_PROTEGIDOS = {"config.py", "versao.txt", "atualizacao.json", "servidor.py", "atualizador.py",
               "PAINEL.bat", "INICIAR.bat", "INICIAR_SESSAO.bat", "_python.bat"}


def limpa_obsoletos():
    """Arquivos que saíram do projeto (ferramentas/obsoletos.txt) e ainda estão
    neste PC: MOVE para _atualizacao/obsoletos/ (não apaga). Só PC instalado."""
    if estado["dev"]:
        return []
    try:
        with open(ARQ_OBSOLETOS, "r", encoding="utf-8") as f:
            linhas = f.read().splitlines()
    except OSError:
        return []
    movidos = []
    destino_base = os.path.join(PASTA_TRAB, "obsoletos")
    for linha in linhas:
        rel = linha.strip().replace("\\", "/")
        if not rel or rel.startswith("#") or rel.startswith("/") or ":" in rel:
            continue
        partes = rel.split("/")
        if ".." in partes or os.path.basename(rel) in _PROTEGIDOS:
            continue
        origem = os.path.join(PASTA, *partes)
        if not os.path.isfile(origem):
            continue
        try:
            destino = os.path.join(destino_base, *partes)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            if os.path.exists(destino):
                os.remove(destino)
            shutil.move(origem, destino)
            movidos.append(rel)
            pasta = os.path.dirname(origem)
            if pasta != PASTA and os.path.isdir(pasta) and not os.listdir(pasta):
                os.rmdir(pasta)      # ex.: "Claude outputs" ficou vazia
        except OSError as e:
            _log("não consegui tirar o obsoleto {}: {}".format(rel, e))
    if movidos:
        _log("arquivos que saíram do projeto movidos para _atualizacao/obsoletos: " + ", ".join(movidos))
    return movidos


def ronda(pode_atualizar, lancador, ao_fechar):
    """Thread: verifica de tempos em tempos e aplica sozinha se estiver ligado."""
    if estado["dev"]:
        estado["local"] = versao_local()
        return
    try:
        limpa_obsoletos()
    except Exception as e:  # noqa: BLE001
        _log("erro ao limpar obsoletos: {!r}".format(e))
    time.sleep(PRIMEIRA_S)
    while True:
        try:
            verificar()
            if estado["disponivel"] and estado["automatica"] and not estado["aplicando"]:
                motivo = pode_atualizar()
                if motivo is True:
                    _log("versão nova no GitHub ({}): {}".format(estado["remoto"][:7], estado["mensagem"]))
                    aplicar(lancador, ao_fechar)
                else:
                    _log("versão nova no GitHub, mas agora não ({}): tento de novo depois".format(motivo))
        except Exception as e:  # noqa: BLE001
            _log("erro na verificação: {!r}".format(e))
        time.sleep(INTERVALO_S if not estado["disponivel"] else 5 * 60)
