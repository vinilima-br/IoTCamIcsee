# -*- coding: utf-8 -*-
"""
biblioteca_sons.py  -  Pasta de sons (sons/) usada pela pagina.

- Aceita mp3, wav, ogg, m4a, aac, opus, flac, wma (ate 20 MB)
- Converte uma vez para G.711 A-law 8 kHz (o formato da camera) e guarda
  em sons/.cache/ - assim o som comeca a tocar na hora
- Valida o arquivo no envio (se o ffmpeg nao entende, recusa)
"""
import os
import re
import time
import unicodedata

import camera_xm

PASTA_SONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sons")
PASTA_CACHE = os.path.join(PASTA_SONS, ".cache")
EXTENSOES = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".opus", ".flac", ".wma"}
TAMANHO_MAX = 20 * 1024 * 1024


class ErroSom(Exception):
    pass


def _garante_pastas():
    os.makedirs(PASTA_CACHE, exist_ok=True)


def nome_seguro(nome):
    """'Alarme Família!.MP3' -> 'Alarme_Familia.mp3' (sem acento/caminho)."""
    nome = os.path.basename(nome.replace("\\", "/"))
    base, ext = os.path.splitext(nome)
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")[:60]
    if not base:
        base = "som_" + time.strftime("%Y%m%d_%H%M%S")
    return base + ext.lower()


def caminho(nome):
    nome = os.path.basename(nome)
    p = os.path.join(PASTA_SONS, nome)
    if not os.path.isfile(p) or os.path.splitext(nome)[1].lower() not in EXTENSOES:
        raise ErroSom("som nao encontrado: %s" % nome)
    return p


def _cache_de(nome):
    return os.path.join(PASTA_CACHE, nome + ".alaw")


def alaw_de(nome):
    """Bytes A-law prontos para a camera (usa/gera o cache)."""
    _garante_pastas()
    p = caminho(nome)
    c = _cache_de(nome)
    if os.path.isfile(c) and os.path.getmtime(c) >= os.path.getmtime(p):
        with open(c, "rb") as f:
            return f.read()
    alaw = camera_xm.arquivo_para_alaw(p)
    with open(c, "wb") as f:
        f.write(alaw)
    return alaw


def listar():
    _garante_pastas()
    sons = []
    for nome in os.listdir(PASTA_SONS):
        p = os.path.join(PASTA_SONS, nome)
        if not os.path.isfile(p) or os.path.splitext(nome)[1].lower() not in EXTENSOES:
            continue
        try:
            segundos = round(len(alaw_de(nome)) / 8000.0, 1)
        except Exception:
            segundos = None                   # arquivo que o ffmpeg nao entende
        sons.append({"nome": nome, "segundos": segundos,
                     "kb": round(os.path.getsize(p) / 1024), "mtime": os.path.getmtime(p)})
    sons.sort(key=lambda s: s["nome"].lower())
    return sons


def salvar_upload(nome_original, dados):
    if not dados:
        raise ErroSom("arquivo vazio")
    if len(dados) > TAMANHO_MAX:
        raise ErroSom("arquivo maior que 20 MB")
    nome = nome_seguro(nome_original)
    ext = os.path.splitext(nome)[1].lower()
    if ext not in EXTENSOES:
        raise ErroSom("formato nao aceito (%s). Use: %s" % (ext or "sem extensao",
                                                           ", ".join(sorted(EXTENSOES))))
    _garante_pastas()
    base, ext = os.path.splitext(nome)
    final = nome
    n = 2
    while os.path.exists(os.path.join(PASTA_SONS, final)):
        final = "%s_%d%s" % (base, n, ext)
        n += 1
    p = os.path.join(PASTA_SONS, final)
    with open(p, "wb") as f:
        f.write(dados)
    try:
        alaw = alaw_de(final)               # valida e ja deixa convertido
    except Exception as e:
        os.remove(p)
        raise ErroSom("o arquivo nao parece um audio valido: %s" % e)
    return {"nome": final, "segundos": round(len(alaw) / 8000.0, 1)}


def apagar(nome):
    p = caminho(nome)
    os.remove(p)
    c = _cache_de(os.path.basename(nome))
    if os.path.exists(c):
        os.remove(c)
