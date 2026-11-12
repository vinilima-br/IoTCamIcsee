# -*- coding: utf-8 -*-
"""
ferramentas/dump_configs_elsys.py  -  Lista TODAS as configs que a Elsys expõe.

Usa a sessao do sessao_xm (INICIAR_SESSAO.bat ABERTO, cam1 conectada). Nao
acende nada: so LÊ e imprime, pra achar o nome da config da "Luz de status"
(e qualquer outra luz controlavel).

Uso:  python ferramentas\\dump_configs_elsys.py   > dump_elsys.txt
      (e me manda o conteudo, ou cola a saida)
"""
import json, sys, urllib.request, urllib.error

CID = sys.argv[1] if len(sys.argv) > 1 else "cam1"
URL = "http://127.0.0.1:5051/rpc"

# "árvores" (pais) - algumas câmeras devolvem o ramo inteiro de uma vez
PAIS = ["Camera", "NetWork", "Detect", "Alarm", "fVideo", "General", "Uart",
        "Ability", "OPNetAlarm", "Simplify"]

# nomes específicos ligados a luz/LED/indicador/IR
ESPECIFICAS = [
    "Camera.WhiteLight", "Camera.WhiteLightV2", "Camera.Param", "Camera.ParamEx",
    "Camera.ClearFog", "Camera.MotionLight", "Camera.StatusLight", "Camera.StatusLed",
    "Camera.IndicatorLight", "Camera.WorkLed", "Camera.Led",
    "fLedCtrl", "fLedStatus", "LedControl", "StatusLed", "OPStatusLed",
    "NetWork.LedState", "NetWork.StatusLed", "fVideo.StatusLed", "fVideo.GUISet",
    "Detect.MotionDetect", "Alarm.AlarmOut", "Alarm.LocalAlarmOut",
    "Ability.WhiteLight", "Ability.BlueWhiteLight", "Ability.LightState",
    "Ability.AlarmFunc", "Ability.SupportExtRecord",
]


def rpc(metodo, *args, timeout=12):
    corpo = json.dumps({"cid": CID, "metodo": metodo, "args": list(args), "kwargs": {}}).encode()
    req = urllib.request.Request(URL, data=corpo, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, str(e)
    if d.get("ok"):
        return d.get("r"), None
    return None, d.get("erro", "erro")


def main():
    st, err = rpc("status")
    if st is None:
        print("[X] sessao nao respondeu: %s (abra o INICIAR_SESSAO.bat)" % err)
        return
    print("sessao OK (logada=%s)\n" % st.get("logada"))

    print("######## ARVORES (pais) ########")
    for nome in PAIS:
        v, err = rpc("ler", nome)
        if v is not None:
            print("\n===== %s =====" % nome)
            print(json.dumps(v, indent=1, ensure_ascii=False)[:4000])

    print("\n\n######## CONFIGS ESPECIFICAS DE LUZ/LED ########")
    for nome in ESPECIFICAS:
        v, err = rpc("ler", nome)
        if v is not None:
            print("[tem] %-26s = %s" % (nome, json.dumps(v, ensure_ascii=False)))
        else:
            print("[-- ] %s" % nome)

    print("\n(fim) -- me manda tudo isso. Vou achar o nome da 'Luz de status'.")


if __name__ == "__main__":
    main()
