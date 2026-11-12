# -*- coding: utf-8 -*-
"""
ferramentas/fala_elsys.py  -  FALAR na Elsys (enviar som pelo alto-falante).

Junta tudo que descobrimos:
  - forja a sessao (pega a chave da captura, reusa usuario/senha, chave de sessao nossa)
  - sessao cifrada em AES-128-CBC/IV0 com a nossa chave
  - OPTalk: Claim (1434, texto puro, numa conexao auxiliar) -> Start (1430, cifrado,
    na sessao principal) -> audio G.711A (1432, texto puro, na auxiliar) -> Stop (1430)

Por padrao toca um TOM de teste (pra confirmar que sai som). Com um arquivo:
    python ferramentas\\fala_elsys.py sons\\acesso_liberado.mp3
(usa ffmpeg pra converter; precisa de ffmpeg/imageio-ffmpeg)

pip install pycryptodome.  Rode com o INICIAR_SESSAO.bat fechado e fique PERTO
da camera pra ouvir.
"""
import hashlib, json, math, os, shutil, socket, struct, subprocess, sys, time, base64
from Crypto.Cipher import AES

CAM_IP = "192.168.3.119"
PORTA = 34567
PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_ABRE = os.path.join(PASTA, "elsys_abre_1413.bin")
ARQ_MAT = os.path.join(PASTA, "elsys_material.json")
ALVO_MD5 = "c3d5cb9dab71dfcc8e40829b1b12658d"
K = b"ABCDEF0123456789"
MAX_CONEXOES = 25
CLAIM, START_STOP, AUDIO = 1434, 1430, 1432
CHUNK = 320
SILENCIO = 0xD5


# ---------------- G.711 A-law ----------------
def lin2alaw(amostra):
    if amostra >= 0:
        mascara = 0xD5
    else:
        mascara = 0x55
        amostra = -amostra - 1
    if amostra > 32767:
        amostra = 32767
    seg_fim = (0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF)
    a = amostra >> 3
    seg = 0
    while seg < 8 and a > seg_fim[seg]:
        seg += 1
    if seg >= 8:
        return 0x7F ^ mascara
    aval = seg << 4
    aval |= ((a >> 1) if seg < 2 else (a >> seg)) & 0x0F
    return aval ^ mascara


def gera_tom(segundos=2.5):
    """Dois bips alternados, bem audiveis, pra confirmar que sai som."""
    out = bytearray()
    for n in range(int(8000 * segundos)):
        t = n / 8000.0
        f = 1000 if int(t / 0.25) % 2 == 0 else 1500
        amp = 22000 if (t % 0.25) < 0.2 else 0
        out.append(lin2alaw(int(amp * math.sin(2 * math.pi * f * t))))
    return bytes(out)


def acha_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def arquivo_para_alaw(caminho):
    ff = acha_ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg nao encontrado (pip install imageio-ffmpeg)")
    r = subprocess.run([ff, "-loglevel", "error", "-i", caminho, "-ac", "1",
                        "-ar", "8000", "-f", "alaw", "pipe:1"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("falha ao converter: %s" % r.stderr.decode("utf-8", "replace")[-200:])
    return r.stdout


# ---------------- DVRIP ----------------
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


def cmd_sessao(sock, sid, msgid, body):
    """Comando cifrado na sessao: base64(AES(json+\\x00)) + \\x00."""
    sock.sendall(frame(msgid, base64.b64encode(enc(body.encode() + b"\x00")) + b"\x00", sessao=sid))


def forja():
    mat = json.load(open(ARQ_MAT))
    mod_hex, exp_hex = mat["PublicKey"].split(",")
    N, e = int(mod_hex, 16), int(exp_hex, 16)
    abre_raw = open(ARQ_ABRE, "rb").read()
    ck = rsa_pkcs1v15(K, N, e).hex().upper()
    login = {"EncryptType": "MD5", "LoginType": "DVRIP-FutureHome",
             "UserName": mat["UserName_rsa"], "PassWord": mat["PassWord_rsa"], "CommunicateKey": ck}
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


def json_talk(sid, acao):
    return ('{"Name":"OPTalk","SessionID":"0x%08X","OPTalk":{"Action":"%s",'
            '"AudioFormat":{"BitRate":0,"EncodeType":"G711_ALAW","SampleBit":8,"SampleRate":8}}}'
            % (sid, acao))


def falar(sock_main, sid, alaw):
    # conexao auxiliar (sem login), usando o SID da sessao
    aux = socket.create_connection((CAM_IP, PORTA), timeout=6)
    try:
        # 1) Claim na auxiliar (texto puro)
        aux.sendall(frame(CLAIM, (json_talk(sid, "Claim")).encode() + b"\x00", sessao=sid))
        mid, sess, corpo = recv_frame(aux, 3)
        print("   Claim -> msgid %s: %s" % (mid, corpo.rstrip(b"\x00\r\n ")[:80]))
        # 2) Start na sessao principal (cifrado)
        cmd_sessao(sock_main, sid, START_STOP, json_talk(sid, "Start"))
        time.sleep(0.2)
        # 3) audio na auxiliar (texto puro), ritmo ~40ms por 320 bytes
        n = (len(alaw) + CHUNK - 1) // CHUNK
        print("   enviando %d pacotes de audio (~%.1fs)..." % (n, len(alaw) / 8000.0))
        for k in range(n):
            ped = alaw[k * CHUNK:(k + 1) * CHUNK]
            if len(ped) < CHUNK:
                ped += bytes([SILENCIO]) * (CHUNK - len(ped))
            pkt = b"\x00\x00\x01\xfa\x0e\x02" + struct.pack("<H", len(ped)) + ped
            aux.sendall(frame(AUDIO, pkt, sessao=sid))
            time.sleep(0.037)
        time.sleep(0.3)
        # 4) Stop na sessao principal (cifrado)
        cmd_sessao(sock_main, sid, START_STOP, json_talk(sid, "Stop"))
        print("   Stop enviado.")
    finally:
        try:
            aux.close()
        except Exception:
            pass


def main():
    arquivo = sys.argv[1] if len(sys.argv) > 1 else None
    print("=" * 60)
    print(" FALA ELSYS  -  enviando som pelo alto-falante")
    print("=" * 60)
    if arquivo:
        print("[i] convertendo %s para G.711..." % arquivo)
        alaw = arquivo_para_alaw(arquivo)
    else:
        print("[i] sem arquivo: usando TOM de teste (dois bips).")
        alaw = gera_tom()

    sock, sid = forja()
    if sock is None:
        print("[X] nao forjei a sessao (chave da captura nao apareceu). Rode de novo.")
        return
    print("[i] sessao OK (SID=0x%X). Fique perto da camera!\n" % sid)
    try:
        falar(sock, sid, alaw)
        print("\n[OK] Terminou. Saiu som na camera?")
    finally:
        try:
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
