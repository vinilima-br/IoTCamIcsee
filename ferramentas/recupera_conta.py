# -*- coding: utf-8 -*-
"""
recupera_conta.py  -  Descobre a CONTA REAL da camera iCSee/Xiongmai (porta 34567)
                      e, se voce quiser, define nela uma senha fixa sua.

POR QUE ISTO EXISTE
-------------------
O "admin" de senha em branco dessas cameras e uma CONTA DE TESTE DE FABRICA
(backdoor). Ela funciona por uma janela depois do reset e depois passa a dar
Ret 205 sozinha, so pela passagem do tempo - foi isso que travou a cam2/cam3.
Alem dela, toda camera tem uma CONTA REAL por aparelho (nome tipo "xkfu"), que
NAO expira. Esta ferramenta:
  1) loga com admin/branco (enquanto a janela esta aberta, logo apos um reset);
  2) le o numero de serie real da camera (SystemInfo, msg 1020);
  3) pede a conta real a propria camera (GetRandomUser, msg 1660) e descriptografa
     (AES-128-CBC, IV zero, chave montada do numero de serie);
  4) opcional: define uma senha fixa sua na conta real (ChangeRandomUser, msg 1660,
     sem login) e confirma logando com ela;
  5) mostra a linha pronta para o config.py.

Depois disso, o servidor loga na 34567 com a CONTA REAL em vez do admin/branco,
e o 205 deixa de acontecer.

COMO USAR
---------
Com a SESSAO FECHADA (feche a janela do INICIAR_SESSAO.bat) e a camera recem-resetada:
    python ferramentas\\recupera_conta.py 192.168.3.67
    python ferramentas\\recupera_conta.py 192.168.3.67 --definir-senha minhasenha123

Fonte do protocolo (engenharia reversa, verificada ao vivo por terceiros):
  github.com/voidnullvalue/Icsee-android  (PROTOCOL_NOTES.md, PASSWORD_CHANGE_RE.md)
"""
import argparse
import base64
import hashlib
import json
import socket
import struct
import sys
import time

PORTA = 34567
LOGIN, LOGOUT = 1000, 1001
SYSTEMINFO = 1020
RANDOMUSER = 1660          # GetRandomUser e ChangeRandomUser usam o mesmo msgid

CODIGOS = {100: "OK", 515: "OK", 203: "senha errada",
           205: "usuario bloqueado na camera (backdoor expirou - precisa resetar)",
           204: "usuario ilegal"}


def descreve(ret):
    return "%s (%s)" % (ret, CODIGOS.get(ret, "?"))


# ------------------------------------------------------------------
#  Framing DVRIP (igual ao camera_xm.py do projeto)
# ------------------------------------------------------------------
def sofia_hash(senha):
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    h = hashlib.md5(senha.encode("utf-8")).digest()
    return "".join(chars[(h[i] + h[i + 1]) % 62] for i in range(0, 16, 2))


def _corpo(obj):
    if isinstance(obj, str):
        return obj.encode("utf-8") + b"\x0a\x00"
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\x0a\x00"


def _envia(sock, session, seq, msgid, obj):
    payload = _corpo(obj)
    cab = bytearray(20)
    cab[0] = 255
    struct.pack_into("<I", cab, 4, session)
    struct.pack_into("<I", cab, 8, seq)
    struct.pack_into("<H", cab, 14, msgid)
    struct.pack_into("<I", cab, 16, len(payload))
    sock.sendall(bytes(cab) + payload)


def _le_exato(sock, n):
    buf = b""
    while len(buf) < n:
        b = sock.recv(n - len(buf))
        if not b:
            raise ConnectionError("a camera fechou a conexao")
        buf += b
    return buf


def _le_pacote(sock):
    cab = _le_exato(sock, 20)
    if cab[0] != 255:
        raise ConnectionError("pacote invalido (cabecalho)")
    msgid = struct.unpack_from("<H", cab, 14)[0]
    tam = struct.unpack_from("<I", cab, 16)[0]
    corpo = _le_exato(sock, tam) if tam else b""
    return msgid, corpo


def _json(corpo):
    txt = corpo.rstrip(b"\x00\n\r ").decode("utf-8", "replace")
    try:
        return json.loads(txt)
    except ValueError:
        return {"__bruto__": txt[:300]}


def _pede(sock, session, seq, msgid, obj, chave_esperada, tentativas=4):
    """Envia um comando e le pacotes ate achar um JSON com a chave esperada."""
    _envia(sock, session, seq, msgid, obj)
    for _ in range(tentativas):
        _, corpo = _le_pacote(sock)
        r = _json(corpo)
        if chave_esperada in r or "Ret" in r:
            return r
    return {}


# ------------------------------------------------------------------
#  Descriptografia da conta real (AES-128-CBC, IV zero, chave do serial)
# ------------------------------------------------------------------
def deriva_chave(serial):
    """chave = serial[5:11] + serial[1:7] + serial[8:12]  (16 chars ASCII)."""
    if len(serial) < 12:
        return None
    return serial[5:11] + serial[1:7] + serial[8:12]


def descriptografa_conta(info_b64, serial):
    try:
        from Crypto.Cipher import AES
    except ImportError:
        print("  [!] Falta a biblioteca pycryptodome (pip install pycryptodome).")
        return None
    chave = deriva_chave(serial)
    if not chave or len(chave) != 16:
        print("  [!] Numero de serie com formato inesperado (%r) - nao montei a chave." % serial)
        return None
    try:
        cifrado = base64.b64decode(info_b64)
        aes = AES.new(chave.encode("ascii"), AES.MODE_CBC, b"\x00" * 16)
        claro = aes.decrypt(cifrado).decode("ascii", "replace")
    except Exception as e:
        print("  [!] Nao consegui descriptografar: %s" % e)
        return None
    import re
    user = re.search(r"p1:(\S*)", claro)
    pwd = re.search(r"p2:(\S*)", claro)
    if user and pwd and user.group(1) and pwd.group(1):
        return user.group(1), pwd.group(1)
    print("  [!] Descriptografou, mas nao achei o formato 'p1:... p2:...'. Texto: %r" % claro[:60])
    return None


# ------------------------------------------------------------------
#  Operacoes
# ------------------------------------------------------------------
def login(sock, usuario, senha):
    """Uma unica tentativa de login. Retorna (session_int, sid_hex) ou levanta."""
    obj = {"EncryptType": "MD5", "LoginType": "DVRIP-Web",
           "PassWord": sofia_hash(senha), "UserName": usuario}
    _envia(sock, 0, 0, LOGIN, obj)
    _, corpo = _le_pacote(sock)
    r = _json(corpo)
    ret = r.get("Ret")
    if ret not in (100, 515):
        raise RuntimeError("login recusado: Ret %s" % descreve(ret))
    sid = str(r.get("SessionID", "0x0"))
    try:
        return int(sid, 16), sid
    except ValueError:
        return 0, sid


def logout(sock, session, sid):
    try:
        _envia(sock, session, 1, LOGOUT, {"Name": "", "SessionID": sid})
        sock.settimeout(2)
        _le_pacote(sock)
    except Exception:
        pass


def change_random_user(ip, nome_atual, senha_atual, novo_nome, nova_senha):
    """ChangeRandomUser: comando SEM login, numa conexao propria."""
    s = socket.create_connection((ip, PORTA), timeout=8)
    try:
        obj = {"Name": "ChangeRandomUser",
               "ChangeRandomUser": {"RandomName": nome_atual, "RandomPwd": senha_atual,
                                    "NewName": novo_nome, "NewPwd": nova_senha}}
        r = _pede(s, 0, 0, RANDOMUSER, obj, "ChangeRandomUser")
        return r.get("Ret")
    finally:
        s.close()


# ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Recupera a conta real da camera iCSee (porta 34567).")
    ap.add_argument("ip", help="IP da camera, ex: 192.168.3.67")
    ap.add_argument("--usuario", default="admin", help="usuario do login inicial (padrao: admin)")
    ap.add_argument("--senha", default="", help="senha do login inicial (padrao: em branco)")
    ap.add_argument("--definir-senha", default=None, metavar="SENHA",
                    help="define esta senha fixa na conta real (ChangeRandomUser)")
    args = ap.parse_args()

    print("=" * 64)
    print(" RECUPERAR CONTA REAL DA CAMERA  -  %s" % args.ip)
    print("=" * 64)
    print(" IMPORTANTE: feche a janela do INICIAR_SESSAO.bat antes de rodar.")
    print(" O login inicial usa %s/'%s' - funciona na janela logo apos o reset." %
          (args.usuario, args.senha))
    print("-" * 64)

    try:
        sock = socket.create_connection((args.ip, PORTA), timeout=8)
        sock.settimeout(8)
    except OSError as e:
        print(" [X] Nao conectei na porta %d: %s" % (PORTA, e))
        print("     A camera esta na rede? O IP esta certo?")
        sys.exit(1)

    try:
        print("[1] Login %s/'%s' ..." % (args.usuario, args.senha))
        try:
            session, sid = login(sock, args.usuario, args.senha)
        except RuntimeError as e:
            print("    [X] %s" % e)
            print("\n    Se deu 205: o backdoor ja expirou. Resete a camera (botao de")
            print("    reset), reconecte no app e rode esta ferramenta logo em seguida.")
            sys.exit(2)
        print("    OK. SessionID = %s" % sid)

        print("[2] Lendo numero de serie (SystemInfo) ...")
        r = _pede(sock, session, 1, SYSTEMINFO, {"Name": "SystemInfo", "SessionID": sid}, "SystemInfo")
        serial = (r.get("SystemInfo") or {}).get("SerialNo")
        if not serial:
            print("    [X] A camera nao devolveu o SerialNo. Resposta: %r" % r)
            sys.exit(3)
        print("    SerialNo (interno da camera): %s" % serial)
        chave = deriva_chave(serial)
        print("    Chave derivada: %s" % (chave or "(formato inesperado)"))

        print("[3] Pedindo a conta real (GetRandomUser) ...")
        r = _pede(sock, session, 2, RANDOMUSER, {"Name": "GetRandomUser", "SessionID": sid}, "GetRandomUser")
        bloco = r.get("GetRandomUser") or {}
        info = bloco.get("Info") or bloco.get("InfoUser")
        if not info:
            print("    [X] A camera nao devolveu o campo Info. Resposta: %r" % r)
            sys.exit(4)
        conta = descriptografa_conta(info, serial)
        if not conta:
            sys.exit(5)
        user_real, senha_real = conta
        print("    >>> CONTA REAL encontrada:  usuario = %s   senha = %s" % (user_real, senha_real))

        logout(sock, session, sid)
        sock.close()

        # ---- opcional: definir uma senha fixa sua ----
        usuario_final, senha_final = user_real, senha_real
        if args.definir_senha is not None:
            nova = args.definir_senha
            print("[4] Definindo senha fixa na conta real (ChangeRandomUser) ...")
            ret = change_random_user(args.ip, user_real, senha_real, user_real, nova)
            if ret in (100, 515):
                print("    OK (Ret 100). Confirmando com login novo ...")
                time.sleep(1)
                s2 = socket.create_connection((args.ip, PORTA), timeout=8)
                try:
                    login(s2, user_real, nova)
                    print("    >>> Confirmado: a nova senha loga.")
                    senha_final = nova
                    logout(s2, 0, "0x0")
                except RuntimeError as e:
                    print("    [!] A troca respondeu OK, mas o login novo falhou: %s" % e)
                finally:
                    s2.close()
            else:
                print("    [!] ChangeRandomUser respondeu Ret %s - senha NAO trocada." % descreve(ret))

        print("-" * 64)
        print(" PRONTO. Use esta conta no config.py (porta 34567):")
        print()
        print("   CAM?_ADMIN_USUARIO = %r" % usuario_final)
        print("   CAM?_ADMIN_SENHA   = %r" % senha_final)
        print()
        print(" (troque o ? pelo numero da camera: cam2 -> CAM2_, cam3 -> CAM3_ ...)")
        print("=" * 64)
    finally:
        try:
            sock.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
