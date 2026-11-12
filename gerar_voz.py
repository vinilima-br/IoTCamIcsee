# -*- coding: utf-8 -*-
"""
gerar_voz.py  -  Transforma um TEXTO em audio falado, pronto para tocar na camera.

Vozes (escolhidas no painel):
  - ElevenLabs (Adam, Alice, Bella, Bill...): as mais expressivas. Precisa de
    internet e de ELEVENLABS_API_KEY no config.py. Gasta creditos da conta,
    mas cada frase fica guardada em cache\\tts_eleven\\ (repetir nao gasta).
    O modelo eleven_v3 entende tags de emocao no texto:
        [whispers] [sighs] [laughs softly] [warmly] [excited] ...
  - edge-tts (Francisca, Antonio): vozes neurais da Microsoft, gratis, internet.
  - Windows: voz do proprio Windows, offline.

Se a voz escolhida falhar, cai para a Francisca e, sem internet, para o Windows.

config.py (tudo opcional, menos a chave para usar o ElevenLabs):
    ELEVENLABS_API_KEY = "sk_..."
    ELEVENLABS_VOZES = ["Adam", "Alice", "Bella", "Bill"]   # nomes como no site
    ELEVENLABS_MODELO = "eleven_v3"
    VOZ_EDGE = "pt-BR-FranciscaNeural"   # voz padrao (falas automaticas, rostos)

Gera WAV 8 kHz mono 16 bits - o formato que a camera usa.

Uso:
   python gerar_voz.py "Atencao, voce esta sendo filmado"
   python gerar_voz.py "Saia da area" sons\\saia.wav
   python gerar_voz.py "[whispers] Oi..." --voz=bella
   python gerar_voz.py vozes            (lista as vozes disponiveis)
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

PASTA = os.path.dirname(os.path.abspath(__file__))

VOZ_EDGE_PADRAO = "pt-BR-FranciscaNeural"
TEMPO_MAX_EDGE = 20  # segundos; passou disso, usa a voz do Windows

ELEVEN_API = "https://api.elevenlabs.io/v1"
ELEVEN_VOZES_PADRAO = ["Adam", "Alice", "Bella", "Bill"]
ELEVEN_MODELO_PADRAO = "eleven_v3"
PASTA_CACHE_ELEVEN = os.path.join(PASTA, "cache", "tts_eleven")
ARQ_IDS_ELEVEN = os.path.join(PASTA, "elevenlabs_vozes.json")

# Vozes fixas (id do painel -> (tipo, voz, nome bonito))
VOZES_FIXAS = [
    ("francisca", "edge", "pt-BR-FranciscaNeural", "Francisca"),
    ("antonio", "edge", "pt-BR-AntonioNeural", "Antônio"),
    ("windows", "windows", "", "Windows (offline)"),
]
# compatibilidade com quem importava VOZES
VOZES = {i: v for i, t, v, _ in VOZES_FIXAS}


class ErroVoz(Exception):
    pass


def _config(nome, padrao):
    try:
        import config
        return getattr(config, nome, padrao)
    except Exception:
        return padrao


def voz_edge_escolhida():
    return _config("VOZ_EDGE", VOZ_EDGE_PADRAO)


def _chave_eleven():
    return (os.environ.get("ELEVENLABS_API_KEY") or _config("ELEVENLABS_API_KEY", "") or "").strip()


def _vozes_eleven():
    return list(_config("ELEVENLABS_VOZES", ELEVEN_VOZES_PADRAO) or [])


def lista_vozes():
    """Para o painel: [{"id": "...", "nome": "..."}]. ElevenLabs so com chave."""
    lista = [{"id": i, "nome": n} for i, t, v, n in VOZES_FIXAS[:2]]
    if _chave_eleven():
        for nome in _vozes_eleven():
            lista.append({"id": "eleven:" + nome.lower(), "nome": nome + " (ElevenLabs)"})
    lista.append({"id": "windows", "nome": "Windows (offline)"})
    return lista


def resolve_voz(voz):
    """Retorna (tipo, voz). tipo = "edge" | "eleven" | "windows".
    Aceita: None/"" (padrao), "francisca", "antonio", "windows",
            "eleven:adam", "adam" (se estiver em ELEVENLABS_VOZES), "pt-BR-XxxNeural"."""
    if voz is None or str(voz).strip() == "":
        padrao = voz_edge_escolhida()
        return ("edge", padrao) if padrao else ("windows", "")
    v = str(voz).strip()
    for i, tipo, nome_voz, _ in VOZES_FIXAS:
        if v.lower() == i:
            return tipo, nome_voz
    if v.lower().startswith("eleven:"):
        pedido = v.split(":", 1)[1].strip()
        for nome in _vozes_eleven():
            if pedido.lower() == nome.lower():
                return "eleven", nome
        return "eleven", pedido
    for nome in _vozes_eleven():
        if v.lower() == nome.lower():
            return "eleven", nome
    if v.endswith("Neural"):
        return "edge", v
    raise ErroVoz("voz desconhecida: %s" % v)


# ------------------------------------------------------------------
#  Voz do Windows (reserva)
# ------------------------------------------------------------------
PS_LISTA = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
foreach ($v in $s.GetInstalledVoices()) {
  $i = $v.VoiceInfo
  Write-Output ("  {0}  ({1}, {2})" -f $i.Name, $i.Culture.Name, $i.Gender)
}
$s.Dispose()
"""

PS_FALA = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$texto = [System.IO.File]::ReadAllText($env:VOZ_TEXTO, [System.Text.Encoding]::UTF8)
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$pt = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'pt*' } | Select-Object -First 1
if ($pt) { $s.SelectVoice($pt.VoiceInfo.Name) }
Write-Output ("VOZ: " + $s.Voice.Name + " (" + $s.Voice.Culture.Name + ")")
$s.Rate = [int]$env:VOZ_VELOCIDADE
$s.Volume = 100
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(8000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($env:VOZ_SAIDA, $fmt)
$s.Speak($texto)
$s.SetOutputToNull()
$s.Dispose()
"""


def roda_ps(script, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, env=env)


def _gerar_windows(texto, saida, velocidade=0):
    if os.name != "nt":
        raise ErroVoz("a voz do Windows so funciona no mini PC")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt",
                                     delete=False) as f:
        f.write(texto)
        arq_texto = f.name
    try:
        r = roda_ps(PS_FALA, {"VOZ_TEXTO": arq_texto, "VOZ_SAIDA": saida,
                              "VOZ_VELOCIDADE": str(int(velocidade))})
    finally:
        os.unlink(arq_texto)
    if r.returncode != 0 or not os.path.isfile(saida):
        raise ErroVoz("falhou ao gerar a voz: %s" % (r.stderr or r.stdout)[-300:].strip())
    voz = ""
    for linha in (r.stdout or "").splitlines():
        if linha.startswith("VOZ:"):
            voz = linha[4:].strip()
    return voz + " [Windows]"


# ------------------------------------------------------------------
#  Conversao MP3 -> WAV 8 kHz
# ------------------------------------------------------------------
def _acha_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _mp3_para_wav8k(mp3, saida):
    ffmpeg = _acha_ffmpeg()
    if not ffmpeg:
        raise ErroVoz("ffmpeg nao encontrado (pip install imageio-ffmpeg)")
    r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", mp3,
                        "-ar", "8000", "-ac", "1", "-c:a", "pcm_s16le", saida],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(saida):
        raise ErroVoz("ffmpeg falhou: %s" % (r.stderr or "")[-200:].strip())


def _sem_tags(texto):
    """Tira as tags [whispers] etc. (so o ElevenLabs v3 entende)."""
    return re.sub(r"\s+", " ", re.sub(r"\[[^\]]{1,40}\]", " ", texto)).strip()


# ------------------------------------------------------------------
#  Voz edge-tts
# ------------------------------------------------------------------
def _gerar_edge(texto, saida, voz, velocidade=0):
    import edge_tts  # se nao estiver instalado, cai na voz do Windows

    vel = max(-10, min(10, int(velocidade)))
    taxa = "%+d%%" % (vel * 10)
    fd, mp3 = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        async def _fala():
            await edge_tts.Communicate(texto, voz, rate=taxa).save(mp3)
        asyncio.run(asyncio.wait_for(_fala(), TEMPO_MAX_EDGE))
        if os.path.getsize(mp3) == 0:
            raise ErroVoz("edge-tts nao devolveu audio")
        _mp3_para_wav8k(mp3, saida)
    finally:
        try:
            os.unlink(mp3)
        except OSError:
            pass
    return voz.replace("pt-BR-", "").replace("Neural", "") + " [edge-tts]"


# ------------------------------------------------------------------
#  Voz ElevenLabs
# ------------------------------------------------------------------
_trava_ids = threading.Lock()
_ids_eleven = None  # nome em minusculas -> voice_id


def _eleven_pedir(metodo, caminho, corpo=None, aceita="application/json"):
    chave = _chave_eleven()
    if not chave:
        raise ErroVoz("falta ELEVENLABS_API_KEY no config.py")
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(ELEVEN_API + caminho, data=dados, method=metodo, headers={
        "xi-api-key": chave, "Content-Type": "application/json", "Accept": aceita})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        corpo_erro = e.read()
        try:
            d = json.loads(corpo_erro.decode("utf-8", "replace")).get("detail", "")
            msg = d.get("message", "") if isinstance(d, dict) else str(d)
        except Exception:
            msg = corpo_erro[:150].decode("utf-8", "replace")
        raise ErroVoz("ElevenLabs erro %d: %s" % (e.code, msg))
    except urllib.error.URLError as e:
        raise ErroVoz("sem conexao com o ElevenLabs (%s)" % e.reason)


def _nome_curto(nome):
    """'Adam - Dominant, Firm' -> 'adam'"""
    return nome.split(" - ")[0].strip().lower()


def _id_eleven(nome):
    """Acha o voice_id pelo nome (consulta a conta 1 vez e guarda em arquivo)."""
    global _ids_eleven
    alvo = nome.strip().lower()
    with _trava_ids:
        if _ids_eleven is None:
            try:
                with open(ARQ_IDS_ELEVEN, encoding="utf-8") as f:
                    _ids_eleven = json.load(f)
            except Exception:
                _ids_eleven = {}
        if alvo not in _ids_eleven:
            vozes = json.loads(_eleven_pedir("GET", "/voices").decode("utf-8")).get("voices", [])
            for v in vozes:
                _ids_eleven.setdefault(_nome_curto(v.get("name", "")), v["voice_id"])
                _ids_eleven.setdefault(v.get("name", "").strip().lower(), v["voice_id"])
            try:
                with open(ARQ_IDS_ELEVEN, "w", encoding="utf-8") as f:
                    json.dump(_ids_eleven, f, indent=1, ensure_ascii=False)
            except OSError:
                pass
        if alvo not in _ids_eleven:
            raise ErroVoz("voz '%s' nao existe na sua conta do ElevenLabs" % nome)
        return _ids_eleven[alvo]


def _gerar_eleven(texto, saida, nome):
    modelo = _config("ELEVENLABS_MODELO", ELEVEN_MODELO_PADRAO) or ELEVEN_MODELO_PADRAO
    if modelo != "eleven_v3":
        texto = _sem_tags(texto)
    voice_id = _id_eleven(nome)

    # cache: mesma voz + modelo + texto -> nao gasta credito de novo
    os.makedirs(PASTA_CACHE_ELEVEN, exist_ok=True)
    h = hashlib.sha1(("%s|%s|%s" % (voice_id, modelo, texto)).encode("utf-8")).hexdigest()[:20]
    em_cache = os.path.join(PASTA_CACHE_ELEVEN, h + ".wav")
    rotulo = nome + " [ElevenLabs]"
    if os.path.isfile(em_cache) and os.path.getsize(em_cache) > 44:
        shutil.copyfile(em_cache, saida)
        return rotulo + " (cache)"

    audio = _eleven_pedir("POST", "/text-to-speech/%s?output_format=mp3_44100_128" % voice_id,
                          {"text": texto, "model_id": modelo}, aceita="audio/mpeg")
    if not audio:
        raise ErroVoz("ElevenLabs nao devolveu audio")
    fd, mp3 = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        with open(mp3, "wb") as f:
            f.write(audio)
        _mp3_para_wav8k(mp3, em_cache)
    finally:
        try:
            os.unlink(mp3)
        except OSError:
            pass
    shutil.copyfile(em_cache, saida)
    return rotulo


# ------------------------------------------------------------------
#  Funcao usada pelo servidor
# ------------------------------------------------------------------
def _motivo(e):
    if isinstance(e, ImportError):
        return "edge-tts nao instalado (pip install edge-tts)"
    return "%s" % (str(e)[:160] or type(e).__name__)


def gerar_detalhado(texto, saida, velocidade=0, voz=None):
    """Gera WAV 8 kHz com a voz pedida. Se falhar, tenta Francisca e depois Windows.
    Retorna (nome da voz usada, aviso). aviso = "" quando saiu a voz pedida."""
    texto = (texto or "").strip()
    if not texto:
        raise ErroVoz("digite um texto")
    if len(texto) > 500:
        raise ErroVoz("texto muito longo (max 500 caracteres)")
    saida = os.path.abspath(saida)
    os.makedirs(os.path.dirname(saida), exist_ok=True)

    tipo, nome = resolve_voz(voz)
    avisos = []

    if tipo == "eleven":
        try:
            return _gerar_eleven(texto, saida, nome), ""
        except Exception as e:
            avisos.append("%s falhou (%s)" % (nome, _motivo(e)))
            print("[voz] %s - tentando a Francisca" % avisos[-1])
            tipo, nome = "edge", VOZ_EDGE_PADRAO

    texto_simples = _sem_tags(texto) or texto
    if tipo == "edge":
        try:
            return _gerar_edge(texto_simples, saida, nome, velocidade), " / ".join(avisos)
        except Exception as e:
            avisos.append("edge-tts falhou (%s)" % _motivo(e))
            print("[voz] %s - usando a voz do Windows" % avisos[-1])

    return _gerar_windows(texto_simples, saida, velocidade), " / ".join(avisos)


def gerar(texto, saida, velocidade=0, voz=None):
    """Igual ao gerar_detalhado, mas retorna so o nome da voz usada."""
    return gerar_detalhado(texto, saida, velocidade, voz)[0]


# ------------------------------------------------------------------
#  Linha de comando
# ------------------------------------------------------------------
def _lista_vozes():
    print("Vozes do painel:")
    for v in lista_vozes():
        print("  %-18s %s" % (v["id"], v["nome"]))
    if os.name == "nt":
        r = roda_ps(PS_LISTA)
        print("\nVozes do Windows instaladas:")
        print(r.stdout or r.stderr)
    print("\nPadrao (falas automaticas): %s" % (voz_edge_escolhida() or "voz do Windows"))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    if args[0].lower() == "vozes":
        _lista_vozes()
        return

    voz_pedida = None
    for a in list(args):
        if a.startswith("--voz="):
            voz_pedida = a.split("=", 1)[1]
            args.remove(a)
    if not args:
        print(__doc__)
        return
    texto = args[0]
    saida = args[1] if len(args) > 1 else os.path.join(PASTA, "sons", "voz.wav")
    try:
        voz, aviso = gerar_detalhado(texto, saida, voz=voz_pedida)
    except ErroVoz as e:
        print("Falhou:", e)
        return
    saida = os.path.abspath(saida)
    if aviso:
        print("[!]", aviso)
    print("VOZ:", voz)
    print("Gerado: %s (%d bytes)" % (saida, os.path.getsize(saida)))


if __name__ == "__main__":
    main()
