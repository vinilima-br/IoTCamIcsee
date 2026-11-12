# -*- coding: utf-8 -*-
"""
ferramentas/forja_senha_elsys.py  -  Login RSA forjado com SENHA CONHECIDA.

Depois do reset, o app pediu a senha 2119. SE o admin da 34567 for 2119, dá pra
forjar o login contra a chave publica ATUAL de cada conexao (lida do 1414 na
hora) -> acaba a dependencia da chave capturada e do revezamento (solucao durável).

Este teste faz UMA tentativa (senha errada arrisca 205). Formato do campo PassWord:
  sofia (padrao) = sofia_hash(senha)   |   raw = a senha crua   |   md5 = md5 hex maiusculo

Uso (INICIAR_SESSAO.bat fechado):
  python ferramentas\\forja_senha_elsys.py                      (192.168.3.119, 2119, sofia)
  python ferramentas\\forja_senha_elsys.py 192.168.3.119 2119 raw
"""
import base64, hashlib, json, os, socket, struct, sys, time
from Crypto.Cipher import AES

PORTA = 34567
PASTA = os.path.dirname(os.path.abspath(__file__))
KEY_SESSAO = b"ABCDEF0123456789"
KEY_1414 = b"dashoiahfarqdasr"


def sofia_hash(senha):
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    h = hashlib.md5(senha.encode("utf-8")).digest()
    return "".join(chars[(h[i] + h[i + 1]) % 62] for i in range(0, 16, 2))


def recv_frame(sock, timeout=4):
    sock.settimeout(timeout)
    cab = b""
    try:
        while len(cab) < 20:
            ch = sock.recv(20 - len(cab))
            if not ch:
                return None, 0, b""
            cab += ch
    except (socket.timeout, OSError):
        return None, 0, b""
    sess = struct.unpack_from("<I", cab, 4)[0]
    mid = struct.unpack_from("<H", cab, 14)[0]
    tam = struct.unpack_from("<I", cab, 16)[0]
    corpo = b""
    while len(corpo) < tam:
        try:
            ch = sock.recv(min(65536, tam - len(corpo)))
        except (socket.timeout, OSError):
            break
        if not ch:
            break
        corpo += ch
    return mid, sess, corpo


def frame(msgid, payload, sessao=0):
    cab = bytearray(20)
    cab[0] = 255
    struct.pack_into("<I", cab, 4, sessao)
    struct.pack_into("<H", cab, 14, msgid)
    struct.pack_into("<I", cab, 16, len(payload))
    return bytes(cab) + payload


def rsa_pkcs1v15(msg, N, e):
    k = (N.bit_length() + 7) // 8
    ps = bytearray()
    while len(ps) < k - 3 - len(msg):
        b = os.urandom(1)
        if b[0] != 0:
            ps.append(b[0])
    em = b"\x00\x02" + bytes(ps) + b"\x00" + msg
    return pow(int.from_bytes(em, "big"), e, N).to_bytes(k, "big")


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.3.119"
    senha = sys.argv[2] if len(sys.argv) > 2 else "2119"
    formato = sys.argv[3] if len(sys.argv) > 3 else "sofia"

    if formato == "sofia":
        pw_plain = sofia_hash(senha)
    elif formato == "raw":
        pw_plain = senha
    elif formato == "md5":
        pw_plain = hashlib.md5(senha.encode()).hexdigest().upper()
    elif formato == "md5low":
        pw_plain = hashlib.md5(senha.encode()).hexdigest()
    else:
        print("formato invalido"); return

    abre = open(os.path.join(PASTA, "elsys_%s_abre.bin" % ip.replace(".", "_")), "rb").read()

    print("=" * 60)
    print(" FORJA COM SENHA CONHECIDA  %s" % ip)
    print(" senha=%r formato=%s -> PassWord plano=%r UserName=%r" % (senha, formato, pw_plain, "admin"))
    print("=" * 60)
    try:
        s = socket.create_connection((ip, PORTA), timeout=6)
    except OSError as e:
        print("[X] nao conectou:", e); return

    # abre-alas -> 1414 (chave publica ATUAL desta conexao)
    s.sendall(abre)
    pub = None
    s14 = None
    for _ in range(4):
        mid, sess, corpo = recv_frame(s, 3)
        if mid is None:
            break
        if mid == 1414:
            s14 = sess
            b = corpo.rstrip(b"\x00\r\n ")
            dj = json.loads(AES.new(KEY_1414, AES.MODE_CBC, b"\x00" * 16).decrypt(
                base64.b64decode(b + b"=" * (-len(b) % 4))).rstrip(b"\x00\r\n ").decode())
            pub = dj["PublicKey"]
            break
    if not pub:
        print("[X] nao recebi a chave publica (1414)."); return
    mod_hex, exp_hex = pub.split(",")
    N, e = int(mod_hex, 16), int(exp_hex, 16)
    print("[i] chave publica atual recebida (md5 %s). Forjando login..." % hashlib.md5(mod_hex.encode()).hexdigest()[:8])

    un = rsa_pkcs1v15(b"admin", N, e).hex().upper()
    pw = rsa_pkcs1v15(pw_plain.encode(), N, e).hex().upper()
    ck = rsa_pkcs1v15(KEY_SESSAO, N, e).hex().upper()
    login = {"EncryptType": "MD5", "LoginType": "DVRIP-FutureHome",
             "UserName": un, "PassWord": pw, "CommunicateKey": ck}
    s.sendall(frame(1000, json.dumps(login, separators=(",", ":")).encode() + b"\x00", sessao=s14))

    ret = None
    for _ in range(5):
        mid, sess, corpo = recv_frame(s, 6)
        if mid is None:
            break
        if mid == 1001:
            txt = corpo.rstrip(b"\x00\r\n ").decode("utf-8", "replace")
            try:
                ret = json.loads(txt).get("Ret")
            except Exception:
                pass
            print("  resposta:", txt[:160])
            break
    print("-" * 60)
    if ret == 100:
        print("[OK] >>> LOGIN FORJADO COM SENHA CONHECIDA! <<<")
        print("     admin = %r. DÁ pra logar em QUALQUER chave atual -> fim do revezamento." % senha)
        print("     Me manda isso que eu reescrevo o elsys_xm pra usar a senha (durável).")
    elif ret == 203:
        print("[X] 203 (senha/formato nao bateu).")
        print("    Pode ser: o 2119 e so a senha de VIDEO (admin da 34567 continua escondido),")
        print("    ou o formato do campo e outro. NAO rode varias vezes seguidas (205).")
        print("    Se quiser, teste outro formato: ... 2119 raw   (espere ~1 min entre tentativas).")
    else:
        print("[?] Ret %s - me manda a saida." % ret)
    try:
        s.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
