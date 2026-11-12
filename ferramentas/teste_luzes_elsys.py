# -*- coding: utf-8 -*-
"""
ferramentas/teste_luzes_elsys.py  -  Descobre e testa TODAS as luzes/LEDs da Elsys.

Usa a sessao que JA esta rodando (fala com o sessao_xm.py em 127.0.0.1:5051),
entao rode com o INICIAR_SESSAO.bat ABERTO e a cam1 conectada. Nao abre sessao
nova (sem conflito de chave).

1) Lista as configs de luz/LED que a camera tem (e o valor atual).
2) Testa cada luz controlavel, uma de cada vez, com pausa - olhe a camera e
   anote qual acende.

Uso:  python ferramentas\\teste_luzes_elsys.py         (cam1)
      python ferramentas\\teste_luzes_elsys.py cam4
"""
import json, sys, time, urllib.request, urllib.error

CID = sys.argv[1] if len(sys.argv) > 1 else "cam1"
URL = "http://127.0.0.1:5051/rpc"

# configs candidatas a mexer com luz/LED/IR (lista ampla; mostra as que existirem)
CANDIDATAS = [
    "Camera.WhiteLight", "Camera.Param", "Camera.ParamEx", "Camera.ClearFog",
    "Detect.MotionDetect", "Alarm.AlarmOut", "fLedCtrl", "fVideo.GUISet",
    "NetWork.LedState", "Camera.WhiteLightV2", "Camera.FishEye", "Simplify.Encode",
    "Ability.WhiteLight", "Ability.BlueWhiteLight", "Ability.AlarmFunc",
    "OPNetAlarm", "Camera.IRCUT", "Uart.PTZControl",
]


def rpc(metodo, *args, timeout=12):
    corpo = json.dumps({"cid": CID, "metodo": metodo, "args": list(args), "kwargs": {}}).encode()
    req = urllib.request.Request(URL, data=corpo, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, "sem resposta do sessao_xm (%s)" % e
    if d.get("ok"):
        return d.get("r"), None
    return None, d.get("erro", "erro")


def ler(nome):
    r, err = rpc("ler", nome)
    return r


def grava(nome, valor):
    r, err = rpc("gravar", nome, valor)
    if err:
        return "ERRO: %s" % err
    return r


def main():
    print("=" * 62)
    print(" LUZES/LEDs DA ELSYS  (%s) - usando a sessao do sessao_xm" % CID)
    print("=" * 62)

    # checa se a sessao responde
    st, err = rpc("status")
    if st is None:
        print("[X] %s" % err)
        print("    Abra o INICIAR_SESSAO.bat e confirme que a %s conectou." % CID)
        return
    print("[i] sessao OK (logada=%s)\n" % st.get("logada"))

    print("--- 1) CONFIGS QUE A CAMERA TEM ---")
    existentes = {}
    for nome in CANDIDATAS:
        v = ler(nome)
        if v is not None:
            existentes[nome] = v
            s = json.dumps(v)
            print("  [tem] %-22s = %s" % (nome, s[:110] + ("..." if len(s) > 110 else "")))
        else:
            print("  [ -- ] %s" % nome)

    print("\n--- 2) TESTE DAS LUZES (olhe a camera; cada uma fica ~4s) ---")

    # 2a) Luz branca: varre modos
    wl = existentes.get("Camera.WhiteLight")
    if isinstance(wl, dict):
        print("\n[Luz branca] testando modos...")
        for modo in ["Open", "KeepOpen", "Manual", "Intelligent", "Auto", "Close"]:
            novo = dict(wl)
            novo["WorkMode"] = modo
            novo["Brightness"] = 100
            if isinstance(novo.get("WorkPeriod"), dict):
                wp = dict(novo["WorkPeriod"]); wp["Enable"] = 0; novo["WorkPeriod"] = wp
            r = grava("Camera.WhiteLight", novo)
            print("   WorkMode=%-12s -> %s   (acendeu? anote)" % (modo, r))
            time.sleep(4)
        grava("Camera.WhiteLight", wl)   # restaura
        print("   (restaurei a luz branca)")

    # 2b) IR / dia-noite (acende os LEDs infravermelhos - brilho vermelho fraco)
    cp = existentes.get("Camera.Param")
    if cp is not None:
        print("\n[Infravermelho/Noite] forcando modo noite por 5s...")
        try:
            arr = cp if isinstance(cp, list) else [cp]
            orig = json.dumps(arr)
            for item in arr:
                if isinstance(item, dict):
                    for k in ("DayNightColor", "IRCUTMode", "Day_Night"):
                        if k in item:
                            item[k] = "1" if isinstance(item[k], str) else 1
            print("   ->", grava("Camera.Param", arr), "(olhe se acendeu luz/IR)")
            time.sleep(5)
            grava("Camera.Param", json.loads(orig))
            print("   (restaurei dia-noite)")
        except Exception as e:
            print("   (pulei: %s)" % e)

    # 2c) LED de status (verde/vermelho), se existir controle
    for nome in ("fLedCtrl", "NetWork.LedState"):
        v = existentes.get(nome)
        if v is not None:
            print("\n[LED de status: %s] alternando..." % nome)
            try:
                for val in (0, 1, (v if not isinstance(v, (int, bool)) else None)):
                    if val is None:
                        continue
                    print("   =%s ->" % val, grava(nome, val))
                    time.sleep(3)
                grava(nome, v)
            except Exception as e:
                print("   (pulei: %s)" % e)

    print("\n" + "=" * 62)
    print(" Me diga: qual linha ACENDEU algo (e de que cor)? Com isso eu fixo")
    print(" o 'negado' na luz certa. Se nenhuma acender, uso uma VOZ de 'acesso")
    print(" negado' no alto-falante (que ja funciona) como sinal.")
    print("=" * 62)


if __name__ == "__main__":
    main()
