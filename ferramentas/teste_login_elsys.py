# -*- coding: utf-8 -*-
"""
ferramentas/teste_login_elsys.py  -  Login RSA da Elsys (porta 34567)

A Elsys usa login RSA ("DVRIP-FutureHome"). A captura (PCAPdroid) mostrou a
sequencia certa na conexao do login:

   1) o app manda um 1413 (OPMonitor) com uma sessao que a camera NAO conhece
   2) a camera responde 1414 com a chave publica + capacidades ("se identifique")
   3) so entao o app manda o 1000 (login RSA) e recebe 1001 Ret=100

O replay seco do 1000 (sem o passo 1) deu Ret 117 (dados fora de ordem). Este
teste refaz os tres passos, reusando os bytes capturados (credenciais que ja
funcionaram -> sem risco de 203/205).

Arquivos ao lado deste script (vindos da captura):
   elsys_abre_1413.bin   -> o 1413 inteiro (cabecalho+corpo), mandado cru
   elsys_login_1000.b64  -> o corpo do 1000 (base64 cifrado)

Uso (com o INICIAR_SESSAO.bat fechado):
   python ferramentas\\teste_login_elsys.py
"""
import json, os, socket, struct, sys, time

CAM_IP = "192.168.3.119"
PORTA = 34567
PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_ABRE = os.path.join(PASTA, "elsys_abre_1413.bin")
ARQ_LOGIN = os.path.join(PASTA, "elsys_login_1000.b64")


def recv_frame(sock, timeout=6):
    """Le um pacote DVRIP (20 bytes de cabecalho + corpo). (msgid, sessao, corpo) ou (None,..)."""
    sock.settimeout(timeout)
    cab = b""
    try:
        while len(cab) < 20:
            ch = sock.recv(20 - len(cab))
            if not ch:
                return None, 0, b""
            cab += ch
    except socket.timeout:
        return None, 0, b""
    sessao = struct.unpack_from("<I", cab, 4)[0]
    msgid = struct.unpack_from("<H", cab, 14)[0]
    tam = struct.unpack_from("<I", cab, 16)[0]
    corpo = b""
    while len(corpo) < tam:
        try:
            ch = sock.recv(min(65536, tam - len(corpo)))
        except socket.timeout:
            break
        if not ch:
            break
        corpo += ch
    return msgid, sessao, corpo


def envia(sock, msgid, payload, sessao=0, seq=0):
    cab = bytearray(20)
    cab[0] = 255
    struct.pack_into("<I", cab, 4, sessao)
    struct.pack_into("<I", cab, 8, seq)
    struct.pack_into("<H", cab, 14, msgid)
    struct.pack_into("<I", cab, 16, len(payload))
    sock.sendall(bytes(cab) + payload)


def main():
    for a in (ARQ_ABRE, ARQ_LOGIN):
        if not os.path.exists(a):
            print("[X] Falta o arquivo:", a)
            return
    abre = open(ARQ_ABRE, "rb").read()          # ja tem cabecalho; manda cru
    login_b64 = open(ARQ_LOGIN, "rb").read().strip()

    print("=" * 60)
    print(" LOGIN RSA  %s:%d" % (CAM_IP, PORTA))
    print("=" * 60)
    try:
        sock = socket.create_connection((CAM_IP, PORTA), timeout=6)
    except OSError as e:
        print("[X] nao conectou:", e)
        return

    # passo 1: abre-alas (1413) -> faz a camera mandar a chave/capacidades (1414)
    sock.sendall(abre)
    got_pub = False
    for _ in range(4):
        mid, sess, corpo = recv_frame(sock, timeout=3)
        if mid is None:
            break
        texto = corpo.rstrip(b"\x00\r\n ")[:60]
        print("[i] <- msgid %d (%d bytes) %s" % (mid, len(corpo), texto))
        if mid == 1414:
            got_pub = True
            break
    if not got_pub:
        print("[!] a camera nao mandou o 1414 (chave). Vou tentar o login mesmo assim.")

    # passo 2: login (1000), sessao 0 no cabecalho
    envia(sock, 1000, login_b64, sessao=0, seq=0)

    # passo 3: le ate a resposta de login (1001)
    ret, sid, resp_txt = None, None, ""
    for _ in range(5):
        mid, sess, corpo = recv_frame(sock, timeout=6)
        if mid is None:
            break
        if mid == 1001:
            resp_txt = corpo.rstrip(b"\x00\r\n ").decode("utf-8", "replace")
            try:
                j = json.loads(resp_txt)
                ret = j.get("Ret")
                sid = j.get("SessionID")
            except Exception:
                pass
            break
        else:
            print("[i] <- msgid %d (%d bytes)" % (mid, len(corpo)))

    print("-" * 60)
    print("resposta login:", resp_txt[:300] if resp_txt else "(sem 1001)")
    if ret == 100:
        print("[OK] >>> LOGIN ACEITO (Ret 100). SessionID = %s <<<" % sid)
        print("     Entramos como admin na Elsys. A fechadura abriu.")
    elif ret == 117:
        print("[X] Ret 117 de novo (ordem/dados). Me manda a saida que eu ajusto o abre-alas.")
    elif ret in (203, 205):
        print("[X] Ret %s (credencial/bloqueio) - inesperado no replay." % ret)
    else:
        print("[?] Resposta inesperada - me manda a saida inteira.")
    try:
        sock.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
