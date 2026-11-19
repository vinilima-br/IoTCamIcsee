# -*- coding: utf-8 -*-
"""
acesso.py  -  Senha do painel para quem entra por OUTRO aparelho.

- No próprio PC (127.0.0.1) a Central abre direto, sem senha.
- De outro aparelho da rede (celular, notebook) o painel pede a senha.
- Sem senha definida, outros aparelhos ficam BLOQUEADOS (define em ⚙ Config,
  só no próprio PC).

Guarda tudo em acesso.json, na pasta do projeto (não vai para o GitHub):
  segredo -> assina o "lembrar deste aparelho" (cookie de sessão)
  sal/hash -> a senha, embaralhada (PBKDF2-SHA256); a senha em si não é gravada
  versao  -> muda a cada troca de senha: derruba quem estava logado
"""
import hashlib
import hmac
import json
import os
import secrets
import socket
import threading
import time

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import caminhos  # noqa: E402
ARQUIVO = caminhos.estado("acesso.json")          # dados\estado\ (antes: na raiz)
VOLTAS = 200_000
TAMANHO_MIN = 6
TENTATIVAS = 5            # erros seguidos antes de travar o aparelho
TRAVA_S = 60              # 1ª trava; dobra a cada nova trava, até TRAVA_MAX_S
TRAVA_MAX_S = 900

_trava = threading.Lock()
_dados = None
_falhas = {}              # ip -> {"n": erros seguidos, "ate": travado até, "vezes": travas}


def _le():
    global _dados
    if _dados is None:
        try:
            with open(ARQUIVO, "r", encoding="utf-8") as f:
                d = json.load(f)
            _dados = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            _dados = {}
        if not _dados.get("segredo"):
            _dados["segredo"] = secrets.token_hex(32)
            _grava()
    return _dados


def _grava():
    temp = ARQUIVO + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(_dados, f, indent=2)
        os.replace(temp, ARQUIVO)
    except OSError as e:
        print("[acesso] não gravei o acesso.json: {}".format(e))


def _embaralha(senha, sal):
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(sal), VOLTAS).hex()


def segredo():
    with _trava:
        return _le()["segredo"]


def tem_senha():
    with _trava:
        d = _le()
        return bool(d.get("hash") and d.get("sal"))


def versao():
    with _trava:
        return _le().get("versao") or ""


def define(senha):
    senha = (senha or "").strip()
    if len(senha) < TAMANHO_MIN:
        raise ValueError("a senha precisa de pelo menos {} letras ou números".format(TAMANHO_MIN))
    if len(senha) > 100:
        raise ValueError("senha longa demais (máx. 100)")
    with _trava:
        d = _le()
        d["sal"] = secrets.token_hex(16)
        d["hash"] = _embaralha(senha, d["sal"])
        d["versao"] = secrets.token_hex(8)       # quem estava logado precisa entrar de novo
        _grava()
        _falhas.clear()
    print("[acesso] senha do painel definida")


def remove():
    with _trava:
        d = _le()
        for k in ("sal", "hash"):
            d.pop(k, None)
        d["versao"] = secrets.token_hex(8)
        _grava()
    print("[acesso] senha do painel removida (outros aparelhos bloqueados)")


def espera(ip):
    """Segundos que este aparelho ainda fica travado por errar a senha (0 = pode tentar)."""
    with _trava:
        f = _falhas.get(ip)
        return max(0, int(f["ate"] - time.time() + 0.999)) if f else 0


def confere(senha, ip):
    """True se a senha bate. Conta os erros por aparelho e trava quem insiste."""
    with _trava:
        d = _le()
        f = _falhas.setdefault(ip, {"n": 0, "ate": 0.0, "vezes": 0})
        if f["ate"] > time.time() or not (d.get("hash") and d.get("sal")):
            return False
        ok = hmac.compare_digest(_embaralha(senha or "", d["sal"]), d["hash"])
        if ok:
            _falhas.pop(ip, None)
            return True
        f["n"] += 1
        if f["n"] >= TENTATIVAS:
            f["n"] = 0
            f["ate"] = time.time() + min(TRAVA_S * (2 ** f["vezes"]), TRAVA_MAX_S)
            f["vezes"] += 1
            print("[acesso] {} errou a senha {} vezes: travado por um tempo".format(ip, TENTATIVAS))
        if len(_falhas) > 500:                       # não deixa a lista crescer sem fim
            agora = time.time()
            for k in [k for k, v in _falhas.items() if v["ate"] < agora and k != ip]:
                _falhas.pop(k, None)
        return False


def ip_na_rede():
    """IP deste PC na rede local (para mostrar o endereço do celular). Não envia nada."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None
