# -*- coding: utf-8 -*-
"""
ferramentas/teste_sessao_elsys.py  -  Login OK: agora, da pra falar sem cifrar?

Login RSA resolvido (texto puro JSON+\\x00, cabecalho com a sessao do 1414).
Aqui testamos se a SESSAO pode ir sem criptografia, pra mandar os comandos
(OPTalk Start, AlarmOut) em texto puro. Duas tentativas:

  MODO 1 "orig"  : loga reusando a CommunicateKey capturada (sessao cifrada
                   com a chave do app, que nao sabemos). Mandar um GET em texto
                   puro deve FALHAR -> confirma que a sessao exige cifra.
  MODO 2 "vazio" : loga com CommunicateKey = ""  -> se a camera aceitar e o GET
                   em texto puro responder, a sessao vai SEM cifra: ganhamos.

Mostra, em cada modo: Ret do login e a resposta crua a um GET fVideo.Volume
mandado em texto puro. Credenciais capturadas (validas) -> sem risco de 205.

Uso (INICIAR_SESSAO.bat fechado):  python ferramentas\\teste_sessao_elsys.py
"""
import json, os, socket, struct, time

CAM_IP = "192.168.3.119"
PORTA = 34567
PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_ABRE = os.path.join(PASTA, "elsys_abre_1413.bin")
ARQ_PLAIN = os.path.join(PASTA, "elsys_login_plain.json")


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


def mostra(corpo):
    s = corpo.rstrip(b"\x00\r\n ")
    try:
        t = s.decode("utf-8")
        if t[:1] in ("{", "["):
            return "TEXTO: " + t[:240]
    except Exception:
        pass
    return "CIFRADO/bin (%d bytes): %s" % (len(s), s[:48].hex())


def roda(modo, abre_raw, login_json):
    print("\n" + "=" * 62)
    print(" MODO: %s" % modo)
    print("=" * 62)
    try:
        sock = socket.create_connection((CAM_IP, PORTA), timeout=6)
    except OSError as e:
        print("  [X] nao conectou:", e)
        return
    try:
        # abre-alas -> 1414
        sock.sendall(abre_raw)
        s14 = None
        for _ in range(4):
            mid, sess, corpo = recv_frame(sock, 3)
            if mid is None:
                break
            if mid == 1414:
                s14 = sess
                break
        if s14 is None:
            print("  [!] sem 1414; abortando modo")
            return
        print("  [i] 1414 ok, sessao negociada = 0x%X" % s14)
        # login (texto puro + \x00), cabecalho com a sessao do 1414
        payload = login_json.encode("utf-8") + b"\x00"
        sock.sendall(frame(1000, payload, sessao=s14))
        sid = None
        ret = None
        for _ in range(5):
            mid, sess, corpo = recv_frame(sock, 6)
            if mid is None:
                break
            if mid == 1001:
                txt = corpo.rstrip(b"\x00\r\n ").decode("utf-8", "replace")
                try:
                    j = json.loads(txt)
                    ret = j.get("Ret")
                    sid = j.get("SessionID")
                except Exception:
                    pass
                print("  login Ret=%s SessionID=%s" % (ret, sid))
                break
        if ret != 100:
            print("  login nao passou neste modo; parando.")
            return
        # GET fVideo.Volume em TEXTO PURO
        sid_int = int(str(sid), 16)
        getp = ('{"Name":"fVideo.Volume","SessionID":"%s"}' % sid).encode() + b"\x00"
        sock.sendall(frame(1042, getp, sessao=sid_int))
        print("  --> GET fVideo.Volume em texto puro; resposta(s):")
        for _ in range(3):
            mid, sess, corpo = recv_frame(sock, 5)
            if mid is None:
                break
            print("      msgid %d: %s" % (mid, mostra(corpo)))
    finally:
        try:
            sock.close()
        except Exception:
            pass


def main():
    abre_raw = open(ARQ_ABRE, "rb").read()
    j = json.loads(open(ARQ_PLAIN, "rb").read().rstrip(b"\x00\r\n ").decode())

    # modo orig: json como capturado (compacto)
    orig = json.dumps(j, separators=(",", ":"))
    # modo vazio: CommunicateKey = ""
    jv = dict(j)
    jv["CommunicateKey"] = ""
    vazio = json.dumps(jv, separators=(",", ":"))

    roda("orig (CommunicateKey do app)", abre_raw, orig)
    time.sleep(2)
    roda("vazio (CommunicateKey = '')", abre_raw, vazio)

    print("\n" + "#" * 62)
    print(" Me manda tudo. Se no modo 'vazio' o GET responder em TEXTO,")
    print(" a sessao aceita sem cifra e esta tudo resolvido.")
    print("#" * 62)


if __name__ == "__main__":
    main()
