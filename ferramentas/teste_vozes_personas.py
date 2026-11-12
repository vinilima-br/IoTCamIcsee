# -*- coding: utf-8 -*-
"""
Teste de "personas" de voz (edge-tts) - rodada 2.

Mistura vozes pt-BR com ajustes de velocidade/tom e vozes MULTILINGUAIS
(americanas, francesa, alema...) falando portugues, com sotaque leve.

So GERA arquivos para ouvir no PC. Nao mexe no servidor nem nas cameras.

Uso (dentro da pasta do projeto):
    python ferramentas\\teste_vozes_personas.py

Resultado em vozes_teste2\\ :
    *.mp3          -> qualidade cheia
    *_camera.wav   -> 8 kHz mono, faixa de telefone (como sai na camera)
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
PASTA_SAIDA = os.path.join(PASTA_PROJETO, "vozes_teste2")

# (apelido, voz, velocidade, tom, descricao)
PERSONAS = [
    # --- femininas ---
    ("Francisca_Veludo",   "pt-BR-FranciscaNeural",          "-12%", "-6Hz", "Francisca mais lenta e grave, macia"),
    ("Francisca_Animada",  "pt-BR-FranciscaNeural",          "+8%",  "+4Hz", "Francisca simpatica, recepcionista"),
    ("Thalita",            "pt-BR-ThalitaMultilingualNeural", "+0%", "+0Hz", "Thalita natural, jovem"),
    ("Thalita_Sussurro",   "pt-BR-ThalitaMultilingualNeural", "-15%", "-5Hz", "Thalita lenta e baixa, intimista"),
    ("Ava_Sotaque",        "en-US-AvaMultilingualNeural",    "-5%",  "+0Hz", "Ava (EUA) - voz quente, sotaque leve"),
    ("Emma_Sotaque",       "en-US-EmmaMultilingualNeural",   "-5%",  "+0Hz", "Emma (EUA) - doce e clara"),
    ("Vivienne_Francesa",  "fr-FR-VivienneMultilingualNeural", "-8%", "-2Hz", "Vivienne (Franca) - charme frances"),
    ("Seraphina_Alema",    "de-DE-SeraphinaMultilingualNeural", "-8%", "-3Hz", "Seraphina (Alemanha) - elegante, seria"),
    # --- masculinas ---
    ("Antonio_Locutor",    "pt-BR-AntonioNeural",            "-10%", "-8Hz", "Antonio grave, voz de locutor"),
    ("Antonio_Mordomo",    "pt-BR-AntonioNeural",            "-6%",  "-3Hz", "Antonio calmo e educado"),
    ("Andrew_Sotaque",     "en-US-AndrewMultilingualNeural", "-5%",  "-2Hz", "Andrew (EUA) - quente, confiante"),
    ("Brian_Sotaque",      "en-US-BrianMultilingualNeural",  "-5%",  "+0Hz", "Brian (EUA) - descontraido"),
    ("Remy_Frances",       "fr-FR-RemyMultilingualNeural",   "-8%",  "-3Hz", "Remy (Franca) - galanteador"),
    ("Giuseppe_Italiano",  "it-IT-GiuseppeMultilingualNeural", "-5%", "+0Hz", "Giuseppe (Italia) - expansivo"),
]

FRASES = [
    ("chegada", "Oi... que bom que você chegou. Fica à vontade, já vou te atender."),
    ("aviso", "Atenção: esta área está sendo monitorada e gravada."),
]


def achar_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def versao_camera(ffmpeg, mp3, wav):
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", mp3,
           "-af", "highpass=f=300,lowpass=f=3400",
           "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le", wav]
    return subprocess.run(cmd, capture_output=True).returncode == 0


async def main():
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    print("Conferindo quais vozes existem no servico...")
    try:
        existentes = {v["ShortName"] for v in await edge_tts.list_voices()}
    except Exception as e:
        print("Sem acesso ao servico da Microsoft (precisa de internet):", e)
        return

    ffmpeg = achar_ffmpeg()
    if not ffmpeg:
        print("ffmpeg nao encontrado: so MP3 (pip install imageio-ffmpeg).")

    gerados = 0
    for n, (apelido, voz, vel, tom, desc) in enumerate(PERSONAS, start=1):
        print("\n%02d %-20s %s" % (n, apelido, desc))
        if voz not in existentes:
            print("    [pulei] a voz %s nao existe no servico" % voz)
            continue
        for chave, texto in FRASES:
            base = "%02d_%s_%s" % (n, apelido, chave)
            mp3 = os.path.join(PASTA_SAIDA, base + ".mp3")
            try:
                await edge_tts.Communicate(texto, voz, rate=vel, pitch=tom).save(mp3)
            except Exception as e:
                print("    [falhou]", chave, "->", e)
                continue
            if ffmpeg:
                versao_camera(ffmpeg, mp3, os.path.join(PASTA_SAIDA, base + "_camera.wav"))
            print("    ok", chave)
            gerados += 1

    print("\nPronto: %d frases em %s" % (gerados, PASTA_SAIDA))
    if os.name == "nt" and gerados:
        os.startfile(PASTA_SAIDA)


if __name__ == "__main__":
    asyncio.run(main())
