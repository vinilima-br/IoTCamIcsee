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
#  Câmera de 2 lentes (iCSee X6S, quadro com as lentes empilhadas):
#  grava só a Lente 1 (metade de cima), só a Lente 2 (de baixo) ou as duas.
#
#  Cada gravação vira:
#    <pasta>/AAAA-MM-DD/<Camera>_AAAA-MM-DD_HH-MM-SS[_lente1|_lente2|_2lentes].mp4
#  (as antigas, HH-MM-SS.mp4, continuam aparecendo na lista)
# =============================================================

import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from datetime import datetime

# H.265 -> H.264 ao gravar: rápido e leve (o stream gravado é o Leve)
RECODIFICA_H264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                   "-pix_fmt", "yuv420p", "-g", "30"]
_codecs = {}                 # url -> ((codec, largura, altura), quando) - cache da sondagem
_CACHE_S = 600
LENTES = {"ambas": "2lentes", "cima": "lente1", "baixo": "lente2"}
ROTULO_LENTE = {"2lentes": "2 lentes", "lente1": "Lente 1", "lente2": "Lente 2"}
_RE_NOME = re.compile(r"^(?P<cam>.+)_(?P<dia>\d{4}-\d{2}-\d{2})_(?P<hora>\d{2}-\d{2}-\d{2})"
                      r"(?:_(?P<lente>lente1|lente2|2lentes))?(?:_\d+)?$")


def nome_arquivo_seguro(texto):
    """'Portão da Frente' -> 'Portao-da-Frente' (sem acento/espaço: vale em qualquer PC)."""
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9_-]+", "-", t).strip("-_")
    return t[:40] or "camera"


def duas_lentes(largura, altura):
    """Quadro mais alto que largo (ex.: 640x720, 2304x2592) = duas lentes empilhadas."""
    return bool(largura and altura and altura / float(largura) > 0.9)


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
    return info_video(url, ffmpeg, timeout)[0]


def info_video(url, ffmpeg=None, timeout=12):
    """(codec, largura, altura) do vídeo da URL; (None, 0, 0) se não deu para ver."""
    agora = time.time()
    if url in _codecs and agora - _codecs[url][1] < _CACHE_S:
        return _codecs[url][0]
    ffmpeg = ffmpeg or acha_ffmpeg()
    if not ffmpeg:
        return None, 0, 0
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
        return None, 0, 0
    m = re.search(r"Stream #\S+.*?: Video: (\w+)[^\n]*?, (\d{2,5})x(\d{2,5})", txt)
    if not m:
        m2 = re.search(r"Stream #\S+.*?: Video: (\w+)", txt)
        info = (m2.group(1).lower(), 0, 0) if m2 else (None, 0, 0)
    else:
        info = (m.group(1).lower(), int(m.group(2)), int(m.group(3)))
    if info[0]:
        _codecs[url] = (info, agora)
    return info


class Gravador:
    """Controla um processo ffmpeg que grava o RTSP enquanto há evento.

    cid:          id da câmera (só pra log)
    pasta:        pasta base das gravações dessa câmera (gravacoes/<cid>)
    obtem_url:    função() -> URL RTSP a gravar (normalmente o stream leve)
    duracao_max_s: trava de segurança; a gravação nunca passa disso
                   mesmo que a IA esqueça de parar.
    """

    def __init__(self, cid, pasta, obtem_url, ffmpeg=None, duracao_max_s=300, nome=None):
        self.cid = cid
        self.nome = nome or cid           # nome da câmera (vai no nome do arquivo)
        self.lente_atual = None           # lente da gravação em andamento
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

    def _monta_cmd(self, url, saida, codec=None, recorte=None):
        """recorte: None (quadro inteiro), "cima" (Lente 1) ou "baixo" (Lente 2)."""
        if recorte in ("cima", "baixo"):              # recortar = precisa recodificar
            y = "0" if recorte == "cima" else "trunc(ih/4)*2"
            video = ["-vf", "crop=iw:trunc(ih/4)*2:0:" + y] + list(RECODIFICA_H264)
        elif codec in (None, "h264"):
            video = ["-c:v", "copy"]
        else:
            video = list(RECODIFICA_H264)
        entrada = ["-rtsp_transport", "tcp"] if url.startswith("rtsp") else []
        return [self.ffmpeg, "-y", "-loglevel", "error"] + entrada + [
                "-fflags", "+genpts",
                "-i", url,
                "-t", str(self.duracao_max_s),
                "-map", "0:v:0", "-map", "0:a:0?"] + video + [
                "-c:a", "aac", "-b:a", "64k",
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4", saida]

    def inicia(self, lente="ambas"):
        """Começa a gravar, se já não estiver gravando.
        lente (câmera de 2 lentes): "ambas", "cima" (Lente 1) ou "baixo" (Lente 2)."""
        if lente not in LENTES:
            lente = "ambas"
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

            codec, larg, alt = info_video(url, self.ffmpeg)
            dupla = duas_lentes(larg, alt)
            recorte = lente if dupla and lente in ("cima", "baixo") else None

            agora = datetime.now()
            dia = agora.strftime("%Y-%m-%d")
            pasta_dia = os.path.join(self.pasta, dia)
            os.makedirs(pasta_dia, exist_ok=True)
            base = "{}_{}_{}".format(nome_arquivo_seguro(self.nome), dia, agora.strftime("%H-%M-%S"))
            if dupla:
                base += "_" + LENTES[lente]
            saida, n = os.path.join(pasta_dia, base + ".mp4"), 2
            while os.path.exists(saida):
                saida = os.path.join(pasta_dia, "{}_{}.mp4".format(base, n))
                n += 1

            if recorte:
                print("[grav:{}] gravando só a {}".format(self.cid, "Lente 1" if recorte == "cima" else "Lente 2"))
            elif codec not in (None, "h264"):
                print("[grav:{}] vídeo em {} -> gravando em H.264 (toca no navegador e no Windows)"
                      .format(self.cid, codec.upper()))
            try:
                self.proc = subprocess.Popen(
                    self._monta_cmd(url, saida, codec, recorte),
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as erro:
                self.erro = "não iniciou o ffmpeg: {}".format(erro)
                self.proc = None
                return False

            self.arquivo_atual = saida
            self.lente_atual = LENTES[lente] if dupla else None
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
            self.lente_atual = None
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
                base = os.path.splitext(nome)[0]
                m = _RE_NOME.match(base)
                lente = m.group("lente") if m else None
                itens.append((mtime, {
                    "arquivo": "{}/{}".format(dia, nome),
                    "nome": nome,
                    "dia": m.group("dia") if m else dia,
                    "hora": m.group("hora") if m else base,
                    "lente": ROTULO_LENTE.get(lente) if lente else None,
                    "mb": round(tam / 1048576.0, 1),
                }))
    itens.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in itens[:limite]]
