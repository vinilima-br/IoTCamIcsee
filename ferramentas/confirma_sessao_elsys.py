# -*- coding: utf-8 -*-
"""
ferramentas/confirma_sessao_elsys.py  -  Confirma o AES da sessao (CBC/IV0) lendo configs.

Sessao da Elsys = AES-128-CBC, chave = nossa CommunicateKey, IV = 0, base64,
zero-padding. Este script forja a sessao e LE algumas configs inteiras (JSON
completo), pra confirmar a cifra e ja mostrar o que precisamos pra falar e pra
luz: volume, saida de alarme, vozes, luz branca.

pip install pycryptodome.  Uso (INICIAR_SESSAO.bat fechado):
    python ferramentas\\confirma_sessao_elsys.py
"""
import hashlib, json, os, socket, struct, time, base64
from Crypto.Cipher import AES

CAM_IP = "192.168.3.119"
PORTA = 34567
PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_ABRE = os.path.join(PASTA, "elsys_abre_1413.bin")
ARQ_MAT = os.path.join(PASTA, "elsys_material.json")
ALVO_MD5 = "c3d5cb9dab71dfcc8e40829b1b12658d"
K = b"ABCDEF0123456789"
MAX_CONEXOES = 25
GET_CONFIG, SET_CONFIG = 1042, 1040


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


def enc(data):
    return AES.new(K, AES.MODE_CBC, b"\x00" * 16).encrypt(data + b"\x00" * ((-len(data)) % 16))


def dec(data):
    return AES.new(K, AES.MODE_CBC, b"\x00" * 16).decrypt(data)


def forja():
    mat = json.load(open(ARQ_MAT))
    mod_hex, exp_hex = mat["PublicKey"].split(",")
    N, e = int(mod_hex, 16), int(exp_hex, 16)
    abre_raw = open(ARQ_ABRE, "rb").read()
    ck = rsa_pkcs1v15(K, N, e).hex().upper()
    login = {"EncryptType": "MD5", "LoginType": "DVRIP-FutureHome",
             "UserName": mat["UserName_rsa"], "PassWord": mat["PassWord_rsa"],
             "CommunicateKey": ck}
    lb = json.dumps(login, separators=(",", ":")).encode() + b"\x00"
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
            s.close(); time.sleep(0.5); continue
        s.sendall(frame(1000, lb, sessao=s14))
        for _ in range(5):
            mid, sess, corpo = recv_frame(s, 6)
            if mid == 1001:
                try:
                    sid = int(str(json.loads(corpo.rstrip(b"\x00\r\n ").decode()).get("SessionID")), 16)
                    return s, sid
                except Exception:
                    pass
            if mid is None:
                break
        s.close()
    return None, None


def get_config(sock, sid, nome):
    sid_hex = "0x%08X" % sid
    body = ('{"Name":"%s","SessionID":"%s"}' % (nome, sid_hex)).encode() + b"\x00"
    # payload = base64(cifra) + \x00 terminador (igual a captura: 88 b64 + 1 nulo)
    sock.sendall(frame(GET_CONFIG, base64.b64encode(enc(body)) + b"\x00", sessao=sid))
    mid, sess, corpo = recv_frame(sock, 6)
    if mid is None:
        return None, "sem resposta"
    s = corpo.rstrip(b"\x00\r\n ")
    try:
        plain = dec(base64.b64decode(s + b"=" * (-len(s) % 4))).rstrip(b"\x00\r\n ")
        txt = plain.decode("utf-8", "replace")
        return json.loads(txt), txt
    except Exception as ex:
        return None, "erro: %s" % ex


def main():
    print("=" * 60)
    print(" CONFIRMA SESSAO (AES-CBC/IV0, chave nossa)")
    print("=" * 60)
    sock, sid = forja()
    if sock is None:
        print("[X] nao forjei a sessao (rode de novo).")
        return
    print("[i] sessao OK, SID=0x%X. Lendo configs...\n" % sid)
    try:
        for nome in ["fVideo.Volume", "Alarm.AlarmOut", "Camera.WhiteLight", "Ability.VoiceTipType"]:
            j, txt = get_config(sock, sid, nome)
            ok = "[OK]" if j is not None else "[--]"
            print("%s %s:" % (ok, nome))
            print("     %s" % (txt[:280] if isinstance(txt, str) else txt))
        print("\n" + "=" * 60)
        print(" Se os valores acima vieram como JSON legivel, a cifra da sessao")
        print(" esta 100%% confirmada (CBC/IV0). Proximo: falar e acender a luz.")
    finally:
        try:
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
