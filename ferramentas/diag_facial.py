# -*- coding: utf-8 -*-
"""
diag_facial.py - mede, NESTE PC, quanto custa cada etapa da análise do rosto.

Usa o mesmo código do reconhecimento (app/rostos_ia.py) numa foto real da câmera
(a última de rostos/eventos/). Testa:
  - o motor do OpenCV (automático x novo) e o número de threads;
  - redução + detecção (YuNet) e o código do rosto (SFace) separados;
  - se o painel está aberto (disputa de CPU com o vídeo da câmera).
Grava o resultado em logs/diag_facial_AAAAMMDD_HHMMSS.txt.

Uso:  python ferramentas\\diag_facial.py            (roda tudo)
      python ferramentas\\diag_facial.py --uma      (uma medição só, usado internamente)
"""
import glob
import json
import os
import platform
import socket
import subprocess
import sys
import time

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_RAIZ, "app"))
sys.path.append(_RAIZ)


def acha_foto():
    """Última foto inteira de acesso (não a miniatura _r.jpg) de qualquer câmera."""
    fotos = [f for f in glob.glob(os.path.join(_RAIZ, "rostos", "eventos", "*", "*", "*.jpg"))
             if not f.endswith("_r.jpg")]
    return max(fotos, key=os.path.getmtime) if fotos else None


def lente_da(caminho):
    cid = os.path.basename(os.path.dirname(os.path.dirname(caminho)))
    try:
        import caminhos
        with open(caminhos.estado("lentes_deteccao.json"), encoding="utf-8") as f:
            return cid, json.load(f).get(cid, "ambas")
    except Exception:  # noqa: BLE001
        return cid, "ambas"


def uma_medicao(threads):
    """Roda dentro de um processo novo (o motor do OpenCV é escolhido na partida)."""
    import cv2
    import numpy as np
    import lentes
    import rostos_ia as ia
    if threads > 0:
        cv2.setNumThreads(threads)
    foto = acha_foto()
    if foto:
        frame = cv2.imdecode(np.fromfile(foto, dtype=np.uint8), cv2.IMREAD_COLOR)
        cid, lente = lente_da(foto)
    else:
        frame = np.full((2592, 2304, 3), 120, np.uint8)
        cid, lente = "-", "baixo"
    parte, _ = lentes.recorta(frame, lente)
    t0 = time.perf_counter()
    rostos = ia.Rostos()
    ms_carregar = (time.perf_counter() - t0) * 1000

    def mede(f, n=12):
        f()
        t = time.perf_counter()
        for _ in range(n):
            f()
        return (time.perf_counter() - t) / n * 1000

    tot = mede(lambda: rostos.analisa(parte))
    achados, ms_det, ms_cod = rostos.analisa(parte)
    altura, largura = parte.shape[:2]
    escala = min(1.0, ia.LADO_DETECCAO / max(altura, largura))
    pequeno = cv2.resize(parte, (int(largura * escala), int(altura * escala)), interpolation=cv2.INTER_AREA)
    ms_reduzir = mede(lambda: cv2.resize(parte, (int(largura * escala), int(altura * escala)),
                                         interpolation=cv2.INTER_AREA))
    ms_det_so = mede(lambda: rostos.det.detect(pequeno))
    return {"foto": os.path.relpath(foto, _RAIZ) if foto else "(sintética)", "cid": cid, "lente": lente,
            "quadro": "{}x{}".format(frame.shape[1], frame.shape[0]),
            "parte_analisada": "{}x{}".format(largura, altura),
            "detecta_em": "{}x{}".format(pequeno.shape[1], pequeno.shape[0]),
            "rostos_achados": len(achados), "threads_opencv": cv2.getNumThreads(),
            "ms_carregar_modelos": round(ms_carregar), "ms_analise_total": round(tot, 1),
            "ms_reduzir": round(ms_reduzir, 1), "ms_detectar": round(ms_det_so, 1),
            "ms_codigo_rosto": round(ms_cod, 1)}


def painel_aberto():
    try:
        sys.path.append(_RAIZ)
        import config
        porta = getattr(config, "WEB_PORTA", 5050)
    except Exception:  # noqa: BLE001
        porta = 5050
    s = socket.socket()
    s.settimeout(0.5)
    aberto = s.connect_ex(("127.0.0.1", porta)) == 0
    s.close()
    return aberto


def main():
    if "--uma" in sys.argv:
        threads = int(sys.argv[sys.argv.index("--uma") + 1])
        print(json.dumps(uma_medicao(threads)))
        return
    import cv2
    linhas = []

    def diz(txt=""):
        print(txt)
        linhas.append(txt)

    diz("DIAGNÓSTICO DO RECONHECIMENTO FACIAL - " + time.strftime("%d/%m/%Y %H:%M:%S"))
    diz("Python {} | OpenCV {} | {} | núcleos: {}".format(
        platform.python_version(), cv2.__version__, platform.processor() or platform.machine(), os.cpu_count()))
    try:
        diz("AVX2: {} | otimizado: {}".format(cv2.checkHardwareSupport(cv2.CPU_AVX2), cv2.useOptimized()))
    except Exception:  # noqa: BLE001
        pass
    diz("Painel aberto agora: {}".format("SIM (a câmera está disputando a CPU)" if painel_aberto() else "não"))
    diz("")
    for motor, rotulo in (("", "automático"), ("2", "novo")):
        for threads in (0, 1):
            env = dict(os.environ)
            if motor:
                env["OPENCV_FORCE_DNN_ENGINE"] = motor
            else:
                env.pop("OPENCV_FORCE_DNN_ENGINE", None)
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "--uma", str(threads)],
                               capture_output=True, text=True, env=env, cwd=_RAIZ, timeout=300)
            nome = "motor {:<10} threads {:<7}".format(rotulo, "padrão" if threads == 0 else threads)
            try:
                d = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception:  # noqa: BLE001
                diz(nome + " -> FALHOU: " + (r.stderr.strip().splitlines() or ["?"])[-1][:200])
                continue
            diz("{} -> ANÁLISE {:>6.1f} ms  (reduzir {:.1f} + detectar {:.1f} + código {:.1f})  "
                "[{} threads, {} rosto(s)]".format(nome, d["ms_analise_total"], d["ms_reduzir"], d["ms_detectar"],
                                                   d["ms_codigo_rosto"], d["threads_opencv"], d["rostos_achados"]))
            ultimo = d
    if "ultimo" in locals():
        diz("")
        diz("Foto usada: {} ({}, câmera {}, lente {}) -> analisa {} reduzida para {}".format(
            ultimo["foto"], ultimo["quadro"], ultimo["cid"], ultimo["lente"],
            ultimo["parte_analisada"], ultimo["detecta_em"]))
    pasta = os.path.join(_RAIZ, "logs")
    os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, "diag_facial_{}.txt".format(time.strftime("%Y%m%d_%H%M%S")))
    with open(arq, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    diz("")
    diz("Resultado salvo em " + os.path.relpath(arq, _RAIZ))


if __name__ == "__main__":
    main()
