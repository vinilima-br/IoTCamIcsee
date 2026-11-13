# =============================================================
#  ptz.py - Movimentar a câmera (PTZ) pelo ONVIF
#
#  Usa o mesmo ONVIF que já achou o endereço de vídeo da iCSee.
#  Oferece: mover continuamente numa direção, parar, e posições
#  salvas (presets). O servidor/página chamam essas funções.
#
#  "Continuous move": a câmera se move enquanto você segura;
#  manda-se a velocidade (pan/tilt/zoom de -1 a 1) e depois um
#  parar(). É o que encaixa com segurar um botão de seta.
# =============================================================

import re
import threading

import onvif_rtsp as o

NS_PTZ = "http://www.onvif.org/ver20/ptz/wsdl"
NS_SCHEMA = "http://www.onvif.org/ver10/schema"


class ErroPTZ(Exception):
    pass


def _servicos(device_url, usuario, senha):
    """namespace(min) -> XAddr, via GetServices."""
    status, xml = o._soap(
        device_url,
        '<GetServices xmlns="http://www.onvif.org/ver10/device/wsdl">'
        "<IncludeCapability>false</IncludeCapability></GetServices>",
        usuario, senha)
    achados = {}
    if status == 200:
        for ns, xaddr in re.findall(
                r"<[\w-]*:?Namespace>([^<]+)</[\w-]*:?Namespace>\s*"
                r"<[\w-]*:?XAddr>([^<]+)</", xml):
            achados[ns.lower()] = xaddr
    return achados


def contexto(ip, usuario, senha, porta_onvif=None):
    """Descobre o serviço de PTZ e os perfis. Lança ErroPTZ se falhar."""
    portas = [porta_onvif] if porta_onvif else o.PORTAS_ONVIF_PADRAO
    device_url, porta = o._acha_device_service(ip, usuario, senha, portas)
    if not device_url:
        raise ErroPTZ("ONVIF não respondeu em {}".format(ip))

    servicos = _servicos(device_url, usuario, senha)
    ptz_url = next((x for ns, x in servicos.items() if "ptz" in ns), None)
    media_url = next((x for ns, x in servicos.items() if "media" in ns), None)
    if not media_url:
        media_url = "http://{}:{}/onvif/Media".format(ip, porta)
    tem_ptz = ptz_url is not None
    if not ptz_url:
        ptz_url = "http://{}:{}/onvif/PTZ".format(ip, porta)

    status, xml = o._soap(media_url,
                          '<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>',
                          usuario, senha)
    profiles = re.findall(r"<[\w-]*:?Profiles[^>]*\btoken=\"([^\"]+)\"", xml) if status == 200 else []
    # perfil com PTZConfiguration = o vídeo dessa câmera tem motor ligado a ele
    perfil_com_ptz = status == 200 and re.search(r"<[\w-]*:?PTZConfiguration\b", xml) is not None

    return {
        "ip": ip, "usuario": usuario, "senha": senha,
        "device_url": device_url, "media_url": media_url, "ptz_url": ptz_url,
        "porta": porta, "profiles": profiles, "tem_ptz": tem_ptz, "perfil_com_ptz": perfil_com_ptz,
    }


def tem_motor(ctx):
    """A câmera se mexe de verdade? Serviço PTZ + (nó PTZ ou perfil com PTZConfiguration)."""
    if not ctx.get("tem_ptz"):
        return False
    status, xml = o._soap(ctx["ptz_url"], '<GetNodes xmlns="{}"/>'.format(NS_PTZ),
                          ctx["usuario"], ctx["senha"])
    nos = len(re.findall(r"<[\w-]*:?PTZNode\b", xml)) if status == 200 and not _tem_fault(xml) else 0
    return nos > 0 or bool(ctx.get("perfil_com_ptz"))


def _tem_fault(xml):
    return "Fault" in xml or "fault" in xml


def _motivo(status, xml):
    m = re.search(r"<[\w-]*:?Text[^>]*>([^<]*)</", xml or "")
    if m:
        return m.group(1).strip()
    return "HTTP {}".format(status)


def mover(ctx, token, pan=0.0, tilt=0.0, zoom=0.0):
    """Começa a mover (velocidades de -1 a 1). Lança ErroPTZ em falha."""
    corpo = (
        '<ContinuousMove xmlns="{ns}">'
        "<ProfileToken>{t}</ProfileToken>"
        "<Velocity>"
        '<PanTilt x="{p}" y="{ti}" xmlns="{sc}"/>'
        '<Zoom x="{z}" xmlns="{sc}"/>'
        "</Velocity></ContinuousMove>"
    ).format(ns=NS_PTZ, sc=NS_SCHEMA, t=token, p=pan, ti=tilt, z=zoom)
    status, xml = o._soap(ctx["ptz_url"], corpo, ctx["usuario"], ctx["senha"])
    if status != 200 or _tem_fault(xml):
        raise ErroPTZ(_motivo(status, xml))


def parar(ctx, token):
    corpo = (
        '<Stop xmlns="{ns}"><ProfileToken>{t}</ProfileToken>'
        "<PanTilt>true</PanTilt><Zoom>true</Zoom></Stop>"
    ).format(ns=NS_PTZ, t=token)
    status, xml = o._soap(ctx["ptz_url"], corpo, ctx["usuario"], ctx["senha"])
    if status != 200 or _tem_fault(xml):
        raise ErroPTZ(_motivo(status, xml))


def listar_presets(ctx, token):
    """Retorna [(token, nome)] das posições salvas."""
    corpo = ('<GetPresets xmlns="{ns}"><ProfileToken>{t}</ProfileToken></GetPresets>'
             ).format(ns=NS_PTZ, t=token)
    status, xml = o._soap(ctx["ptz_url"], corpo, ctx["usuario"], ctx["senha"])
    if status != 200:
        return []
    presets = []
    for bloco in re.findall(r"<[\w-]*:?Preset\b[^>]*token=\"([^\"]+)\"[^>]*>(.*?)</[\w-]*:?Preset>", xml, re.S):
        tok, miolo = bloco
        nome = re.search(r"<[\w-]*:?Name>([^<]*)</", miolo)
        presets.append((tok, nome.group(1) if nome else tok))
    return presets


def ir_preset(ctx, token, preset_token):
    corpo = ('<GotoPreset xmlns="{ns}"><ProfileToken>{t}</ProfileToken>'
             "<PresetToken>{p}</PresetToken></GotoPreset>"
             ).format(ns=NS_PTZ, t=token, p=preset_token)
    status, xml = o._soap(ctx["ptz_url"], corpo, ctx["usuario"], ctx["senha"])
    if status != 200 or _tem_fault(xml):
        raise ErroPTZ(_motivo(status, xml))


class Controle:
    """Controle de PTZ de uma câmera, pronto pro servidor usar.

    Descobre o ONVIF sob demanda (na primeira vez que precisa) e
    guarda o contexto. perfil: token da lente móvel; se None, usa o
    primeiro perfil da câmera.
    """

    def __init__(self, ip, usuario, senha, porta_onvif=None, perfil=None):
        self.ip = ip
        self.usuario = usuario
        self.senha = senha
        self.porta = porta_onvif
        self.perfil_forcado = perfil
        self.ctx = None
        self.token = None
        self.erro = None
        self.trava = threading.Lock()
        self.capaz = None          # None = ainda não sei / True = tem motor / False = câmera fixa

    def verificar(self):
        """Pergunta à câmera (ONVIF) se ela tem motor. Guarda em self.capaz e devolve."""
        with self.trava:
            if not self._garante():
                return None
            try:
                self.capaz = tem_motor(self.ctx)
            except Exception as e:  # noqa: BLE001
                self.erro = "não consegui confirmar o PTZ: {}".format(e)
                return None
            return self.capaz

    def _garante(self):
        if self.ctx and self.token:
            return True
        try:
            self.ctx = contexto(self.ip, self.usuario, self.senha, self.porta)
        except ErroPTZ as erro:
            self.erro = str(erro)
            return False
        profs = self.ctx["profiles"]
        self.token = self.perfil_forcado or (profs[0] if profs else None)
        if not self.token:
            self.erro = "a câmera não expôs um perfil de vídeo"
            return False
        self.erro = None
        return True

    def mover(self, pan=0.0, tilt=0.0, zoom=0.0):
        with self.trava:
            if not self._garante():
                raise ErroPTZ(self.erro)
            mover(self.ctx, self.token, pan=pan, tilt=tilt, zoom=zoom)

    def parar(self):
        with self.trava:
            if not self._garante():
                raise ErroPTZ(self.erro)
            parar(self.ctx, self.token)

    def presets(self):
        with self.trava:
            if not self._garante():
                return []
            try:
                return listar_presets(self.ctx, self.token)
            except Exception:
                return []

    def ir(self, preset_token):
        with self.trava:
            if not self._garante():
                raise ErroPTZ(self.erro)
            ir_preset(self.ctx, self.token, preset_token)
