# -*- coding: utf-8 -*-
"""
Teste de vozes do ElevenLabs (rodada 3).

So GERA arquivos para ouvir no PC. Nao mexe no servidor nem nas cameras.
Nao precisa instalar nada (usa so a biblioteca padrao do Python + ffmpeg).

Antes:
  1. Crie a conta em https://elevenlabs.io (plano gratis: 10 mil creditos/mes).
  2. Crie a chave em https://elevenlabs.io/app/settings/api-keys
     (permissoes: "Text to Speech" e "Voices" com leitura).
  3. Coloque no config.py:
        ELEVENLABS_API_KEY = "sk_..."

Uso (dentro da pasta do projeto):
    python ferramentas\\teste_elevenlabs.py               (todas as vozes da conta)
    python ferramentas\\teste_elevenlabs.py --max=5       (so as 5 primeiras)
    python ferramentas\\teste_elevenlabs.py --so-minhas   (so as que voce adicionou
                                                           da Voice Library)
    python ferramentas\\teste_elevenlabs.py --modelo=eleven_multilingual_v2

Resultado em vozes_teste3\\ :
    *.mp3          -> qualidade cheia
    *_camera.wav   -> 8 kHz mono, faixa de telefone (como sai na camera)

Modelo padrao: eleven_v3, o mais expressivo. Ele entende "tags" de emocao
entre colchetes no texto, ex.: [whispers] [sighs] [laughs softly] [warmly].
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_SAIDA = os.path.join(PASTA_PROJETO, "vozes_teste3")
sys.path.insert(0, PASTA_PROJETO)

API = "https://api.elevenlabs.io/v1"

FRASE_V3 = ("[warmly] Oi... que bom que você chegou. "
            "[whispers] Fica à vontade... já vou te atender.")
FRASE_SEM_TAGS = "Oi... que bom que você chegou. Fica à vontade, já vou te atender."


def chave_api():
    k = os.environ.get("ELEVENLABS_API_KEY", "")
    if not k:
        try:
            import config
            k = getattr(config, "ELEVENLABS_API_KEY", "")
        except Exception:
            pass
    return (k or "").strip()


def pedir(metodo, caminho, chave, corpo=None, aceita="application/json"):
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(API + caminho, data=dados, method=metodo, headers={
        "xi-api-key": chave, "Content-Type": "application/json", "Accept": aceita})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def detalhe_erro(corpo):
    try:
        d = json.loads(corpo.decode("utf-8", "replace")).get("detail", "")
        if isinstance(d, dict):
            return "%s: %s" % (d.get("status", ""), d.get("message", ""))
        return str(d)
    except Exception:
        return corpo[:200].decode("utf-8", "replace")


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


def nome_arquivo(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_")[:40] or "voz"


def main():
    args = sys.argv[1:]
    maximo = None
    so_minhas = "--so-minhas" in args
    modelo = "eleven_v3"
    for a in args:
        if a.startswith("--max="):
            maximo = int(a.split("=", 1)[1])
        elif a.startswith("--modelo="):
            modelo = a.split("=", 1)[1].strip()
    frase = FRASE_V3 if modelo == "eleven_v3" else FRASE_SEM_TAGS

    chave = chave_api()
    if not chave:
        print("Falta a chave: coloque ELEVENLABS_API_KEY = \"sk_...\" no config.py")
        return

    print("Buscando as vozes da sua conta...")
    st, corpo = pedir("GET", "/voices", chave)
    if st != 200:
        print("Erro %d ao listar vozes: %s" % (st, detalhe_erro(corpo)))
        if st == 401:
            print("-> chave errada, ou falta a permissao 'Voices' (leitura) na chave.")
        return
    vozes = json.loads(corpo.decode("utf-8")).get("voices", [])
    if so_minhas:
        vozes = [v for v in vozes if v.get("category") != "premade"]
    # as que voce adicionou primeiro, depois as prontas
    vozes.sort(key=lambda v: (v.get("category") == "premade", v.get("name", "")))
    if maximo:
        vozes = vozes[:maximo]
    if not vozes:
        print("Nenhuma voz para testar.")
        return

    custo = len(frase) * len(vozes)
    print("\nModelo: %s" % modelo)
    print("Frase:  %s" % frase)
    print("Vozes:  %d  ->  gasto aproximado: %d creditos (o gratis da 10.000/mes)"
          % (len(vozes), custo))
    if input("Continuar? (s/n) ").strip().lower() != "s":
        return

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    ffmpeg = achar_ffmpeg()
    if not ffmpeg:
        print("ffmpeg nao encontrado: so MP3 (pip install imageio-ffmpeg).")

    gerados = 0
    for n, v in enumerate(vozes, start=1):
        rot = v.get("labels") or {}
        info = ", ".join(x for x in (rot.get("gender"), rot.get("age"), rot.get("accent"),
                                     rot.get("description") or rot.get("descriptive"),
                                     rot.get("use_case")) if x)
        tipo = "sua" if v.get("category") != "premade" else "pronta"
        print("\n%02d %s  [%s]  %s" % (n, v.get("name"), tipo, info))
        print("    id: %s" % v.get("voice_id"))

        st, audio = pedir("POST", "/text-to-speech/%s?output_format=mp3_44100_128"
                          % v["voice_id"], chave,
                          {"text": frase, "model_id": modelo}, aceita="audio/mpeg")
        if st != 200:
            msg = detalhe_erro(audio)
            print("    [falhou] erro %d: %s" % (st, msg))
            if st == 401 or "quota" in msg.lower() or "credits" in msg.lower():
                print("    -> parei (chave/permissao ou creditos acabaram).")
                break
            continue

        base = "%02d_%s_%s" % (n, nome_arquivo(v.get("name", "")), nome_arquivo(rot.get("gender", "")))
        mp3 = os.path.join(PASTA_SAIDA, base + ".mp3")
        with open(mp3, "wb") as f:
            f.write(audio)
        if ffmpeg:
            versao_camera(ffmpeg, mp3, os.path.join(PASTA_SAIDA, base + "_camera.wav"))
        print("    ok")
        gerados += 1

    print("\nPronto: %d vozes em %s" % (gerados, PASTA_SAIDA))
    if os.name == "nt" and gerados:
        os.startfile(PASTA_SAIDA)


if __name__ == "__main__":
    main()
