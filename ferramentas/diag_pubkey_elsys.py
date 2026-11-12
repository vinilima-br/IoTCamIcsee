# -*- coding: utf-8 -*-
"""
ferramentas/diag_pubkey_elsys.py  -  A chave publica RSA muda a cada conexao?

Abre 3 conexoes novas, manda SO o abre-alas (1413) e le o 1414 (chave+caps).
NAO faz login nenhum (nao manda senha) -> risco ZERO de 203/205.

Compara os blocos 1414: se forem iguais, a chave e estavel; se diferentes,
e por-conexao (cada conexao tem a sua) -> o login tem que ser montado na hora,
lendo a chave da propria conexao.

Uso:  python ferramentas\\diag_pubkey_elsys.py
"""
import hashlib, os, socket, struct, time

CAM_IP = "192.168.3.119"
PORTA = 34567
PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_ABRE = os.path.join(PASTA, "elsys_abre_1413.bin")


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


def pega_1414(abre_raw):
    sock = socket.create_connection((CAM_IP, PORTA), timeout=6)
    try:
        sock.sendall(abre_raw)
        for _ in range(4):
            mid, sess, corpo = recv_frame(sock, 3)
            if mid is None:
                return None
            if mid == 1414:
                return corpo.rstrip(b"\x00\r\n ")
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


def main():
    abre_raw = open(ARQ_ABRE, "rb").read()
    blocos = []
    for i in range(3):
        b = pega_1414(abre_raw)
        if b is None:
            print("conexao %d: sem 1414" % (i + 1))
        else:
            h = hashlib.md5(b).hexdigest()[:12]
            print("conexao %d: 1414 com %d bytes, md5=%s" % (i + 1, len(b), h))
            blocos.append(b)
        time.sleep(1.5)
    print("-" * 56)
    if len(blocos) >= 2:
        iguais = all(b == blocos[0] for b in blocos)
        if iguais:
            print("TODAS IGUAIS -> a chave e ESTAVEL (pelo menos agora).")
        else:
            print("DIFERENTES -> a chave muda A CADA CONEXAO.")
            print("=> o login tem que ser montado na hora, com a chave da propria conexao.")
    print("Me manda este resultado.")


if __name__ == "__main__":
    main()
