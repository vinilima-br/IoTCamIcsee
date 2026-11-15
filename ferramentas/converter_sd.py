# -*- coding: utf-8 -*-
"""
ferramentas/converter_sd.py  -  Converte de novo um arquivo .h264 do cartao SD
                                (ja baixado) em .mp4, sem baixar outra vez.

Uso (na pasta do projeto):
   python ferramentas\\converter_sd.py sd_baixados\\2026-11-09_11-07-14_R.h264
   python ferramentas\\converter_sd.py sd_baixados          (todos os .h264 da pasta)
"""
import glob
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # pasta do projeto
sys.path.insert(0, os.path.join(_RAIZ, "app"))                       # o codigo fica em app/
sys.path.append(_RAIZ)                                               # config.py
import sd_xm  # noqa: E402


def converte(bruto):
    mp4 = os.path.splitext(bruto)[0] + ".mp4"
    try:
        info = sd_xm.para_mp4(bruto, mp4)
    except Exception as e:
        print("  [X] %s: %s" % (os.path.basename(bruto), e))
        return
    print("  [OK] %s  ->  %dx%d, %s fps, %s s, audio: %s%s" % (
        os.path.basename(mp4), info["largura"], info["altura"], info["fps"], info["duracao_s"],
        "sim" if info["com_audio"] else ("NAO ENTROU" if info.get("audio_no_cartao") else "nao gravado"),
        ", %d bytes recuperados" % info["bytes_recuperados"] if info.get("bytes_recuperados") else ""))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    alvo = sys.argv[1]
    arquivos = sorted(glob.glob(os.path.join(alvo, "*.h264"))) if os.path.isdir(alvo) else [alvo]
    exe, ver = sd_xm.versao_ffmpeg()
    print("ffmpeg: %s" % ver)
    for a in arquivos:
        converte(a)


if __name__ == "__main__":
    main()
