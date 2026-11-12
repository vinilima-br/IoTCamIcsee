# -*- coding: utf-8 -*-
"""
ferramentas/diag_luz_alerta.py  -  Descobre como acender o LED vermelho/azul
                                   (luz de alerta) da camera quando VOCE quiser.

Esse LED e a "saida de alarme" da camera (AlarmOut). Na deteccao de
movimento ela pisca uns 4 s (AlarmOutLatch). Este teste tenta forcar a
saida pela configuracao Alarm.AlarmOut, uma forma de cada vez, e pergunta
se o LED acendeu/piscou. No fim SEMPRE volta a configuracao original.

Usa UMA sessao (1 login so), igual ao diag_fala.

ANTES DE RODAR: feche o servidor (Ctrl+C) e o app iCSee no celular.
De preferencia, deixe a camera "vendo" uma cena PARADA (sem movimento),
pra o LED nao piscar por causa da deteccao e confundir o teste.

Uso (na pasta do projeto):
   python ferramentas\\diag_luz_alerta.py                 # camera 2
   python ferramentas\\diag_luz_alerta.py 192.168.3.2     # outra camera
"""
import copy
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
import camera_xm as xm  # noqa: E402

ARQ_RESULTADO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "xm_luz_alerta.json")
SEGUNDOS_LIGADO = 6

# (nome da configuracao, AlarmOutType, AlarmOutStatus, descricao)
TENTATIVAS = [
    ("Alarm.AlarmOut", "MANUAL", "OPEN", "saida em MANUAL + OPEN"),
    ("Alarm.AlarmOut", "MANUAL", "CLOSE", "saida em MANUAL + CLOSE (algumas firmwares invertem)"),
    ("AlarmOut", "MANUAL", "OPEN", "mesma coisa pelo nome curto 'AlarmOut'"),
]


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


def le_alarm_out(s, nome):
    """Le a lista AlarmOut. Tenta o nome pedido e, se nao der, a secao Alarm."""
    try:
        v = s.ler(nome)
        if isinstance(v, list):
            return v
    except Exception as e:
        print("   (ler %s: %s)" % (nome, e))
    try:
        alarm = s.ler("Alarm")
        if isinstance(alarm, dict) and isinstance(alarm.get("AlarmOut"), list):
            return alarm["AlarmOut"]
    except Exception as e:
        print("   (ler Alarm: %s)" % e)
    return None


def grava(s, nome, valor):
    r = s.comando(xm.SET_CONFIG, {"Name": nome, "SessionID": "0x%08X" % s.session, nome: valor})
    return r.get("Ret") if isinstance(r, dict) else None


def main():
    # pega a câmera (iCSee com 34567) da lista única do config.py
    icsee = [c for c in config.cameras() if c["tipo"] == "icsee" and c["xm"]]
    alvo = None
    for a in sys.argv[1:]:
        if a.count(".") == 3:
            alvo = next((c for c in icsee if c["ip"] == a), {"ip": a, "admin_usuario": "admin", "admin_senha": ""})
    if alvo is None:
        alvo = icsee[0] if icsee else {"ip": "192.168.3.67", "admin_usuario": "admin", "admin_senha": ""}
    ip = alvo["ip"]
    usuario = alvo.get("admin_usuario", "admin")
    senha = alvo.get("admin_senha", "")

    print("=" * 62)
    print(" DIAGNOSTICO DA LUZ DE ALERTA (LED vermelho/azul) - %s" % ip)
    print("=" * 62)
    if servidor_aberto():
        print("\n[!] O servidor parece estar ABERTO. Feche ele (Ctrl+C) e rode de novo.")
        return

    s = xm.SessaoCamera("luz", ip, usuario, senha, log=lambda m: print("   " + m))
    s.iniciar()
    print("\nConectando (respeitando a trava anti-205; pode levar ate ~1 min)...")
    t0 = time.time()
    while not s.conectada and time.time() - t0 < 120 and not s.desistiu:
        time.sleep(0.5)
    if not s.conectada:
        print("\n[!] Nao conectou: %s" % (s.ultimo_erro or "tempo esgotado"))
        s.encerrar()
        return

    original = le_alarm_out(s, "Alarm.AlarmOut")
    print("\nConfiguracao atual da saida de alarme: %s" % json.dumps(original, ensure_ascii=False))
    if not original:
        print("[!] A camera nao informou AlarmOut. Me cola esta saida.")
        s.encerrar()
        return

    achou = None
    alterado = None
    try:
        print("\nOlhe para a camera. Cada tentativa deixa a saida ligada %d s.\n" % SEGUNDOS_LIGADO)
        for nome, tipo, status, desc in TENTATIVAS:
            print("-" * 62)
            print(" Tentativa: %s" % desc)
            novo = copy.deepcopy(original)
            for item in novo:
                item["AlarmOutType"] = tipo
                item["AlarmOutStatus"] = status
            ret = grava(s, nome, novo)
            print("   camera respondeu: %s" % (xm.descreve(ret) if ret is not None else "sem resposta"))
            if ret not in (100, 515):
                continue
            alterado = nome
            time.sleep(SEGUNDOS_LIGADO)
            viu = pergunta("   O LED vermelho/azul ACENDEU ou PISCOU? (s/n): ")
            r2 = grava(s, nome, original)                 # volta ao normal
            alterado = None if r2 in (100, 515) else nome
            print("   voltei ao original (%s)" % (xm.descreve(r2) if r2 is not None else "sem resposta"))
            if viu:
                apagou = pergunta("   E APAGOU depois que voltei ao original? (s/n): ")
                achou = {"nome": nome, "ligar": {"AlarmOutType": tipo, "AlarmOutStatus": status},
                         "original": original, "apaga_ao_restaurar": apagou}
                break
            time.sleep(1.5)
    except KeyboardInterrupt:
        print("\n(cancelado)")
    finally:
        if alterado:
            grava(s, alterado, original)
            print("   (configuracao original restaurada)")
        s.encerrar()

    print("\n" + "=" * 62)
    if achou:
        try:
            with open(ARQ_RESULTADO, "r", encoding="utf-8") as f:
                todos = json.load(f)
        except Exception:
            todos = {}
        todos[ip] = achou
        with open(ARQ_RESULTADO, "w", encoding="utf-8") as f:
            json.dump(todos, f, indent=1, ensure_ascii=False)
        print(" ACHAMOS: %s com %s." % (achou["nome"], achou["ligar"]))
        print(" Salvei em xm_luz_alerta.json. Me conta o resultado que eu ponho")
        print(" o botao 'Luz de alerta' na pagina.")
        if not achou["apaga_ao_restaurar"]:
            print(" Obs.: nao apagou ao restaurar -> vou tratar isso no servidor.")
    else:
        print(" Nenhuma forma acendeu o LED. Me cola esta saida inteira:")
        print(" o proximo passo e testar o disparo por 'alarme de rede'.")
    print("=" * 62)


if __name__ == "__main__":
    main()
