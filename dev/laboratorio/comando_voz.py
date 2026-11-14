# =============================================================
#  comando_voz.py  -  PASSO 3: reconhece o comando E ACIONA
#
#  Escuta a camera, e quando voce diz o gatilho + comando, ele chama
#  o SEU servidor (a mesma rota que a pagina usa) para ligar a luz.
#
#    "O senhor e meu pastor, alerta"  ->  liga a luz de alerta da cam2
#
#  IMPORTANTE: o servidor (servidor.py / INICIAR.bat) precisa estar
#  RODANDO, porque e ele quem fala com a camera na porta 34567.
#  Este script so pede pelo HTTP, igual a pagina - sem risco de 205.
#
#  Uso:
#  LABORATORIO: experimento do comando por voz (nao faz parte do app).
#  Precisa:  pip install sherpa-onnx   (o modelo baixa sozinho)
#     python dev\laboratorio\comando_voz.py        (escuta a cam2)
#     python dev\laboratorio\comando_voz.py cam3   (escuta/aciona outra camera)
# =============================================================

import collections
import json
import math
import os
import re
import subprocess
import sys
import tarfile
import unicodedata
import urllib.error
import urllib.request

import numpy as np

# este arquivo fica em dev/laboratorio/: a pasta do projeto e 2 niveis acima
PASTA_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PASTA_BASE, "app"))   # o codigo fica em app/
sys.path.append(PASTA_BASE)                           # config.py

import config  # noqa: E402

# ---- Servidor e acao da luz (mexer aqui para ajustar) ----
SERVIDOR = "http://127.0.0.1:5050"   # onde o servidor.py roda
ALERTA_SEGUNDOS = 10                  # quanto tempo a luz fica acesa
ALERTA_SOM = None                     # None = so luz | "" = sirene | "arquivo.wav"

MODELO_NOME = "sherpa-onnx-whisper-small"
MODELO_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
              "asr-models/sherpa-onnx-whisper-small.tar.bz2")
MODELO_DIR = os.path.join(PASTA_BASE, "modelos", MODELO_NOME)
ENCODER = os.path.join(MODELO_DIR, "small-encoder.int8.onnx")
DECODER = os.path.join(MODELO_DIR, "small-decoder.int8.onnx")
TOKENS = os.path.join(MODELO_DIR, "small-tokens.txt")

TAXA = 16000

QUADRO_MS = 30
QUADRO = int(TAXA * QUADRO_MS / 1000)
QUADRO_BYTES = QUADRO * 2
SILENCIO_FIM = int(0.7 * 1000 / QUADRO_MS)
MIN_FALA = int(0.3 * 1000 / QUADRO_MS)
MAX_FALA = int(12 * 1000 / QUADRO_MS)
PRE_ROLL = int(0.3 * 1000 / QUADRO_MS)

# =============================================================
#  GATILHO E COMANDOS  (so mexer AQUI para adicionar mais tarde)
# =============================================================
GATILHOS_WAKE = [
    "o senhor e meu pastor",
    "senhor e meu pastor",
    "meu pastor",
]

COMANDOS = [
    {"nome": "luz de alerta", "acao": "LUZ_ALERTA", "gatilhos": ["alerta", "alarme"]},
]


def normaliza(texto):
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tem_wake(norm):
    return any(g in norm for g in GATILHOS_WAKE)


def acha_comando(norm):
    for c in COMANDOS:
        if any(g in norm for g in c["gatilhos"]):
            return c
    return None


def aciona(acao, cid):
    """Chama o servidor para executar a acao de verdade."""
    if acao == "LUZ_ALERTA":
        url = "{}/api/xm/{}/alerta".format(SERVIDOR, cid)
        corpo = {"ligar": True, "segundos": ALERTA_SEGUNDOS, "som": ALERTA_SOM}
        try:
            req = urllib.request.Request(
                url, data=json.dumps(corpo).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as r:
                resp = json.loads(r.read().decode("utf-8", "replace"))
            if resp.get("ok"):
                print("   >>> LUZ DE ALERTA LIGADA ({}s)".format(ALERTA_SEGUNDOS))
                if resp.get("aviso"):
                    print("       aviso:", resp["aviso"])
            else:
                print("   >>> o servidor recusou:", resp.get("erro"))
        except urllib.error.URLError as e:
            print("   >>> nao consegui falar com o servidor ({}).".format(e))
            print("       O servidor.py esta rodando em {} ?".format(SERVIDOR))
        except Exception as e:
            print("   >>> erro ao acionar:", e)


def acha_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def escolhe_camera(argumento):
    cams = config.cameras()
    if argumento:
        for c in cams:
            if c["cid"] == argumento or c["ip"] == argumento:
                return c
        print("Nao achei a camera '{}' no config.py.".format(argumento))
        print("Disponiveis:", ", ".join("{} ({})".format(c["cid"], c["ip"]) for c in cams))
        sys.exit(1)
    for c in cams:
        if c["cid"] == "cam2":
            return c
    for c in cams:
        if c["tipo"] == "icsee":
            return c
    return cams[0]


def url_rtsp(cam):
    if cam["tipo"] == "elsys":
        return "rtsp://{ip}:{porta}/user={u}_password={s}_channel=1_stream=0.sdp".format(
            ip=cam["ip"], porta=cam.get("porta", 554),
            u=cam.get("usuario", "admin"), s=cam.get("senha", ""))
    import onvif_rtsp
    urls = onvif_rtsp.descobre_urls(cam["ip"], cam["usuario"], cam["senha"],
                                    cam.get("porta_onvif") or None)
    return urls[1] if len(urls) > 1 else urls[0]


def garante_modelo():
    if os.path.isfile(ENCODER) and os.path.isfile(DECODER) and os.path.isfile(TOKENS):
        return
    pasta_modelos = os.path.join(PASTA_BASE, "modelos")
    os.makedirs(pasta_modelos, exist_ok=True)
    destino = os.path.join(pasta_modelos, MODELO_NOME + ".tar.bz2")
    print("Baixando o modelo Whisper em ONNX (so na 1a vez, ~250 MB)...")
    try:
        def _progresso(blocos, tam, total):
            if total > 0:
                pct = min(100, blocos * tam * 100 // total)
                sys.stdout.write("\r  {}%".format(pct))
                sys.stdout.flush()
        urllib.request.urlretrieve(MODELO_URL, destino, _progresso)
        print("\r  100%  -  descompactando...")
        with tarfile.open(destino, "r:bz2") as t:
            t.extractall(pasta_modelos)
        os.remove(destino)
        print("Modelo pronto em modelos/{}".format(MODELO_NOME))
    except Exception as erro:
        print("\nNao consegui baixar/extrair o modelo:", erro)
        print("Baixe a mao em: {}".format(MODELO_URL))
        sys.exit(1)


def cria_reconhecedor():
    import sherpa_onnx
    try:
        rec = sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=ENCODER, decoder=DECODER, tokens=TOKENS,
            language="pt", task="transcribe",
            num_threads=4, provider="cpu",
            decoding_method="greedy_search",
        )
        print("Whisper (sherpa-onnx) em CPU.")
        return rec
    except Exception as erro:
        print("Nao consegui iniciar o reconhecedor:", erro)
        sys.exit(1)


def le_quadro(stream):
    buffer = b""
    while len(buffer) < QUADRO_BYTES:
        pedaco = stream.read(QUADRO_BYTES - len(buffer))
        if not pedaco:
            return None
        buffer += pedaco
    return buffer


def rms(bytes_quadro):
    amostras = np.frombuffer(bytes_quadro, dtype=np.int16).astype(np.float32)
    return math.sqrt(float(np.mean(amostras * amostras)) + 1e-9)


def transcreve(rec, quadros):
    audio = np.frombuffer(b"".join(quadros), dtype=np.int16).astype(np.float32) / 32768.0
    s = rec.create_stream()
    s.accept_waveform(TAXA, audio)
    rec.decode_stream(s)
    return s.result.text.strip()


def interpreta(texto, cid):
    print("   ouvi:", texto)
    norm = normaliza(texto)
    if not tem_wake(norm):
        return
    comando = acha_comando(norm)
    if comando:
        print("   >>> COMANDO: {}".format(comando["nome"]))
        aciona(comando["acao"], cid)
    else:
        print("   >>> (ouvi o gatilho, mas nao reconheci nenhum comando)")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        print("O sherpa-onnx nao esta instalado. Rode:  pip install sherpa-onnx")
        sys.exit(1)

    cam = escolhe_camera(sys.argv[1] if len(sys.argv) > 1 else "")
    cid_cam = cam["cid"]
    print("Camera: {} ({}) - {}".format(cid_cam, cam["ip"], cam["nome"]))
    try:
        rtsp = url_rtsp(cam)
    except Exception as erro:
        print("Nao consegui o endereco de video da camera:", erro)
        sys.exit(1)

    garante_modelo()
    print("Carregando o Whisper...")
    rec = cria_reconhecedor()

    ffmpeg = acha_ffmpeg()
    comando = [
        ffmpeg, "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", rtsp,
        "-vn", "-ac", "1", "-ar", str(TAXA),
        "-af", "volume=3.0",
        "-f", "s16le", "-",
    ]
    proc = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    print("Calibrando o silencio (fique quieto 1,5 s)...")
    fundo_amostras = []
    for _ in range(int(1.5 * 1000 / QUADRO_MS)):
        q = le_quadro(proc.stdout)
        if q is None:
            print("A camera nao mandou audio. Tente outra (ex.: python dev\\laboratorio\\comando_voz.py cam3).")
            return
        fundo_amostras.append(rms(q))
    fundo = sorted(fundo_amostras)[len(fundo_amostras) // 2]
    limiar = max(40.0, fundo * 3.0)
    print("Pronto. (fundo ~{:.0f}, limiar ~{:.0f})".format(fundo, limiar))

    print("\n== Diga:  \"O senhor e meu pastor, alerta\"   (Ctrl+C para parar) ==\n")
    pre = collections.deque(maxlen=PRE_ROLL)
    buffer_fala = []
    em_fala = False
    silencio = 0
    frames_falados = 0

    def fecha_frase():
        nonlocal buffer_fala, em_fala, silencio, frames_falados
        if frames_falados >= MIN_FALA:
            texto = transcreve(rec, buffer_fala)
            if texto:
                interpreta(texto, cid_cam)
        buffer_fala = []
        em_fala = False
        silencio = 0
        frames_falados = 0

    try:
        while True:
            q = le_quadro(proc.stdout)
            if q is None:
                print("\nO audio parou de chegar.")
                break

            if rms(q) >= limiar:
                if not em_fala:
                    em_fala = True
                    buffer_fala = list(pre)
                buffer_fala.append(q)
                frames_falados += 1
                silencio = 0
            else:
                if em_fala:
                    buffer_fala.append(q)
                    silencio += 1
                    if silencio >= SILENCIO_FIM:
                        fecha_frase()
                else:
                    pre.append(q)

            if em_fala and len(buffer_fala) >= MAX_FALA:
                fecha_frase()
    except KeyboardInterrupt:
        print("\n\nParando.")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()
