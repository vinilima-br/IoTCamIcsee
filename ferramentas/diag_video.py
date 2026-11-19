# -*- coding: utf-8 -*-
"""
diag_video.py - mede quanto de CPU custa DECODIFICAR o vídeo Alta da câmera,
no processador (como hoje) e na placa de vídeo (aceleração por hardware, D3D11).

Feche o painel antes (senão os dois disputam a CPU e a medição fica errada).
Grava o resultado em logs/diag_video_AAAAMMDD_HHMMSS.txt.

Uso:  python ferramentas\\diag_video.py [cid]     (sem cid: a 1ª câmera iCSee do config.py)
"""
import os
import sys
import time

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer"
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_RAIZ, "app"))
sys.path.append(_RAIZ)

import cv2  # noqa: E402

import config  # noqa: E402
import onvif_rtsp  # noqa: E402

SEGUNDOS = 8
NOMES_ACEL = {0: "nenhuma (CPU)", 1: "qualquer", 2: "D3D11", 3: "VAAPI", 4: "MFX"}


def mede(url, gpu):
    params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000]
    if gpu:
        params += [cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY]
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
    if not cap.isOpened():
        return {"erro": "não abriu o vídeo"}
    acel = int(cap.get(cv2.CAP_PROP_HW_ACCELERATION))
    for _ in range(10):                      # descarta o começo (abre/ajusta)
        cap.read()
    quadros, tam = 0, None
    cpu0, t0 = time.process_time(), time.perf_counter()
    while time.perf_counter() - t0 < SEGUNDOS:
        ok, f = cap.read()
        if not ok:
            break
        quadros += 1
        tam = f.shape
    wall = time.perf_counter() - t0
    cpu = time.process_time() - cpu0
    cap.release()
    return {"fps": quadros / wall, "cpu_pct": 100.0 * cpu / wall / (os.cpu_count() or 1),
            "acel": NOMES_ACEL.get(acel, str(acel)), "tam": "{}x{}".format(tam[1], tam[0]) if tam else "-"}


def main():
    cams = config.cameras() if hasattr(config, "cameras") else []
    pedido = sys.argv[1] if len(sys.argv) > 1 else None
    cam = next((c for c in cams if (c["cid"] == pedido if pedido else c.get("tipo") == "icsee")), None)
    linhas = []

    def diz(t=""):
        print(t)
        linhas.append(t)

    diz("DIAGNÓSTICO DO VÍDEO - " + time.strftime("%d/%m/%Y %H:%M:%S") + " | OpenCV " + cv2.__version__)
    if cam is None:
        diz("Nenhuma câmera iCSee no config.py.")
        return
    diz("Câmera {} ({}) - vídeo Alta, {} s em cada modo".format(cam["cid"], cam["ip"], SEGUNDOS))
    try:
        lista = onvif_rtsp.descobre_urls(cam["ip"], cam.get("usuario") or "admin", cam.get("senha", ""),
                                         porta_onvif=cam.get("porta_onvif"))
    except Exception as e:  # noqa: BLE001
        diz("Não descobriu o endereço do vídeo: {}".format(e))
        return
    url = lista[0]
    diz("")
    for gpu, nome in ((False, "Decodificando na CPU          "), (True, "Decodificando na placa de vídeo")):
        r = mede(url, gpu)
        if "erro" in r:
            diz("{} -> {}".format(nome, r["erro"]))
        else:
            diz("{} -> {:5.1f} quadros/s | CPU usada {:5.1f}% do PC | aceleração: {} | {}".format(
                nome, r["fps"], r["cpu_pct"], r["acel"], r["tam"]))
    pasta = os.path.join(_RAIZ, "logs")
    os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, "diag_video_{}.txt".format(time.strftime("%Y%m%d_%H%M%S")))
    with open(arq, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    diz("")
    diz("Resultado salvo em " + os.path.relpath(arq, _RAIZ))


if __name__ == "__main__":
    main()
