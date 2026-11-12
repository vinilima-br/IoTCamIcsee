# =============================================================
#  Projeto ESP + CAM  -  MODELO de configuracao
#  --------------------------------------------------------------
#  Este e o MODELO (vai para o GitHub, SEM senhas).
#  No PC, copie para config.py e preencha - ou deixe o
#  provisionar.py / INSTALAR.bat preencherem sozinhos.
#      copy config_exemplo.py config.py
#  O config.py real NAO vai para o repositorio (.gitignore).
# =============================================================

# -------------------------------------------------------------
#  ElevenLabs (vozes da fala) - opcional. Deixe vazio se nao usar.
# -------------------------------------------------------------
ELEVENLABS_API_KEY = ""
ELEVENLABS_VOZES = ["Adam", "Alice", "Bella", "Bill", "Carlos"]


# =============================================================
#  CAMERAS  -  uma lista, cada camera e um dicionario.
#  Comece VAZIA: o provisionar.py (ferramentas\provisionar.py)
#  insere as iCSee aqui sozinho. Veja a secao 12 do GUIA_COMPLETO.md.
#
#  Modelo de um bloco iCSee (descomente e ajuste, ou deixe o
#  provisionar.py gerar):
#    {
#        "cid": "cam1", "tipo": "icsee", "nome": "iCSee Portao",
#        "ip": "192.168.3.XX",
#        "usuario": "seu@email.com", "senha": "senha do app",
#        "porta_onvif": 8899,
#        "admin_usuario": "swua", "admin_senha": "SUASENHAFIXA",
#        "xm": True, "ptz": True,
#    },
# =============================================================
CAMERAS = [
]


# -------------------------------------------------------------
#  PAUSA do login da Elsys (RSA) na sessao 34567
#  True = nao loga nas Elsys (video RTSP continua; sem alto-falante/luz/SD)
# -------------------------------------------------------------
ELSYS_SESSAO_PAUSADA = True


def cameras():
    """Lista das cameras com todos os campos preenchidos (defaults).
    Usada pelo servidor.py e pelo sessao_xm.py - a regra fica so aqui."""
    saida = []
    vistos = set()
    for i, bruto in enumerate(CAMERAS, 1):
        c = dict(bruto)
        c.setdefault("cid", "cam%d" % i)
        c.setdefault("tipo", "icsee")
        c.setdefault("nome", c["cid"])
        c.setdefault("xm", True)
        c["stream"] = c.get("stream", 1) if c.get("stream") in (0, 1) else 1
        if c["tipo"] == "elsys":
            if ELSYS_SESSAO_PAUSADA:
                c["xm"] = False
            c.setdefault("porta", 554)
            c.setdefault("usuario", "admin")
            c.setdefault("senha", "")
        else:  # icsee
            c.setdefault("usuario", "admin")
            c.setdefault("senha", "")
            c.setdefault("porta_onvif", 0)
            c.setdefault("admin_usuario", "admin")
            c.setdefault("admin_senha", "")
            c.setdefault("ptz", True)
            c.setdefault("ptz_perfil", "000")
        if c["cid"] in vistos:
            raise ValueError("config.py: cid repetido em CAMERAS: %r" % c["cid"])
        vistos.add(c["cid"])
        saida.append(c)
    return saida


# -------------------------------------------------------------
#  Reconhecimento facial - frases faladas na camera
# -------------------------------------------------------------
ROSTO_FRASE_OK = "Acesso liberado, {nome}"
ROSTO_FRASE_NEGADO = "Acesso negado"
