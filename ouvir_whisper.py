# =============================================================
#  ouvir_whisper.py  -  PASSO 1 (versao Whisper)
#
#  Igual ao ouvir_texto.py, mas usa o WHISPER (faster-whisper),
#  que entende voz de longe e audio ruim muito melhor que o Vosk.
#  Aproveita a GTX 1060: tenta a GPU e, se nao der, cai pra CPU
#  sozinho (so fica mais lento). Nao roda letra por letra: ele
#  junta a fala e, quando voce faz uma pausa, transcreve a frase.
#
#  Nao mexe na porta 34567 -> sem risco de 205. Pode rodar com o
#  servidor ligado.
#
#  Uso:
#     python ouvir_whisper.py            (usa a cam2)
#     python ouvir_whisper.py cam3       (escolhe pelo apelido)
#     python ouvir_whisper.py 192.168.3.67   (ou direto pelo IP)
#
#  Precisa instalar uma vez:   pip install faster-whisper
#  Na primeira execucao ele baixa sozinho o modelo (~460 MB).
#  Para mais/menos precisao, troque TAMANHO_MODELO abaixo
#  ("tiny", "base", "small", "medium"). "small" e um bom meio.
# =============================================================

import collections
import math
import os
import subprocess
import sys

import numpy as np

import config

PASTA_BASE = os.path.dirname(os.path.abspath(__file__))

TAMANHO_MODELO = "small"   # tiny < base < small < medium (precisao x velocidade)
TAXA = 16000               # 16 kHz mono

# --- parametros do detector de fala (tudo em quadros de 30 ms) ---
QUADRO_MS = 30
QUADRO = int(TAXA * QUADRO_MS / 1000)       # amostras por quadro (480)
QUADRO_BYTES = QUADRO * 2                    # 16 bits = 2 bytes por amostra
SILENCIO_FIM = int(0.7 * 1000 / QUADRO_MS)   # ~0,7 s de pausa encerra a frase
MIN_FALA = int(0.3 * 1000 / QUADRO_MS)       # frases mais curtas que isso: ignora
MAX_FALA = int(12 * 1000 / QUADRO_MS)        # corta a frase se passar de 12 s
PRE_ROLL = int(0.3 * 1000 / QUADRO_MS)       # guarda um tiquinho antes da fala


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
    return urls[0]


def carrega_modelo():
    """Tenta GPU; se falhar, usa CPU. Nao trava o teste de jeito nenhum."""
    from faster_whisper import WhisperModel
    try:
        modelo = WhisperModel(TAMANHO_MODELO, device="cuda", compute_type="int8")
        print("Whisper '{}' na GPU.".format(TAMANHO_MODELO))
        return modelo
    except Exception as erro:
        print("GPU nao disponivel ({}). Usando CPU (mais lento).".format(
            str(erro).splitlines()[0][:80]))
        modelo = WhisperModel(TAMANHO_MODELO, device="cpu", compute_type="int8")
        print("Whisper '{}' na CPU.".format(TAMANHO_MODELO))
        return modelo


def le_quadro(stream):
    """Le exatamente um quadro do ffmpeg (ou None se o audio acabou)."""
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


def transcreve(modelo, quadros):
    audio = np.frombuffer(b"".join(quadros), dtype=np.int16).astype(np.float32) / 32768.0
    segmentos, _ = modelo.transcribe(
        audio, language="pt", beam_size=1, condition_on_previous_text=False)
    partes = [s.text.strip() for s in segmentos if s.no_speech_prob < 0.6]
    return " ".join(p for p in partes if p).strip()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("O faster-whisper nao esta instalado. Rode:  pip install faster-whisper")
        sys.exit(1)

    cam = escolhe_camera(sys.argv[1] if len(sys.argv) > 1 else "")
    print("Camera: {} ({}) - {}".format(cam["cid"], cam["ip"], cam["nome"]))
    try:
        rtsp = url_rtsp(cam)
    except Exception as erro:
        print("Nao consegui o endereco de video da camera:", erro)
        sys.exit(1)

    print("Carregando o Whisper (na 1a vez baixa o modelo, ~460 MB)...")
    modelo = carrega_modelo()

    ffmpeg = acha_ffmpeg()
    comando = [
        ffmpeg, "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", rtsp,
        "-vn", "-ac", "1", "-ar", str(TAXA),
        "-f", "s16le", "-",
    ]
    proc = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Calibra o barulho de fundo por ~1,5 s para saber o que e "fala"
    print("Calibrando o silencio (fique quieto 1,5 s)...")
    amostras_fundo = []
    for _ in range(int(1.5 * 1000 / QUADRO_MS)):
        q = le_quadro(proc.stdout)
        if q is None:
            print("A camera nao mandou audio. Tente outra (ex.: python ouvir_whisper.py cam3).")
            erro = proc.stderr.read().decode("utf-8", "replace").strip()
            if erro:
                print("ffmpeg disse:", erro.splitlines()[-1])
            return
        amostras_fundo.append(rms(q))
    fundo = sorted(amostras_fundo)[len(amostras_fundo) // 2]   # mediana
    limiar = max(250.0, fundo * 2.5)
    print("Barulho de fundo ~{:.0f}, limiar de fala ~{:.0f}.".format(fundo, limiar))

    print("\n== Fale perto da camera. (Ctrl+C para parar) ==\n")
    pre = collections.deque(maxlen=PRE_ROLL)
    buffer_fala = []
    em_fala = False
    silencio = 0
    frames_falados = 0

    def fecha_frase():
        nonlocal buffer_fala, em_fala, silencio, frames_falados
        if frames_falados >= MIN_FALA:
            sys.stdout.write("\r" + " " * 40 + "\r")
            texto = transcreve(modelo, buffer_fala)
            if texto:
                print(">>", texto)
        buffer_fala = []
        em_fala = False
        silencio = 0
        frames_falados = 0

    try:
        while True:
            q = le_quadro(proc.stdout)
            if q is None:
                print("\nO audio parou de chegar.")
                erro = proc.stderr.read().decode("utf-8", "replace").strip()
                if erro:
                    print("ffmpeg disse:", erro.splitlines()[-1])
                break

            if rms(q) >= limiar:
                if not em_fala:
                    em_fala = True
                    buffer_fala = list(pre)   # inclui o pedacinho antes da fala
                buffer_fala.append(q)
                frames_falados += 1
                silencio = 0
                sys.stdout.write("\r  ... ouvindo")
                sys.stdout.flush()
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
