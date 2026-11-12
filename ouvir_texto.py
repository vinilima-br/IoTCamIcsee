# =============================================================
#  ouvir_texto.py  -  PASSO 1 do comando por voz
#
#  Pega o AUDIO de uma camera (pelo RTSP que o projeto ja usa) e
#  vai escrevendo no terminal, AO VIVO, o que voce fala na frente
#  dela. Nao aciona nada ainda - e so pra ver se a transcricao
#  sai decente com o microfone da camera.
#
#  Transcricao: Vosk (offline, roda na CPU, modelo em portugues).
#  Nao mexe na porta 34567, entao NAO corre risco de 205/bloqueio:
#  e so mais um "espectador" de RTSP, igual ao botao Ouvir da pagina.
#  Pode rodar com o servidor ligado.
#
#  Uso:
#     python ouvir_texto.py            (usa a cam2)
#     python ouvir_texto.py cam3       (escolhe pelo apelido)
#     python ouvir_texto.py 192.168.3.67   (ou direto pelo IP)
#
#  Primeira vez: baixa sozinho o modelo de voz (~40 MB) para modelos/.
#  Precisa do Vosk:  pip install vosk
# =============================================================

import json
import os
import subprocess
import sys
import urllib.request
import zipfile

import config

PASTA_BASE = os.path.dirname(os.path.abspath(__file__))

# Modelo pequeno de portugues do Vosk (rapido, bom o bastante pra teste).
# Depois da pra trocar pelo grande (mais preciso) sem mudar nada aqui.
MODELO_NOME = "vosk-model-small-pt-0.3"
MODELO_URL = "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"
MODELO_PASTA = os.path.join(PASTA_BASE, "modelos", MODELO_NOME)

TAXA = 16000   # o modelo trabalha em 16 kHz mono


def acha_ffmpeg():
    """Usa o ffmpeg que vem com o imageio-ffmpeg (ja esta no projeto).
    Se nao achar, tenta o 'ffmpeg' do sistema."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def escolhe_camera(argumento):
    """Devolve o dicionario da camera pedida (por cid ou por IP).
    Sem argumento, pega a cam2 (ou a primeira iCSee que existir)."""
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
    """Monta/descobre a URL RTSP (com audio) da camera."""
    if cam["tipo"] == "elsys":
        # Elsys: RTSP direto, credenciais no caminho. stream 0 = alta (tem audio).
        return "rtsp://{ip}:{porta}/user={u}_password={s}_channel=1_stream=0.sdp".format(
            ip=cam["ip"], porta=cam.get("porta", 554),
            u=cam.get("usuario", "admin"), s=cam.get("senha", ""))
    # iCSee: a URL vem do ONVIF (mesmo jeito do resto do projeto).
    import onvif_rtsp
    urls = onvif_rtsp.descobre_urls(cam["ip"], cam["usuario"], cam["senha"],
                                    cam.get("porta_onvif") or None)
    # A 1a costuma ser a de alta resolucao - e a que carrega o audio.
    return urls[0]


def garante_modelo():
    """Baixa e descompacta o modelo de voz na primeira vez."""
    if os.path.isdir(MODELO_PASTA):
        return
    destino_zip = MODELO_PASTA + ".zip"
    pasta_modelos = os.path.join(PASTA_BASE, "modelos")
    os.makedirs(pasta_modelos, exist_ok=True)
    print("Baixando o modelo de voz (so na primeira vez, ~40 MB)...")
    try:
        def _progresso(blocos, tam_bloco, total):
            if total > 0:
                pct = min(100, blocos * tam_bloco * 100 // total)
                sys.stdout.write("\r  {}%".format(pct))
                sys.stdout.flush()
        urllib.request.urlretrieve(MODELO_URL, destino_zip, _progresso)
        print("\r  100%  -  descompactando...")
        with zipfile.ZipFile(destino_zip) as z:
            z.extractall(pasta_modelos)
        os.remove(destino_zip)
        print("Modelo pronto em modelos/{}".format(MODELO_NOME))
    except Exception as erro:
        print("\nNao consegui baixar o modelo automaticamente:", erro)
        print("Baixe a mao em: {}".format(MODELO_URL))
        print("e descompacte dentro da pasta 'modelos' (fica modelos/{}).".format(MODELO_NOME))
        sys.exit(1)


def main():
    # 1) Vosk instalado?
    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
    except ImportError:
        print("O Vosk nao esta instalado. Rode:  pip install vosk")
        sys.exit(1)
    SetLogLevel(-1)   # silencia os logs internos do Vosk

    # 2) Camera e RTSP
    cam = escolhe_camera(sys.argv[1] if len(sys.argv) > 1 else "")
    print("Camera: {} ({}) - {}".format(cam["cid"], cam["ip"], cam["nome"]))
    try:
        rtsp = url_rtsp(cam)
    except Exception as erro:
        print("Nao consegui o endereco de video da camera:", erro)
        sys.exit(1)

    # 3) Modelo de voz
    garante_modelo()
    modelo = Model(MODELO_PASTA)
    reconhecedor = KaldiRecognizer(modelo, TAXA)

    # 4) ffmpeg puxando SO o audio, em 16 kHz mono PCM
    ffmpeg = acha_ffmpeg()
    comando = [
        ffmpeg, "-nostdin", "-loglevel", "error",
        "-rtsp_transport", "tcp", "-i", rtsp,
        "-vn",                       # descarta o video
        "-ac", "1", "-ar", str(TAXA),
        "-f", "s16le", "-",          # PCM cru na saida
    ]
    proc = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    print("\n== Fale perto da camera. (Ctrl+C para parar) ==\n")
    ultima_parcial = ""
    try:
        while True:
            dados = proc.stdout.read(4000)
            if not dados:
                # ffmpeg fechou - provavelmente a camera nao mandou audio
                erro = proc.stderr.read().decode("utf-8", "replace").strip()
                print("\nO audio parou de chegar.")
                if erro:
                    print("ffmpeg disse:", erro.splitlines()[-1])
                print("Dica: tente outra camera (ex.: python ouvir_texto.py cam3) "
                      "ou confira se essa camera tem microfone ligado.")
                break

            if reconhecedor.AcceptWaveform(dados):
                texto = json.loads(reconhecedor.Result()).get("text", "").strip()
                if texto:
                    # limpa a linha parcial e imprime a frase fechada
                    sys.stdout.write("\r" + " " * (len(ultima_parcial) + 8) + "\r")
                    print(">>", texto)
                    ultima_parcial = ""
            else:
                parcial = json.loads(reconhecedor.PartialResult()).get("partial", "").strip()
                if parcial and parcial != ultima_parcial:
                    sys.stdout.write("\r  ... " + parcial + " " * 4)
                    sys.stdout.flush()
                    ultima_parcial = parcial
    except KeyboardInterrupt:
        print("\n\nParando.")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()
