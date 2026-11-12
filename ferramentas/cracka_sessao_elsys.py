# -*- coding: utf-8 -*-
"""
ferramentas/cracka_sessao_elsys.py  -  Descobre o AES da sessao da Elsys.

Ja sabemos forjar o login com uma chave de sessao NOSSA (ABCDEF0123456789).
A sessao cifra os comandos com AES derivado dessa chave. Este script forja a
sessao e testa varias formas de derivar o AES, mandando um GET fVideo.Volume
em cada forma, ate a camera responder algo que decifre certo.

Precisa da biblioteca pycryptodome:
    pip install pycryptodome

Credenciais validas -> sem risco de 203/205. Uso (INICIAR_SESSAO.bat fechado):
    python ferramentas\\cracka_sessao_elsys.py
"""
import hashlib, json, os, socket, struct, time

try:
    from Crypto.Cipher import AES
except Exception:
    print("[X] Falta a biblioteca de criptografia. Rode:  pip install pycryptodome")
    raise SystemExit(1)

CAM_IP = "192.168.3.119"
PORTA = 34567
PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_ABRE = os.path.join(PASTA, "elsys_abre_1413.bin")
ARQ_MAT = os.path.join(PASTA, "elsys_material.json")
ALVO_MD5 = "c3d5cb9dab71dfcc8e40829b1b12658d"
K = b"ABCDEF0123456789"
MAX_CONEXOES = 25
import base64


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


def frame(msgid, payload, sessao=0, seq=0):
    cab = bytearray(20)
    cab[0] = 255
    struct.pack_into("<I", cab, 4, sessao)
    struct.pack_into("<I", cab, 8, seq)
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


def forja_sessao():
    """Caca a chave da captura e forja o login. Retorna (sock, sid_int) ou (None,None)."""
    mat = json.load(open(ARQ_MAT))
    mod_hex, exp_hex = mat["PublicKey"].split(",")
    N, e = int(mod_hex, 16), int(exp_hex, 16)
    abre_raw = open(ARQ_ABRE, "rb").read()
    ck = rsa_pkcs1v15(K, N, e).hex().upper()
    login = {"EncryptType": "MD5", "LoginType": "DVRIP-FutureHome",
             "UserName": mat["UserName_rsa"], "PassWord": mat["PassWord_rsa"],
             "CommunicateKey": ck}
    login_bytes = json.dumps(login, separators=(",", ":")).encode() + b"\x00"
    for i in range(MAX_CONEXOES):
        try:
            s = socket.create_connection((CAM_IP, PORTA), timeout=6)
        except OSError:
            time.sleep(1)
            continue
        s.sendall(abre_raw)
        s14 = None
        for _ in range(4):
            mid, sess, corpo = recv_frame(s, 3)
            if mid is None:
                break
            if mid == 1414:
                if hashlib.md5(corpo.rstrip(b"\x00\r\n ")).hexdigest() == ALVO_MD5:
                    s14 = sess
                break
        if s14 is None:
            s.close()
            time.sleep(0.5)
            continue
        s.sendall(frame(1000, login_bytes, sessao=s14))
        for _ in range(5):
            mid, sess, corpo = recv_frame(s, 6)
            if mid is None:
                break
            if mid == 1001:
                try:
                    sid = int(str(json.loads(corpo.rstrip(b"\x00\r\n ").decode()).get("SessionID")), 16)
                    print("  [i] sessao forjada OK, SID=0x%X (conexao %d)" % (sid, i + 1))
                    return s, sid
                except Exception:
                    pass
        s.close()
    return None, None


def candidatos():
    md5k = hashlib.md5(K).digest()
    return [
        ("ECB key=K",            AES.MODE_ECB, K,     None),
        ("CBC key=K IV=0",       AES.MODE_CBC, K,     b"\x00" * 16),
        ("CBC key=K IV=K",       AES.MODE_CBC, K,     K),
        ("ECB key=md5(K)",       AES.MODE_ECB, md5k,  None),
        ("CBC key=md5(K) IV=0",  AES.MODE_CBC, md5k,  b"\x00" * 16),
    ]


def enc(mode, key, iv, data):
    c = AES.new(key, mode) if iv is None else AES.new(key, mode, iv)
    return c.encrypt(data)


def dec(mode, key, iv, data):
    c = AES.new(key, mode) if iv is None else AES.new(key, mode, iv)
    return c.decrypt(data)


def pad0(b):
    return b + b"\x00" * ((-len(b)) % 16)


def main():
    print("=" * 62)
    print(" CRACKA SESSAO ELSYS  -  achando o AES da sessao")
    print("=" * 62)
    achou = False
    for nome, mode, key, iv in candidatos():
        print("\n--- candidato: %s ---" % nome)
        sock, sid = forja_sessao()
        if sock is None:
            print("  (nao peguei a chave da captura nesta rodada; pulando)")
            continue
        try:
            sid_hex = "0x%08X" % sid
            getjson = ('{"Name":"fVideo.Volume","SessionID":"%s"}' % sid_hex).encode()
            alvo_plain = pad0(getjson + b"\x00")
            cifra = enc(mode, key, iv, alvo_plain)
            sock.sendall(frame(1042, base64.b64encode(cifra), sessao=sid))
            mid, sess, corpo = recv_frame(sock, 5)
            if mid is None:
                print("  -> sem resposta (derivacao provavelmente errada)")
                continue
            s = corpo.rstrip(b"\x00\r\n ")
            try:
                cback = base64.b64decode(s + b"=" * (-len(s) % 4))
                plain = dec(mode, key, iv, cback).rstrip(b"\x00\r\n ")
                txt = plain.decode("utf-8", "replace")
                if txt.strip()[:1] in ("{", "["):
                    print("  -> [ACHOU!] resposta decifrada: %s" % txt[:120])
                    print("\n>>> DERIVACAO CORRETA: %s <<<" % nome)
                    achou = True
                    break
                else:
                    print("  -> respondeu (msgid %d, %d bytes) mas nao decifrou com esta forma" % (mid, len(s)))
            except Exception as ex:
                print("  -> resposta nao decifrou (%s)" % ex)
        finally:
            try:
                sock.close()
            except Exception:
                pass
        time.sleep(1.5)
    if not achou:
        print("\n[?] Nenhuma das derivacoes comuns decifrou. Me manda a saida INTEIRA")
        print("    que eu amplio as hipoteses (AESV2 pode ter um esquema proprio).")


if __name__ == "__main__":
    main()
