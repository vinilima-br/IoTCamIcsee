# -*- coding: utf-8 -*-
"""
ferramentas/diag_fala.py  -  Descobre como a camera aceita tocar som VARIAS vezes.

O bug: no servidor, so o 1o som saia; os seguintes ficavam mudos ate
reiniciar. Este teste usa UMA sessao (1 login so) e experimenta as formas
de abrir o canal de voz, tocando 2 vezes cada uma. VOCE escuta e responde
s (ouviu) ou n (nao ouviu). A primeira forma que tocar as 2 vezes e salva
em xm_fala_modo.json e o servidor passa a usar ela sozinho.

ANTES DE RODAR: feche o servidor (Ctrl+C) e o app iCSee no celular.

Uso (na pasta do projeto):
   python ferramentas\\diag_fala.py                 # camera 2
   python ferramentas\\diag_fala.py 192.168.3.2     # outra camera
"""
import math
import os
import socket
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # pasta do projeto
sys.path.insert(0, os.path.join(_RAIZ, "app"))                       # o codigo fica em app/
sys.path.append(_RAIZ)                                               # config.py
import config  # noqa: E402
import camera_xm as xm  # noqa: E402

ORDEM = [
    ("sub", "conexao auxiliar (sem login), Start/Stop pela sessao"),
    ("sub_tudo", "conexao auxiliar (sem login), tudo por ela"),
    ("mesma", "tudo pela sessao principal (o jeito do bug)"),
    ("login", "conexao nova com login a cada som (sempre funciona, mas faz 1 login por som)"),
]


def bips(qtd):
    """qtd bips de 1 kHz (0,25 s cada) - pra voce saber qual tentativa e."""
    out = bytearray()
    for _ in range(qtd):
        for n in range(int(8000 * 0.25)):
            out.append(xm.lin2alaw(int(24000 * math.sin(2 * math.pi * 1000 * n / 8000))))
        out += bytes([xm.SILENCIO]) * int(8000 * 0.25)
    out += bytes([xm.SILENCIO]) * 4000
    return bytes(out)


def pergunta(txt):
    while True:
        try:
            r = input(txt).strip().lower()
        except EOFError:
            return False
        if r in ("s", "sim", "y"):
            return True
        if r in ("n", "nao", "não", "no"):
            return False
        print("   responda s ou n")


def servidor_aberto():
    try:
        with socket.create_connection(("127.0.0.1", getattr(config, "WEB_PORTA", 5050)), timeout=0.5):
            return True
    except OSError:
        return False


def main():
    # pega a camera (iCSee com 34567) da lista unica do config.py, igual o diag_luz_alerta
    icsee = [c for c in config.cameras() if c["tipo"] == "icsee" and c["xm"]]
    alvo = None
    for a in sys.argv[1:]:
        if a.count(".") == 3:
            alvo = next((c for c in icsee if c["ip"] == a),
                        {"ip": a, "admin_usuario": "admin", "admin_senha": ""})
    if alvo is None:
        alvo = icsee[0] if icsee else {"ip": "192.168.3.67", "admin_usuario": "admin", "admin_senha": ""}
    ip = alvo["ip"]
    usuario = alvo.get("admin_usuario", "admin")
    senha = alvo.get("admin_senha", "")

    print("=" * 62)
    print(" DIAGNOSTICO DA FALA: tocar som varias vezes na camera %s" % ip)
    print("=" * 62)
    if servidor_aberto():
        print("\n[!] O servidor web parece estar ABERTO. Feche ele (Ctrl+C)")
        print("    e rode este teste de novo - senao sao 2 sessoes na camera.")
        return

    s = xm.SessaoCamera("diag", ip, usuario, senha,
                        log=lambda m: print("   " + m))
    s.iniciar()
    print("\nConectando (respeitando a trava anti-205; pode levar ate ~1 min)...")
    t0 = time.time()
    while not s.conectada and time.time() - t0 < 120:
        if s.desistiu:
            break
        time.sleep(0.5)
    if not s.conectada:
        print("\n[!] Nao conectou: %s" % (s.ultimo_erro or "tempo esgotado"))
        s.encerrar()
        return

    if s.volume is not None and s.volume < 60:
        try:
            s.set_volume(90)
            print("Volume estava em %s - coloquei 90 para o teste." % s.volume)
        except Exception as e:
            print("(nao ajustei o volume: %s)" % e)

    print("\nVou tocar BIPS. Tentativa 1 = 1 bip, tentativa 2 = 2 bips.")
    print("Fique perto da camera e responda se ouviu.\n")

    resultados = []
    achou = None
    try:
        for modo, desc in ORDEM:
            print("-" * 62)
            print(" Forma '%s': %s" % (modo, desc))
            ouviu = []
            for tent in (1, 2):
                time.sleep(1.5)
                print("   tocando tentativa %d (%d bip%s)..." % (tent, tent, "s" if tent > 1 else ""))
                try:
                    r = s.falar(bips(tent), "diag %s #%d" % (modo, tent), modo=modo)
                    print("   camera respondeu: claim=%s start=%s stop=%s  pacotes=%s%s"
                          % (r["claim"], r["start"], r["stop"], r["pacotes"],
                             ("  aux=%s" % r["aux"]) if r.get("aux") else ""))
                except Exception as e:
                    print("   ERRO: %s" % e)
                    ouviu.append(False)
                    break
                ouviu.append(pergunta("   Ouviu %d bip%s? (s/n): " % (tent, "s" if tent > 1 else "")))
                if not ouviu[-1] and tent == 1:
                    break                    # nem a 1a saiu: proxima forma
            resultados.append((modo, ouviu))
            if len(ouviu) == 2 and all(ouviu):
                achou = modo
                break
            if not s.conectada:
                print("   (a sessao caiu - parando o teste)")
                break
    except KeyboardInterrupt:
        print("\n(cancelado)")
    finally:
        s.encerrar()

    print("\n" + "=" * 62)
    print(" RESULTADO")
    for modo, ouviu in resultados:
        print("   %-9s %s" % (modo, "  ".join("%d:%s" % (i + 1, "OUVIU" if o else "mudo")
                                           for i, o in enumerate(ouviu)) or "-"))
    if achou:
        xm.salva_modo_fala(ip, achou)
        print("\n A forma '%s' tocou as 2 vezes. Salvei em xm_fala_modo.json." % achou)
        print(" Agora suba o servidor:  python servidor.py")
        if achou == "login":
            print(" (obs.: essa forma faz 1 login por som; o servidor espera 10 s")
            print("  entre logins da fala pra nao tomar 205)")
    else:
        print("\n Nenhuma forma tocou 2 vezes. Me cola esta saida inteira.")
    print("=" * 62)


if __name__ == "__main__":
    main()
