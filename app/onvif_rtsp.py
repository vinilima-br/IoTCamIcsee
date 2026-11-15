# =============================================================
#  onvif_rtsp.py - Descobre a URL RTSP de uma câmera via ONVIF
#
#  Algumas câmeras (como a iCSee X6S) não aceitam a senha da conta
#  direto no endereço RTSP: elas usam um usuário interno próprio,
#  que só o ONVIF entrega. Este módulo pergunta ao ONVIF qual é o
#  endereço RTSP de cada perfil de vídeo e devolve pronto pra usar.
#
#  Função principal:
#    descobre_urls(ip, usuario, senha) -> lista de URLs RTSP
#    (a 1ª costuma ser a de alta resolução, a 2ª a leve)
# =============================================================

import base64
import hashlib
import os
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone

PORTAS_ONVIF_PADRAO = [8899, 80, 8000, 8080]


class ErroOnvif(Exception):
    pass


def _porta_aberta(ip, porta, timeout=3):
    try:
        with socket.create_connection((ip, porta), timeout=timeout):
            return True
    except OSError:
        return False


def _cabecalho_seguranca(usuario, senha):
    nonce = os.urandom(16)
    criado = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(hashlib.sha1(nonce + criado.encode() + senha.encode()).digest()).decode()
    return (
        '<Security s:mustUnderstand="1" xmlns="http://docs.oasis-open.org/wss/2004/01/'
        'oasis-200401-wss-wssecurity-secext-1.0.xsd"><UsernameToken>'
        "<Username>{u}</Username>"
        '<Password Type="http://docs.oasis-open.org/wss/2004/01/'
        'oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{d}</Password>'
        '<Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/'
        'oasis-200401-wss-soap-message-security-1.0#Base64Binary">{n}</Nonce>'
        '<Created xmlns="http://docs.oasis-open.org/wss/2004/01/'
        'oasis-200401-wss-wssecurity-utility-1.0.xsd">{c}</Created>'
        "</UsernameToken></Security>"
    ).format(u=usuario, d=digest, n=base64.b64encode(nonce).decode(), c=criado)


def _soap(url, corpo, usuario, senha, autenticar=True, timeout=6):
    cabecalho = _cabecalho_seguranca(usuario, senha) if autenticar else ""
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        "<s:Header>{}</s:Header><s:Body>{}</s:Body></s:Envelope>"
    ).format(cabecalho, corpo)
    pedido = urllib.request.Request(
        url, data=envelope.encode("utf-8"),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as erro:
        return 0, str(erro)


def _acha_device_service(ip, usuario, senha, portas):
    for porta in portas:
        if not _porta_aberta(ip, porta):
            continue
        url = "http://{}:{}/onvif/device_service".format(ip, porta)
        status, xml = _soap(url, '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>',
                            usuario, senha, autenticar=False)
        if status == 200 and "SystemDateAndTime" in xml:
            return url, porta
    return None, None


def _acha_media_xaddr(device_url, usuario, senha, ip, porta):
    status, xml = _soap(device_url, '<GetServices xmlns="http://www.onvif.org/ver10/device/wsdl">'
                                    "<IncludeCapability>false</IncludeCapability></GetServices>",
                       usuario, senha)
    if status == 200:
        for ns, xaddr in re.findall(r"<[\w-]*:?Namespace>([^<]+)</[\w-]*:?Namespace>\s*"
                                    r"<[\w-]*:?XAddr>([^<]+)</", xml):
            if "media" in ns.lower():
                return xaddr
    return "http://{}:{}/onvif/Media".format(ip, porta)


def _injeta_credenciais(uri, usuario, senha):
    """Coloca usuario:senha na frente da URL se ainda não tiver."""
    corpo = uri.split("//", 1)[-1]
    antes_barra = corpo.split("/", 1)[0]
    if "@" in antes_barra:        # já tem credenciais
        return uri
    return uri.replace("rtsp://", "rtsp://{}:{}@".format(usuario, senha), 1)


def descobre_urls(ip, usuario, senha, porta_onvif=None, timeout=6):
    """
    Pergunta ao ONVIF as URLs RTSP da câmera.
    Retorna uma lista de URLs (string), uma por perfil de vídeo,
    normalmente [alta, leve]. Lança ErroOnvif se não conseguir.
    """
    portas = [porta_onvif] if porta_onvif else PORTAS_ONVIF_PADRAO
    device_url, porta = _acha_device_service(ip, usuario, senha, portas)
    if not device_url:
        raise ErroOnvif("ONVIF não respondeu nas portas {} de {}".format(portas, ip))

    media_url = _acha_media_xaddr(device_url, usuario, senha, ip, porta)
    status, xml = _soap(media_url, '<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>',
                       usuario, senha, timeout=timeout)
    tokens = re.findall(r"<[\w-]*:?Profiles[^>]*\btoken=\"([^\"]+)\"", xml) if status == 200 else []
    if not tokens:
        raise ErroOnvif("não listou os perfis de vídeo (HTTP {})".format(status))

    urls = []
    for token in tokens:
        corpo = ('<GetStreamUri xmlns="http://www.onvif.org/ver10/media/wsdl">'
                 '<StreamSetup><Stream xmlns="http://www.onvif.org/ver10/schema">RTP-Unicast</Stream>'
                 '<Transport xmlns="http://www.onvif.org/ver10/schema"><Protocol>RTSP</Protocol></Transport>'
                 '</StreamSetup><ProfileToken>{}</ProfileToken></GetStreamUri>').format(token)
        status, xml = _soap(media_url, corpo, usuario, senha, timeout=timeout)
        achado = re.search(r"<[\w-]*:?Uri>([^<]+)</", xml)
        if achado:
            urls.append(_injeta_credenciais(achado.group(1).strip(), usuario, senha))

    if not urls:
        raise ErroOnvif("o ONVIF não devolveu nenhuma URL de vídeo")
    return urls


def info_dispositivo(ip, usuario, senha, porta_onvif=None):
    """Retorna (modelo, firmware) ou (None, None). Útil só para log."""
    portas = [porta_onvif] if porta_onvif else PORTAS_ONVIF_PADRAO
    device_url, _ = _acha_device_service(ip, usuario, senha, portas)
    if not device_url:
        return None, None
    status, xml = _soap(device_url, '<GetDeviceInformation xmlns="http://www.onvif.org/ver10/device/wsdl"/>',
                       usuario, senha)
    modelo = re.search(r"<[\w-]*:?Model>([^<]*)</", xml)
    fw = re.search(r"<[\w-]*:?FirmwareVersion>([^<]*)</", xml)
    return (modelo.group(1) if modelo else None), (fw.group(1) if fw else None)
