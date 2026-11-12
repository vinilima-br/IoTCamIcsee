# -*- coding: utf-8 -*-
"""
ferramentas/diag_handshake_elsys.py  -  Descobre a abertura certa do login RSA.

Testa, em conexoes NOVAS e separadas, algumas formas de abrir a conversa com a
Elsys na 34567, e mostra TUDO que a camera responde (msgid, sessao, corpo).
Objetivo: achar o que faz a camera devolver o 1414 (chave/capacidades) e aceitar
o 1000 (login).

Nao manda senha errada nenhuma (o 1000 usa as credenciais capturadas, que ja
funcionaram), entao nao corre risco de 205.

Uso (INICIAR_SESSAO.bat fechado):  python ferramentas\\diag_handshake_elsys.py
"""
import json, os, socket, struct, time

CAM_IP = "192.168.3.119"
PORTA = 34567
PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_ABRE = os.path.join(PASTA, "elsys_abre_1413.bin")
ARQ_LOGIN = os.path.join(PASTA, "elsys_login_1000.b64")


def recv_frame(sock, timeout=3):
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
    sessao = struct.unpack_from("<I", cab, 4)[0]
    msgid = struct.unpack_from("<H", cab, 14)[0]
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
    return msgid, sessao, corpo


def frame(msgid, payload, sessao=0, seq=0):
    cab = bytearray(20)
    cab[0] = 255
    struct.pack_into("<I", cab, 4, sessao)
    struct.pack_into("<I", cab, 8, seq)
    struct.pack_into("<H", cab, 14, msgid)
    struct.pack_into("<I", cab, 16, len(payload))
    return bytes(cab) + payload


def dump(sock, rotulo, espera=4):
    """Le e imprime tudo o que a camera mandar em ~espera segundos."""
    print("   <%s> respostas da camera:" % rotulo)
    t0 = time.time()
    vazios = 0
    viu = False
    while time.time() - t0 < espera and vazios < 2:
        mid, sess, corpo = recv_frame(sock, timeout=1.5)
        if mid is None:
            vazios += 1
            continue
        vazios = 0
        viu = True
        s = corpo.rstrip(b"\x00\r\n ")
        try:
            txt = s.decode("utf-8")
            if txt[:1] not in ("{", "["):
                raise ValueError
            mostra = txt[:240]
        except Exception:
            mostra = "(bin %d) %s" % (len(s), s[:40].hex())
        print("       msgid %-5d sess=0x%X  %s" % (mid, sess, mostra))
    if not viu:
        print("       (nada — camera ficou muda)")


def variante(nome, construir_e_enviar):
    print("\n" + "=" * 64)
    print(" VARIANTE: %s" % nome)
    print("=" * 64)
    try:
        sock = socket.create_connection((CAM_IP, PORTA), timeout=6)
    except OSError as e:
        print("   [X] nao conectou:", e)
        return
    try:
        construir_e_enviar(sock)
    finally:
        try:
            sock.close()
        except Exception:
            pass


def main():
    abre_raw = open(ARQ_ABRE, "rb").read()
    corpo_abre = abre_raw[20:]                    # so o corpo JSON do 1413
    login_b64 = open(ARQ_LOGIN, "rb").read().strip()

    # 1) abre com sessao 0 no cabecalho, depois login
    def v1(sock):
        sock.sendall(frame(1413, corpo_abre, sessao=0))
        dump(sock, "apos 1413 sessao=0", espera=4)
        sock.sendall(frame(1000, login_b64, sessao=0))
        dump(sock, "apos 1000 login", espera=5)
    variante("1413 com sessao 0  ->  1000", v1)
    time.sleep(3)

    # 2) so o 1000 (reproduz o 117, dump completo)
    def v2(sock):
        sock.sendall(frame(1000, login_b64, sessao=0))
        dump(sock, "apos 1000 (sem abre-alas)", espera=5)
    variante("so o 1000 (reproduz o 117)", v2)
    time.sleep(3)

    # 3) abre VERBATIM (sessao velha 0x1869f), depois login
    def v3(sock):
        sock.sendall(abre_raw)
        dump(sock, "apos 1413 verbatim", espera=4)
        sock.sendall(frame(1000, login_b64, sessao=0))
        dump(sock, "apos 1000 login", espera=5)
    variante("1413 verbatim (sessao velha)  ->  1000", v3)

    print("\n" + "=" * 64)
    print(" Me manda TUDO isso. A variante que devolver 1414 e depois Ret 100")
    print(" no login e a abertura certa.")
    print("=" * 64)


if __name__ == "__main__":
    main()
