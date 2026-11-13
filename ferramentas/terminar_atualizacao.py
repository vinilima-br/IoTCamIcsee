# -*- coding: utf-8 -*-
"""
ferramentas/terminar_atualizacao.py  -  Ajudante da atualização automática.

Chamado pelo atualizador.py (processo separado, sem janela) com o plano.json:
  1) espera a Central fechar (e a janela .bat dela);
  2) se mudou código da sessão das câmeras, fecha a sessão (logout) também;
  3) troca os .bat/.ps1 (não dá pra trocar enquanto o Windows está rodando eles);
  4) se mudou o requirements.txt, roda o pip;
  5) abre a Central de novo (PAINEL.bat ou INICIAR.bat).
Registro em logs/atualizacao.log.
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

PORTA_SESSAO = 5051


def log(pasta, msg):
    try:
        os.makedirs(os.path.join(pasta, "logs"), exist_ok=True)
        with open(os.path.join(pasta, "logs", "atualizacao.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "[ajudante] " + msg + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- processos (Windows)
def _processos():
    """{pid: (pai, exe)} pela foto dos processos do Windows."""
    if os.name != "nt":
        return {}

    class PE(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_ulong), ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", ctypes.c_ulong), ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong), ("szExeFile", ctypes.c_wchar * 260)]
    k = ctypes.windll.kernel32
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    saida = {}
    pe = PE()
    pe.dwSize = ctypes.sizeof(PE)
    ok = k.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        saida[pe.th32ProcessID] = (pe.th32ParentProcessID, pe.szExeFile.lower())
        ok = k.Process32NextW(snap, ctypes.byref(pe))
    k.CloseHandle(snap)
    return saida


def vivo(pid):
    if not pid:
        return False
    if os.name == "nt":
        return pid in _processos()
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def espera_sair(pid, segundos):
    fim = time.time() + segundos
    while time.time() < fim:
        if not vivo(pid):
            return True
        time.sleep(0.4)
    return not vivo(pid)


def mata(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True,
                       creationflags=0x08000000)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def pid_na_porta(porta):
    try:
        r = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                           creationflags=0x08000000 if os.name == "nt" else 0)
    except OSError:
        return None
    for linha in r.stdout.splitlines():
        p = linha.split()
        # "ESCUTANDO"/"LISTENING" muda com o idioma: vale o endereço remoto vazio
        if len(p) >= 5 and p[1].endswith(":%d" % porta) and p[2] in ("0.0.0.0:0", "[::]:0", "*:*"):
            try:
                return int(p[4])
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------- sessão das câmeras
def fecha_sessao(pasta):
    """Pede pra sessão sair (logout limpo). Sessão antiga (sem /sair): fecha à força."""
    pid = pid_na_porta(PORTA_SESSAO)
    if not pid:
        log(pasta, "sessão das câmeras não estava rodando")
        return
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/sair" % PORTA_SESSAO, data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5).read()
        if espera_sair(pid, 20):
            log(pasta, "sessão das câmeras saiu (logout limpo)")
            return
    except Exception:  # noqa: BLE001
        pass
    procs = _processos()
    pai = procs.get(pid, (0, ""))[0]
    mata(pid)
    log(pasta, "sessão antiga fechada à força (pid %s)" % pid)
    # a janela .bat antiga da sessão fica parada em "pressione uma tecla": fecha também
    if pai and procs.get(pai, (0, ""))[1] == "cmd.exe":
        time.sleep(0.5)
        mata(pai)


# ---------------------------------------------------------------- principal
def main():
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        plano = json.load(f)
    pasta = plano["pasta"]
    log(pasta, "começou: esperando a Central fechar (pid %s)" % plano["esperar_pid"])

    if not espera_sair(plano["esperar_pid"], 90):
        log(pasta, "a Central não fechou em 90 s: fechando à força")
        mata(plano["esperar_pid"])
        time.sleep(1)
    # a janela .bat que abriu a Central termina sozinha (saída 0); espera um pouco
    pai = plano.get("pai_pid")
    if pai and os.name == "nt" and _processos().get(pai, (0, ""))[1] == "cmd.exe":
        espera_sair(pai, 10)

    if plano.get("sessao"):
        fecha_sessao(pasta)

    for rel in plano.get("depois", []):
        origem = os.path.join(plano["staging"], rel)
        destino = os.path.join(pasta, rel)
        try:
            os.makedirs(os.path.dirname(destino) or pasta, exist_ok=True)
            shutil.copy2(origem, destino)
        except OSError as e:
            log(pasta, "não troquei %s: %s" % (rel, e))
    if plano.get("depois"):
        log(pasta, "trocados: " + ", ".join(plano["depois"]))

    if plano.get("pip"):
        log(pasta, "requirements.txt mudou: rodando o pip...")
        r = subprocess.run([plano["python"], "-m", "pip", "install", "-r",
                            os.path.join(pasta, "requirements.txt"), "--disable-pip-version-check"],
                           capture_output=True, text=True, cwd=pasta,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        log(pasta, "pip terminou (código %s)" % r.returncode)

    shutil.rmtree(plano["pasta_trab"], ignore_errors=True)

    lancador = os.path.join(pasta, plano.get("lancador") or "PAINEL.bat")
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", "start", "Central de Cameras", "/min", lancador],
                         cwd=pasta, creationflags=0x08000000)
    log(pasta, "Central aberta de novo (%s)" % os.path.basename(lancador))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ERRO: %r" % e)
