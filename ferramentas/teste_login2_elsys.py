# -*- coding: utf-8 -*-
"""
ferramentas/teste_login2_elsys.py  -  Login RSA da Elsys, agora em TEXTO PURO.

Descoberta do diagnostico anterior:
  - o abre-alas 1413 VERBATIM (sessao velha) faz a camera devolver o 1414 certo;
  - mas o 1000 cifrado (AES) e recusado com 117 numa conexao nova.
Hipotese: numa conexao nova o login (1000) vai em TEXTO PURO (o JSON com as
credenciais RSA dentro), nao cifrado. Formato de frame em texto puro = JSON + \\x00.

Testa algumas variacoes e mostra o Ret. Usa as credenciais capturadas (validas),
entao nao ha risco de 205. Salva o bloco 1414 em elsys_1414.bin.

Uso (INICIAR_SESSAO.bat fechado):  python ferramentas\\teste_login2_elsys.py
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


def abre_e_pega_1414(sock, abre_raw):
    """Manda o abre-alas e devolve (sessao_do_1414, corpo_1414) ou (None,None)."""
    sock.sendall(abre_raw)
    for _ in range(4):
        mid, sess, corpo = recv_frame(sock, timeout=3)
        if mid is None:
            break
        if mid == 1414:
            return sess, corpo
    return None, None


def tenta(nome, abre_raw, login_payload, sess_login):
    print("\n" + "=" * 62)
    print(" %s" % nome)
    print("=" * 62)
    try:
        sock = socket.create_connection((CAM_IP, PORTA), timeout=6)
    except OSError as e:
        print("  [X] nao conectou:", e)
        return None
    try:
        sess1414, corpo1414 = abre_e_pega_1414(sock, abre_raw)
        if corpo1414 is not None:
            print("  [i] 1414 recebido (%d bytes, sess=0x%X)" % (len(corpo1414), sess1414))
            try:
                open(os.path.join(PASTA, "elsys_1414.bin"), "wb").write(corpo1414)
            except Exception:
                pass
        else:
            print("  [!] nao veio 1414")
        sock.sendall(frame(1000, login_payload, sessao=sess_login))
        for _ in range(5):
            mid, sess, corpo = recv_frame(sock, timeout=6)
            if mid is None:
                break
            if mid == 1001:
                txt = corpo.rstrip(b"\x00\r\n ").decode("utf-8", "replace")
                print("  login 1001:", txt[:200])
                try:
                    return json.loads(txt).get("Ret")
                except Exception:
                    return None
            else:
                print("  [i] <- msgid %d (%d bytes)" % (mid, len(corpo)))
        print("  (sem resposta de login)")
        return None
    finally:
        try:
            sock.close()
        except Exception:
            pass


def main():
    abre_raw = open(ARQ_ABRE, "rb").read()
    jsonb = open(ARQ_PLAIN, "rb").read().rstrip(b"\x00\r\n ")
    sess1414 = 0x10C8DF   # valor fixo visto no 1414

    combos = [
        ("A) texto puro JSON+\\x00, sessao 0",            jsonb + b"\x00", 0),
        ("B) texto puro JSON+\\x00, sessao do 1414",      jsonb + b"\x00", sess1414),
        ("C) texto puro JSON+\\n\\x00, sessao 0",          jsonb + b"\x0a\x00", 0),
    ]
    resultado = {}
    for nome, payload, sess in combos:
        ret = tenta(nome, abre_raw, payload, sess)
        resultado[nome] = ret
        time.sleep(2)

    print("\n" + "#" * 62)
    print(" RESUMO:")
    for nome, ret in resultado.items():
        marca = "  <<< LOGIN OK!" if ret == 100 else ""
        print("   Ret=%s  %s%s" % (ret, nome, marca))
    print("#" * 62)
    if any(r == 100 for r in resultado.values()):
        print(" Achamos a forma do login. Me manda este resumo.")
    else:
        print(" Nenhuma deu 100. Me manda o resumo E o arquivo elsys_1414.bin")
        print(" (jogue na pasta do projeto) que eu analiso o bloco da camera.")


if __name__ == "__main__":
    main()
