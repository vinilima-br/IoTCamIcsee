# =============================================================
#  gravador.py - Grava trechos do RTSP em arquivo, por evento
#
#  Usado pela IA: quando detecta uma pessoa, chama inicia();
#  quando a cena esvazia, chama para(). Em MP4 fragmentado - que
#  toca no navegador e continua tocável se for cortado no meio.
#  Vídeo H.264: só copia (sem gastar CPU). Vídeo H.265 (HEVC, comum
#  nas iCSee): converte para H.264 ao gravar - o navegador e o
#  player do Windows não tocam H.265 (só saía o som, tela preta).
#  O áudio G.711 da câmera vira AAC (encode leve) pra caber no mp4.
#
#  Cada gravação vira: <pasta>/AAAA-MM-DD/HH-MM-SS.mp4
# =============================================================

import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime

# H.265 -> H.264 ao gravar: rápido e leve (o stream gravado é o Leve)
RECODIFICA_H264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                   "-pix_fmt", "yuv420p", "-g", "30"]
_codecs = {}                 # url -> (codec, quando) - cache da sondagem
_CACHE_S = 600


def acha_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def codec_video(url, ffmpeg=None, timeout=12):
    """'h264', 'hevc', ... do vídeo da URL (ou None se não deu para ver). Fica em cache."""
    agora = time.time()
    if url in _codecs and agora - _codecs[url][1] < _CACHE_S:
        return _codecs[url][0]
    ffmpeg = ffmpeg or acha_ffmpeg()
    if not ffmpeg:
        return None
    cmd = [ffmpeg, "-hide_banner"]
    if url.startswith("rtsp"):
        cmd += ["-rtsp_transport", "tcp"]
    cmd += ["-i", url]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=timeout)
        txt = r.stderr.decode("utf-8", "ignore")
    except subprocess.TimeoutExpired as e:
        txt = (e.stderr or b"").decode("utf-8", "ignore")
    except Exception:
        return None
    m = re.search(r"Stream #\S+.*?: Video: (\w+)", txt)
    codec = m.group(1).lower() if m else None
    if codec:
        _codecs[url] = (codec, agora)
    return codec


class Gravador:
    """Controla um processo ffmpeg que grava o RTSP enquanto há evento.

    cid:          id da câmera (só pra log)
    pasta:        pasta base das gravações dessa câmera (gravacoes/<cid>)
    obtem_url:    função() -> URL RTSP a gravar (normalmente o stream leve)
    duracao_max_s: trava de segurança; a gravação nunca passa disso
                   mesmo que a IA esqueça de parar.
    """

    def __init__(self, cid, pasta, obtem_url, ffmpeg=None, duracao_max_s=300):
        self.cid = cid
        self.pasta = pasta
        self.obtem_url = obtem_url
        self.ffmpeg = ffmpeg or acha_ffmpeg()
        self.duracao_max_s = duracao_max_s
        self.proc = None
        self.arquivo_atual = None
        self.inicio = None
        self.erro = None
        self.trava = threading.Lock()

    def disponivel(self):
        return bool(self.ffmpeg)

    def gravando(self):
        with self.trava:
            return self.proc is not None and self.proc.poll() is None

    def _monta_cmd(self, url, saida, codec=None):
        video = ["-c:v", "copy"] if codec in (None, "h264") else list(RECODIFICA_H264)
        entrada = ["-rtsp_transport", "tcp"] if url.startswith("rtsp") else []
        return [self.ffmpeg, "-y", "-loglevel", "error"] + entrada + [
                "-fflags", "+genpts",
                "-i", url,
                "-t", str(self.duracao_max_s),
                "-map", "0:v:0", "-map", "0:a:0?"] + video + [
                "-c:a", "aac", "-b:a", "64k",
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4", saida]

    def inicia(self):
        """Começa a gravar, se já não estiver gravando."""
        # descobre o formato do vídeo ANTES da trava (pode levar uns segundos na 1a vez;
        # depois fica em cache) - assim a página não trava esperando o status
        if not self.gravando() and self.ffmpeg:
            try:
                url0 = self.obtem_url()
                if url0:
                    codec_video(url0, self.ffmpeg)
            except Exception:
                pass
        with self.trava:
            if self.proc is not None and self.proc.poll() is None:
                return True
            if not self.ffmpeg:
                self.erro = "ffmpeg não encontrado"
                return False
            url = None
            try:
                url = self.obtem_url()
            except Exception as erro:
                self.erro = "sem URL: {}".format(erro)
            if not url:
                self.erro = self.erro or "sem URL de vídeo"
                return False

            agora = datetime.now()
            pasta_dia = os.path.join(self.pasta, agora.strftime("%Y-%m-%d"))
            os.makedirs(pasta_dia, exist_ok=True)
            saida = os.path.join(pasta_dia, agora.strftime("%H-%M-%S") + ".mp4")
            n = 2
            while os.path.exists(saida):
                saida = os.path.join(pasta_dia, agora.strftime("%H-%M-%S") + "_{}.mp4".format(n))
                n += 1

            codec = codec_video(url, self.ffmpeg)
            if codec not in (None, "h264"):
                print("[grav:{}] vídeo em {} -> gravando em H.264 (toca no navegador e no Windows)"
                      .format(self.cid, codec.upper()))
            try:
                self.proc = subprocess.Popen(
                    self._monta_cmd(url, saida, codec),
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as erro:
                self.erro = "não iniciou o ffmpeg: {}".format(erro)
                self.proc = None
                return False

            self.arquivo_atual = saida
            self.inicio = time.time()
            self.erro = None
            print("[grav:{}] Iniciou: {}".format(self.cid, os.path.basename(saida)))
            return True

    def para(self):
        """Encerra a gravação com elegância (o mp4 fica tocável)."""
        with self.trava:
            p = self.proc
            if p is None:
                return
            if p.poll() is None:
                # 'q' faz o ffmpeg fechar o arquivo direitinho
                try:
                    p.stdin.write(b"q")
                    p.stdin.flush()
                except Exception:
                    pass
                try:
                    p.wait(timeout=5)
                except Exception:
                    try:
                        p.terminate()
                        p.wait(timeout=3)
                    except Exception:
                        try:
                            p.kill()
                        except Exception:
                            pass
            try:
                if p.stdin:
                    p.stdin.close()
            except Exception:
                pass
            dur = time.time() - self.inicio if self.inicio else 0
            print("[grav:{}] Parou: {} ({:.0f}s)".format(
                self.cid, os.path.basename(self.arquivo_atual or "?"), dur))
            self.proc = None
            self.arquivo_atual = None
            self.inicio = None

    def status(self):
        with self.trava:
            ativo = self.proc is not None and self.proc.poll() is None
            return {
                "disponivel": bool(self.ffmpeg),
                "gravando": ativo,
                "arquivo": os.path.basename(self.arquivo_atual) if ativo and self.arquivo_atual else None,
                "ha_segundos": round(time.time() - self.inicio) if ativo and self.inicio else 0,
                "erro": self.erro,
            }


def lista_gravacoes(pasta, limite=30):
    """Lista as gravações (mais recentes primeiro): [{'arquivo': 'dia/nome.mp4', ...}]."""
    itens = []
    if not os.path.isdir(pasta):
        return itens
    for dia in os.listdir(pasta):
        caminho_dia = os.path.join(pasta, dia)
        if not os.path.isdir(caminho_dia):
            continue
        for nome in os.listdir(caminho_dia):
            if nome.lower().endswith(".mp4"):
                caminho = os.path.join(caminho_dia, nome)
                try:
                    tam = os.path.getsize(caminho)
                    mtime = os.path.getmtime(caminho)
                except OSError:
                    continue
                itens.append((mtime, {
                    "arquivo": "{}/{}".format(dia, nome),
                    "dia": dia,
                    "hora": os.path.splitext(nome)[0],
                    "mb": round(tam / 1048576.0, 1),
                }))
    itens.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in itens[:limite]]
