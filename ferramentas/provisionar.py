# -*- coding: utf-8 -*-
"""
ferramentas/provisionar.py  -  Wizard: poe uma camera iCSee NOVA no sistema
                               com UM comando so.  (so iCSee; Elsys fica de fora)

O QUE MUDOU (e por que importa)
-------------------------------
O GetRandomUser NAO le a conta: ele GERA uma senha nova a cada chamada e mata a
anterior. Entao "so recuperar" e uma acao destrutiva - a senha gira. Por isso
este wizard, na camera nova, RECUPERA e JA FIXA uma senha sua (ChangeRandomUser)
e confirma com login real. O que fica na camera e duravel, nunca a aleatoria.

  -> Recuperar+fixar: SO em camera nova / recem-resetada (admin/branco aberto).
  -> Camera que ja roda: NUNCA recupere. Use --conta USUARIO SENHA com a senha
     fixa que voce ja definiu (esse modo nao toca na porta 34567 da camera).

FLUXO (camera nova, sem --conta)
  1) portas (554 / 34567 / ONVIF)
  2) video por ONVIF com o login do app (confirma modelo; nao e obrigatorio)
  3) recupera a conta real e FIXA a senha que voce passou em --senha-fixa
  4) confirma logando com a senha fixa
  5) monta o bloco { ... } do config.py; com --gravar, insere (faz backup antes)

FLUXO (--conta USUARIO SENHA): pula 3/4, nao mexe na camera, so monta/grava.

COMO USAR (na pasta do projeto, com a SESSAO e o servidor FECHADOS)
-------------------------------------------------------------------
  # camera nova: recuperar e fixar a senha, so mostrando o bloco:
  python ferramentas\\provisionar.py 192.168.3.50 seu@email.com --senha-fixa MinhaSenha

  # mesmo, ja gravando no config.py (backup automatico):
  python ferramentas\\provisionar.py 192.168.3.50 seu@email.com --senha-fixa MinhaSenha --gravar

  # camera que ja tem senha fixa conhecida (nao toca na camera):
  python ferramentas\\provisionar.py 192.168.3.67 seu@email.com --conta swua MinhaSenha --gravar

Importante: no modo camera nova, a senha da camera E TROCADA mesmo sem --gravar
(a troca acontece na camera). O --gravar so decide se o bloco vai pro config.py.
"""
import argparse
import datetime
import getpass
import json
import os
import re
import socket
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
for _p in (os.path.join(RAIZ, "app"), AQUI):      # o codigo fica em app/
    if _p not in sys.path:
        sys.path.insert(0, _p)
if RAIZ not in sys.path:
    sys.path.append(RAIZ)                         # config.py

import config                      # noqa: E402  (lista CAMERAS + cameras())
import onvif_rtsp                  # noqa: E402  (descobre_urls / info_dispositivo)
import recupera_conta as rc        # noqa: E402  (login / GetRandomUser / ChangeRandomUser / AES)

OK, FALHA, AVISO = "  [OK]  ", "  [X]   ", "  [!]   "
CONFIG_PY = os.path.join(RAIZ, "config.py")


# ------------------------------------------------------------------ utilidades
def porta_aberta(ip, porta, timeout=2.0):
    try:
        with socket.create_connection((ip, porta), timeout=timeout):
            return True
    except OSError:
        return False


def mascara(url):
    """Esconde a senha do endereco RTSP. Lida com e-mail (@) no usuario:
    o host fica depois do ULTIMO @; o usuario/senha se separam no 1o ':'."""
    if "://" not in url:
        return url
    proto, resto = url.split("://", 1)
    if "@" not in resto:
        return url
    creds, host = resto.rsplit("@", 1)          # ultimo @ separa o host
    if ":" in creds:
        user = creds.split(":", 1)[0]
        return "%s://%s:***@%s" % (proto, user, host)
    return "%s://%s@%s" % (proto, creds, host)


def proximo_cid():
    usados = {c.get("cid") for c in config.CAMERAS}
    n = 1
    while ("cam%d" % n) in usados:
        n += 1
    return "cam%d" % n


def ip_ja_existe(ip):
    return any(c.get("ip") == ip for c in config.CAMERAS)


# ----------------------------------------------- recuperar + FIXAR a conta real
def recupera_e_fixa(ip, senha_fixa):
    """Na camera nova: recupera a conta real, fixa senha_fixa nela (ChangeRandomUser)
    e confirma com login real. Retorna (usuario, senha_fixa) ou None."""
    try:
        sock = socket.create_connection((ip, rc.PORTA), timeout=8)
        sock.settimeout(8)
    except OSError as e:
        print("%sNao conectei na porta %d: %s" % (FALHA, rc.PORTA, e))
        return None
    try:
        try:
            session, sid = rc.login(sock, "admin", "")
        except RuntimeError as e:
            print("%slogin admin/branco recusado: %s" % (FALHA, e))
            print("        Se deu 205: o backdoor expirou. Resete a camera, re-adicione")
            print("        no app e rode de novo em seguida (ou use --conta se ja tem a senha).")
            return None
        r = rc._pede(sock, session, 1, rc.SYSTEMINFO,
                     {"Name": "SystemInfo", "SessionID": sid}, "SystemInfo")
        serial = (r.get("SystemInfo") or {}).get("SerialNo")
        if not serial:
            print("%sa camera nao devolveu o numero de serie." % FALHA)
            return None
        r = rc._pede(sock, session, 2, rc.RANDOMUSER,
                     {"Name": "GetRandomUser", "SessionID": sid}, "GetRandomUser")
        bloco = r.get("GetRandomUser") or {}
        info = bloco.get("Info") or bloco.get("InfoUser")
        if not info:
            print("%sa camera nao devolveu a conta (campo Info)." % FALHA)
            return None
        conta = rc.descriptografa_conta(info, serial)
        if not conta:
            return None
        user_real, random_pwd = conta
        rc.logout(sock, session, sid)
    finally:
        try:
            sock.close()
        except Exception:
            pass

    # fixa a senha escolhida
    print("%sconta real: %s (vou fixar a sua senha nela)" % (OK, user_real))
    ret = rc.change_random_user(ip, user_real, random_pwd, user_real, senha_fixa)
    if ret not in (100, 515):
        print("%sChangeRandomUser respondeu %s - senha NAO fixada." % (FALHA, rc.descreve(ret)))
        return None

    # confirma com login real
    try:
        s2 = socket.create_connection((ip, rc.PORTA), timeout=8)
        s2.settimeout(8)
        try:
            session2, sid2 = rc.login(s2, user_real, senha_fixa)
            rc.logout(s2, session2, sid2)
        finally:
            s2.close()
    except RuntimeError as e:
        print("%sa troca respondeu OK, mas o login com a senha nova falhou: %s" % (FALHA, e))
        return None
    except OSError as e:
        print("%snao consegui confirmar o login: %s" % (FALHA, e))
        return None

    print("%ssenha fixada e confirmada (login real OK)." % OK)
    return user_real, senha_fixa


def confere_conta(ip, usuario, senha):
    """Modo --conta: so confirma que a conta informada loga (nao muda nada)."""
    try:
        s = socket.create_connection((ip, rc.PORTA), timeout=8)
        s.settimeout(8)
    except OSError as e:
        print("%snao conectei na 34567 pra conferir: %s" % (AVISO, e))
        return True   # nao bloqueia: segue com o que foi informado
    try:
        try:
            session, sid = rc.login(s, usuario, senha)
            rc.logout(s, session, sid)
            print("%sconta %s confirmada (login real OK)." % (OK, usuario))
            return True
        except RuntimeError as e:
            print("%sa conta informada NAO logou: %s" % (FALHA, e))
            return False
    finally:
        s.close()


# --------------------------------------------------------------- escreve config
def monta_bloco(cid, nome, ip, email, senha_app, admin_usuario, admin_senha,
                porta_onvif, ptz):
    return (
        "    {\n"
        '        "cid": "%s", "tipo": "icsee", "nome": "%s",\n'
        '        "ip": "%s",\n'
        '        "usuario": "%s", "senha": "%s",\n'
        '        "porta_onvif": %d,\n'
        '        "admin_usuario": "%s", "admin_senha": "%s",\n'
        '        "xm": True, "ptz": %s,\n'
        "    },\n"
    ) % (cid, nome, ip, email, senha_app, porta_onvif,
         admin_usuario, admin_senha, "True" if ptz else "False")


def insere_no_config(bloco):
    with open(CONFIG_PY, "r", encoding="utf-8") as f:
        texto = f.read()
    ini = texto.find("CAMERAS = [")
    if ini < 0:
        raise RuntimeError("nao achei 'CAMERAS = [' no config.py")
    abre = texto.find("[", ini)
    prof, fecha = 0, -1
    for i in range(abre, len(texto)):
        if texto[i] == "[":
            prof += 1
        elif texto[i] == "]":
            prof -= 1
            if prof == 0:
                fecha = i
                break
    if fecha < 0:
        raise RuntimeError("nao achei o ] que fecha a lista CAMERAS")
    linha = texto.rfind("\n", 0, fecha) + 1
    novo = texto[:linha] + bloco + texto[linha:]
    carimbo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = CONFIG_PY + ".bak_" + carimbo
    with open(backup, "w", encoding="utf-8") as f:
        f.write(texto)
    with open(CONFIG_PY, "w", encoding="utf-8") as f:
        f.write(novo)
    return backup


def _acha_bloco(texto, cid, ip):
    """(inicio, fim) do dicionario { ... } da camera dentro de CAMERAS = [ ... ].
    Procura pelo "cid"; se o bloco nao tiver cid, procura pelo "ip"."""
    ini = texto.find("CAMERAS = [")
    if ini < 0:
        raise RuntimeError("nao achei 'CAMERAS = [' no config.py")
    i, prof, blocos, abre = texto.find("[", ini) + 1, 0, [], None
    while i < len(texto):
        ch = texto[i]
        if ch == "#":                                  # comentario: pula a linha
            i = texto.find("\n", i)
            if i < 0:
                break
            continue
        if ch in "\"'":                                # string: pula ate fechar
            fim = i + 1
            while fim < len(texto) and texto[fim] != ch:
                fim += 2 if texto[fim] == "\\" else 1
            i = fim + 1
            continue
        if ch == "{":
            if prof == 0:
                abre = i
            prof += 1
        elif ch == "}":
            prof -= 1
            if prof == 0 and abre is not None:
                blocos.append((abre, i + 1))
        elif ch == "]" and prof == 0:
            break
        i += 1
    for chave, valor in (("cid", cid), ("ip", ip)):
        if not valor:
            continue
        padrao = re.compile(r"""["']%s["']\s*:\s*["']%s["']""" % (chave, re.escape(valor)))
        for a, b in blocos:
            if padrao.search(texto, a, b):
                return a, b
    raise RuntimeError("nao achei a camera %s (%s) na lista CAMERAS do config.py" % (cid, ip))


def atualiza_conta_no_config(cid, ip, usuario, senha):
    """Troca SO admin_usuario/admin_senha da camera no config.py (backup antes).
    Retorna o caminho do backup."""
    with open(CONFIG_PY, "r", encoding="utf-8") as f:
        texto = f.read()
    a, b = _acha_bloco(texto, cid, ip)
    bloco = texto[a:b]
    for chave, valor in (("admin_usuario", usuario), ("admin_senha", senha)):
        literal = json.dumps(valor)                    # "texto" com escapes - vale em Python
        padrao = re.compile(r"""(["']%s["']\s*:\s*)(["'])(?:\\.|(?!\2).)*\2""" % chave)
        if padrao.search(bloco):
            bloco = padrao.sub(lambda m: m.group(1) + literal, bloco, count=1)
        else:                                          # chave nao existia: entra antes do }
            fecha = bloco.rstrip().rfind("}")
            antes = bloco[:fecha].rstrip()
            sep = "" if antes.endswith(",") or antes.endswith("{") else ","
            bloco = antes + sep + '\n        "%s": %s,\n    ' % (chave, literal) + bloco[fecha:]
    novo = texto[:a] + bloco + texto[b:]
    compile(novo, CONFIG_PY, "exec")                   # nunca grava um config.py quebrado
    carimbo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup, n = CONFIG_PY + ".bak_" + carimbo, 2
    while os.path.exists(backup):
        backup, n = CONFIG_PY + ".bak_%s_%d" % (carimbo, n), n + 1
    with open(backup, "w", encoding="utf-8") as f:
        f.write(texto)
    with open(CONFIG_PY, "w", encoding="utf-8") as f:
        f.write(novo)
    return backup


# ----------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Poe uma camera iCSee nova no config.py.")
    ap.add_argument("ip", help="IP fixo da camera, ex: 192.168.3.50")
    ap.add_argument("email", nargs="?", default="", help="e-mail/usuario do app (video)")
    ap.add_argument("--nome", default=None, help="nome que aparece na pagina")
    ap.add_argument("--cid", default=None, help="apelido fixo (padrao: proximo camN livre)")
    ap.add_argument("--senha-app", default=None, help="senha do app (senao pergunta escondido)")
    ap.add_argument("--senha-fixa", default=None, metavar="SENHA",
                    help="camera nova: senha que vai ser FIXADA na conta real")
    ap.add_argument("--conta", nargs=2, metavar=("USUARIO", "SENHA"), default=None,
                    help="camera que ja roda: usa esta conta (nao toca na camera)")
    ap.add_argument("--sem-ptz", action="store_true", help="camera nao se mexe (ptz=False)")
    ap.add_argument("--gravar", action="store_true", help="grava o bloco no config.py")
    args = ap.parse_args()

    ip = args.ip
    print("=" * 64)
    print(" PROVISIONAR CAMERA iCSee  -  %s" % ip)
    print("=" * 64)
    if args.gravar and ip_ja_existe(ip):
        print("%sJa existe uma camera com esse IP no config.py. Nada gravado." % FALHA)
        sys.exit(1)

    # 1) portas
    print("\n1) Portas")
    p554 = porta_aberta(ip, 554)
    p34567 = porta_aberta(ip, 34567)
    onvif_abertas = [p for p in onvif_rtsp.PORTAS_ONVIF_PADRAO if porta_aberta(ip, p)]
    print("%s554   RTSP (video)" % (OK if p554 else "  [ ]   "))
    print("%s34567 XM (som, luz, conta real)" % (OK if p34567 else "  [ ]   "))
    print("%sONVIF abertas: %s" % (OK if onvif_abertas else AVISO, onvif_abertas or "nenhuma"))
    if not (p554 or p34567 or onvif_abertas):
        print("%sA camera nao respondeu em nenhuma porta. IP certo? Esta ligada?" % FALHA)
        sys.exit(1)
    if not p34567:
        print("%sSem a porta 34567 esta camera nao e iCSee com conta real." % FALHA)
        sys.exit(1)

    # 2) video (ONVIF) - opcional
    print("\n2) Video (ONVIF com o login do app)")
    email = args.email or input("   E-mail/usuario do app: ").strip()
    senha_app = args.senha_app
    if senha_app is None:
        senha_app = getpass.getpass("   Senha do app (nao aparece ao digitar): ")
    porta_onvif = 8899
    if onvif_abertas:
        for p in onvif_abertas:
            try:
                urls = onvif_rtsp.descobre_urls(ip, email, senha_app, porta_onvif=p)
                if urls:
                    porta_onvif = p
                    print("%sONVIF na porta %d, %d endereco(s):" % (OK, p, len(urls)))
                    for i, u in enumerate(urls):
                        print("        %s: %s" % ("alta" if i == 0 else "leve", mascara(u)))
                    modelo, firmware = onvif_rtsp.info_dispositivo(ip, email, senha_app, p)
                    if modelo:
                        print("%sModelo: %s   firmware: %s" % (OK, modelo, firmware))
                    break
            except Exception as e:
                ultimo = e
        else:
            print("%sONVIF nao entregou o video: %s" % (AVISO, locals().get("ultimo", "?")))
            print("        Confira o e-mail/senha do app. (Nao bloqueia a camera - sigo.)")
    else:
        print("%sNenhuma porta ONVIF aberta - sigo sem confirmar o video." % AVISO)

    # 3) conta da porta 34567
    print("\n3) Conta da porta 34567")
    if args.conta:
        admin_usuario, admin_senha = args.conta
        if not confere_conta(ip, admin_usuario, admin_senha):
            print("\n%sNada gravado." % FALHA)
            sys.exit(2)
    else:
        if not args.senha_fixa:
            print("%sCamera nova precisa de --senha-fixa SENHA (a senha que vou FIXAR)." % FALHA)
            print("        Se a camera ja roda e voce ja tem a senha, use --conta USUARIO SENHA.")
            sys.exit(2)
        print("%sModo camera nova: vou RECUPERAR e FIXAR a senha (isso MUDA a camera)." % AVISO)
        conta = recupera_e_fixa(ip, args.senha_fixa)
        if not conta:
            print("\n%sNao consegui recuperar/fixar. Nada gravado." % FALHA)
            sys.exit(2)
        admin_usuario, admin_senha = conta

    # 4) bloco do config
    cid = args.cid or proximo_cid()
    nome = args.nome or ("iCSee %s" % cid)
    bloco = monta_bloco(cid, nome, ip, email, senha_app, admin_usuario, admin_senha,
                        porta_onvif, not args.sem_ptz)

    print("\n4) Bloco para o config.py (cid = %s)" % cid)
    print("-" * 64)
    print(bloco.rstrip("\n"))
    print("-" * 64)

    if not args.gravar:
        if args.conta:
            print("\n(nada foi gravado nem alterado. Rode com --gravar pra inserir no config.py.)")
        else:
            print("\n(a senha JA foi fixada na camera. Para registrar no config.py, rode com --gravar")
            print(" ou cole o bloco acima na lista CAMERAS do config.py.)")
        return

    backup = insere_no_config(bloco)
    print("%sgravado no config.py. Backup: %s" % (OK, os.path.basename(backup)))
    print("\nFalta so testar perto da camera (sessao e servidor fechados):")
    print("   python ferramentas\\diag_fala.py        %s" % ip)
    print("   python ferramentas\\diag_luz_alerta.py  %s" % ip)
    print("Depois: suba a sessao e o servidor.")


if __name__ == "__main__":
    main()
