# -*- coding: utf-8 -*-
"""
Teste de vozes do edge-tts (vozes neurais da Microsoft, pt-BR).

So GERA arquivos de audio para voce ouvir no PC. Nao mexe no servidor
nem fala com nenhuma camera (pode rodar com o servidor ligado).

Uso (dentro da pasta do projeto):
    pip install edge-tts
    python ferramentas\\teste_vozes_edge.py

Resultado na pasta vozes_teste\\ :
    *.mp3          -> a voz em qualidade cheia
    *_camera.wav   -> a mesma voz em 8 kHz mono, faixa de telefone
                      (aproximadamente como sai no alto-falante da camera)
"""

import asyncio
import os
import shutil
import subprocess
import sys

try:
    import edge_tts
except ImportError:
    print("Falta instalar: pip install edge-tts")
    sys.exit(1)

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_SAIDA = os.path.join(PASTA_PROJETO, "vozes_teste")

FRASES = [
    ("boas-vindas", "Olá! Seja bem-vindo. Já vamos atender você."),
    ("aviso", "Atenção: esta área está sendo monitorada e gravada."),
    ("portao", "Por favor, aguarde no portão. Alguém já está vindo."),
]


def achar_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def versao_camera(ffmpeg, mp3, wav):
    """8 kHz, mono, corta graves e agudos como o G.711 da camera."""
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", mp3,
           "-af", "highpass=f=300,lowpass=f=3400",
           "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le", wav]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0


async def main():
    os.makedirs(PASTA_SAIDA, exist_ok=True)

    print("Buscando as vozes pt-BR disponiveis...")
    try:
        todas = await edge_tts.list_voices()
    except Exception as e:
        print("Nao consegui falar com o servico da Microsoft (precisa de internet).")
        print("Erro:", e)
        return

    vozes = sorted(
        (v for v in todas if v.get("Locale") == "pt-BR"),
        key=lambda v: v["ShortName"],
    )
    if not vozes:
        print("Nenhuma voz pt-BR encontrada.")
        return

    for v in vozes:
        print("  -", v["ShortName"], "(" + v.get("Gender", "?") + ")")

    ffmpeg = achar_ffmpeg()
    if not ffmpeg:
        print("ffmpeg nao encontrado: vou gerar so os MP3 (pip install imageio-ffmpeg).")

    gerados = 0
    for n, v in enumerate(vozes, start=1):
        nome_voz = v["ShortName"].replace("pt-BR-", "").replace("Neural", "")
        for chave, texto in FRASES:
            base = "%02d_%s_%s" % (n, nome_voz, chave)
            mp3 = os.path.join(PASTA_SAIDA, base + ".mp3")
            try:
                await edge_tts.Communicate(texto, v["ShortName"]).save(mp3)
            except Exception as e:
                print("  [falhou]", base, "->", e)
                continue
            linha = "  ok  " + base + ".mp3"
            if ffmpeg:
                wav = os.path.join(PASTA_SAIDA, base + "_camera.wav")
                if versao_camera(ffmpeg, mp3, wav):
                    linha += "  +  _camera.wav"
            print(linha)
            gerados += 1

    print()
    print("Pronto: %d frases geradas em %s" % (gerados, PASTA_SAIDA))
    if os.name == "nt" and gerados:
        os.startfile(PASTA_SAIDA)  # abre a pasta no Explorer


if __name__ == "__main__":
    asyncio.run(main())
