# -*- coding: utf-8 -*-
"""
cameras_cfg.py  -  Menu "➕ Câmeras" do painel: buscar na rede, testar o vídeo,
                   adicionar e remover câmera no config.py (sempre com backup).

Usado pelo servidor.py. As regras de conta da porta 34567 são as do
ferramentas/provisionar.py (o mesmo código do INSTALAR antigo):

  som "resetada": câmera RECÉM-resetada -> descobre a conta real e FIXA a senha
  som "conta":    você já sabe usuário/senha fixa (ex.: câmera que já roda em
                  outro PC) -> só confere, NÃO mexe na câmera
  som "nenhum":   só vídeo (xm = False); dá pra ligar o som depois pelo ⚙ Config
"""
import base64
import importlib
import io
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

PASTA = os.path.dirname(os.path.abspath(__file__))
FERRAMENTAS = os.path.join(PASTA, "ferramentas")
if FERRAMENTAS not in sys.path:
    sys.path.insert(0, FERRAMENTAS)

import config                    # noqa: E402
import onvif_rtsp                # noqa: E402

PORTAS_BUSCA = (34567, 554, 8899)
SENHA_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#_.-!*")
_trava = threading.Lock()


def _prov():
    import provisionar           # noqa: E402  (recupera_e_fixa / confere_conta / config.py)
    importlib.reload(config)
    return provisionar


# ------------------------------------------------------------------ captura dos prints
class _Captura(io.TextIOBase):
    """Guarda em 'linhas' o que ESTA thread imprimir (o resto segue normal)."""

    def __init__(self, original, linhas):
        self.original, self.linhas, self.ident = original, linhas, threading.get_ident()

    def write(self, txt):
        if threading.get_ident() == self.ident:
            for linha in str(txt).splitlines():
                if linha.strip():
                    self.linhas.append(linha.strip())
        return self.original.write(txt)

    def flush(self):
        self.original.flush()


def _com_captura(func, *args):
    linhas = []
    original = sys.stdout
    sys.stdout = _Captura(original, linhas)
    try:
        return func(*args), linhas
    finally:
        sys.stdout = original


# ------------------------------------------------------------------ rede
def ips_locais():
    """IPv4 privados deste PC (todas as placas de rede)."""
    achados = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            achados.add(info[4][0])
    except OSError:
        pass
    for destino in ("192.168.0.1", "10.0.0.1", "172.16.0.1", "8.8.8.8"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((destino, 9))
            achados.add(s.getsockname()[0])
            s.close()
        except OSError:
            pass
    saida = []
    for ip in achados:
        try:
            o = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if o.is_private and not o.is_loopback and not o.is_link_local:
            saida.append(ip)
    return sorted(saida)


def _porta_aberta(ip, porta, timeout):
    try:
        with socket.create_connection((ip, porta), timeout=timeout):
            return True
    except OSError:
        return False


_PROBE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
    'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
    'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    '<e:Header><w:MessageID>uuid:{id}</w:MessageID>'
    '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
    '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
    '</e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>'
    '</e:Envelope>')


def _onvif_descoberta(locais, segundos=2.5):
    """WS-Discovery (multicast 239.255.255.250:3702). {ip: {"porta_onvif", "modelo"}}."""
    achados = {}
    socks = []
    for local in locais or [""]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            if local:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local))
                s.bind((local, 0))
            s.settimeout(0.3)
            s.sendto(_PROBE.format(id=uuid.uuid4()).encode(), ("239.255.255.250", 3702))
            socks.append(s)
        except OSError:
            continue
    fim = time.time() + segundos
    while time.time() < fim and socks:
        for s in socks:
            try:
                dados, (ip, _) = s.recvfrom(65535)
            except OSError:
                continue
            txt = dados.decode("utf-8", "ignore")
            d = achados.setdefault(ip, {"porta_onvif": None, "modelo": ""})
            m = re.search(r"http://[^/\s<]*?:(\d+)/onvif", txt)
            if m:
                d["porta_onvif"] = int(m.group(1))
            elif re.search(r"http://[\d.]+/onvif", txt):
                d["porta_onvif"] = 80
            partes = []
            for chave in ("hardware", "name"):
                m = re.search(r"onvif://www\.onvif\.org/%s/([^\s<]+)" % chave, txt)
                if m:
                    valor = re.sub(r"%20", " ", m.group(1))
                    if valor not in partes:
                        partes.append(valor)
            if partes:
                d["modelo"] = " · ".join(partes)
    for s in socks:
        s.close()
    return achados


def buscar(timeout_porta=0.6):
    """Varre a(s) rede(s) deste PC atrás de câmeras. Leva uns 3 a 6 s."""
    locais = ips_locais()
    alvos = []
    for local in locais:
        rede = ipaddress.ip_network(local + "/24", strict=False)
        alvos.extend(str(h) for h in rede.hosts() if str(h) not in locais)
    alvos = sorted(set(alvos), key=lambda x: tuple(int(p) for p in x.split(".")))

    resultado = {}
    descoberta = {}
    t = threading.Thread(target=lambda: descoberta.update(_onvif_descoberta(locais)), daemon=True)
    t.start()

    def testa(par):
        ip, porta = par
        return ip, porta, _porta_aberta(ip, porta, timeout_porta)

    with ThreadPoolExecutor(max_workers=200) as ex:
        for ip, porta, aberta in ex.map(testa, [(ip, p) for ip in alvos for p in PORTAS_BUSCA]):
            if aberta:
                resultado.setdefault(ip, set()).add(porta)
    t.join(timeout=4)

    importlib.reload(config)
    por_ip = {c.get("ip"): c for c in config.cameras()}
    cams = []
    for ip in sorted(set(resultado) | set(descoberta), key=lambda x: tuple(int(p) for p in x.split("."))):
        portas = sorted(resultado.get(ip, set()))
        info = descoberta.get(ip, {})
        porta_onvif = info.get("porta_onvif") or (8899 if 8899 in portas else None)
        if porta_onvif:
            tipo = "icsee"
        elif 554 in portas:
            tipo = "elsys"          # RTSP direto, sem ONVIF (como a Elsys)
        else:
            continue                # só 34567 sem vídeo: não é câmera que dá pra pôr
        ja = por_ip.get(ip)
        cams.append({"ip": ip, "portas": portas, "porta_onvif": porta_onvif, "tipo": tipo,
                     "modelo": info.get("modelo", ""), "som": 34567 in portas,
                     "no_painel": ja["cid"] if ja else None,
                     "nome_painel": ja["nome"] if ja else None})
    return {"ok": True, "redes": [l.rsplit(".", 1)[0] + ".x" for l in locais], "cameras": cams}


# ------------------------------------------------------------------ vídeo
def url_elsys(ip, porta, usuario, senha, stream):
    return "rtsp://{ip}:{porta}/user={u}_password={s}_channel=1_stream={st}.sdp".format(
        ip=ip, porta=porta, u=usuario, s=senha, st=stream)


def _foto(url, segundos=12):
    """Um quadro do vídeo como data:image/jpeg (ou None)."""
    caixa = {}

    def pega():
        try:
            import cv2
            try:
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG,
                                       [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000,
                                        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000])
            except (TypeError, AttributeError, cv2.error):
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            ok, quadro = False, None
            for _ in range(15):              # os primeiros quadros podem vir cinza
                ok, quadro = cap.read()
                if not ok:
                    break
            cap.release()
            if ok and quadro is not None:
                alt, larg = quadro.shape[:2]
                if larg > 640:
                    quadro = cv2.resize(quadro, (640, int(alt * 640 / larg)))
                ok2, jpg = cv2.imencode(".jpg", quadro, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ok2:
                    caixa["foto"] = "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()
        except Exception as e:  # noqa: BLE001
            caixa["erro"] = repr(e)

    t = threading.Thread(target=pega, daemon=True)
    t.start()
    t.join(segundos)
    return caixa.get("foto")


def _ip_valido(ip):
    try:
        return ipaddress.ip_address(ip).version == 4
    except ValueError:
        return False


def testar_video(d):
    tipo, ip = d.get("tipo"), (d.get("ip") or "").strip()
    if not _ip_valido(ip):
        return {"ok": False, "erro": "IP inválido"}
    if tipo == "elsys":
        porta = int(d.get("porta") or 554)
        if not _porta_aberta(ip, porta, 2):
            return {"ok": False, "erro": "a porta %d (RTSP) não respondeu em %s" % (porta, ip)}
        foto = _foto(url_elsys(ip, porta, d.get("usuario") or "admin", d.get("senha") or "", 1))
        if not foto:
            return {"ok": False, "erro": "a câmera não mandou vídeo (senha do vídeo errada?)"}
        return {"ok": True, "foto": foto, "modelo": "Elsys / RTSP"}

    usuario, senha = (d.get("usuario") or "").strip(), d.get("senha") or ""
    if not usuario or not senha:
        return {"ok": False, "erro": "preencha o e-mail e a senha do app"}
    portas = [int(d["porta_onvif"])] if d.get("porta_onvif") else []
    portas += [p for p in onvif_rtsp.PORTAS_ONVIF_PADRAO if p not in portas]
    ultimo = "nenhuma porta ONVIF respondeu"
    for p in portas:
        if not _porta_aberta(ip, p, 1.5):
            continue
        try:
            urls = onvif_rtsp.descobre_urls(ip, usuario, senha, porta_onvif=p)
        except Exception as e:  # noqa: BLE001
            ultimo = str(e)
            continue
        if not urls:
            continue
        modelo = ""
        try:
            modelo, _fw = onvif_rtsp.info_dispositivo(ip, usuario, senha, p)
        except Exception:  # noqa: BLE001
            pass
        lista = list(urls.values()) if isinstance(urls, dict) else list(urls)
        foto = _foto(lista[1] if len(lista) > 1 else lista[0])
        return {"ok": True, "porta_onvif": p, "modelo": modelo or "", "foto": foto,
                "aviso": None if foto else "o login deu certo, mas a foto não veio (o painel tenta de novo)"}
    return {"ok": False, "erro": "não consegui o vídeo: %s (e-mail/senha do app certos?)" % ultimo}


# ------------------------------------------------------------------ config.py
def _literal(v):
    return json.dumps(v, ensure_ascii=False)


def _monta_bloco(c):
    linhas = ["    {"]
    for chave in ("cid", "tipo", "nome", "ip", "usuario", "senha", "porta", "porta_onvif",
                  "admin_usuario", "admin_senha", "xm", "ptz"):
        if chave not in c:
            continue
        v = c[chave]
        txt = ("True" if v else "False") if isinstance(v, bool) else (str(v) if isinstance(v, int) else _literal(v))
        linhas.append('        "%s": %s,' % (chave, txt))
    linhas.append("    },")
    return "\n".join(linhas) + "\n"


def _insere(bloco):
    prov = _prov()
    with open(prov.CONFIG_PY, "r", encoding="utf-8") as f:
        texto = f.read()
    ini = texto.find("CAMERAS = [")
    if ini < 0:
        raise RuntimeError("não achei 'CAMERAS = [' no config.py")
    abre = texto.find("[", ini)
    prof, fecha = 0, -1
    for i in range(abre, len(texto)):
        if texto[i] == "[":
            prof += 1
        elif texto[i] == "]":
            prof -= 1
            if prof == 0:
                fecha = i
                break
    if fecha < 0:
        raise RuntimeError("não achei o ] que fecha a lista CAMERAS")
    if texto[abre + 1:fecha].strip() == "":                 # lista vazia: CAMERAS = [\n]
        novo = texto[:abre + 1] + "\n" + bloco + texto[fecha:]
    else:
        linha = texto.rfind("\n", 0, fecha) + 1
        antes = texto[:linha].rstrip()
        if not antes.endswith(",") and not antes.endswith("["):
            texto_antes = antes + ","
            novo = texto_antes + "\n" + bloco + texto[linha:]
        else:
            novo = texto[:linha] + bloco + texto[linha:]
    return _grava(prov, texto, novo)


def _grava(prov, antigo, novo):
    compile(novo, prov.CONFIG_PY, "exec")                    # nunca grava config.py quebrado
    carimbo = time.strftime("%Y%m%d_%H%M%S")
    backup, n = prov.CONFIG_PY + ".bak_" + carimbo, 2
    while os.path.exists(backup):
        backup, n = prov.CONFIG_PY + ".bak_%s_%d" % (carimbo, n), n + 1
    with open(backup, "w", encoding="utf-8") as f:
        f.write(antigo)
    with open(prov.CONFIG_PY, "w", encoding="utf-8") as f:
        f.write(novo)
    importlib.reload(config)
    return os.path.basename(backup)


def _novo_cid():
    """camN que nunca foi usado: nem no config.py nem em pastas de fotos/gravações
    (assim uma câmera nova não herda gravações/ajustes de uma removida)."""
    usados = {c["cid"] for c in config.cameras()}
    for pasta in ("fotos", "gravacoes", "sd_baixados", os.path.join("rostos", "eventos")):
        try:
            usados.update(os.listdir(os.path.join(PASTA, pasta)))
        except OSError:
            pass
    nums = [int(m.group(1)) for m in (re.fullmatch(r"cam(\d+)", u) for u in usados) if m]
    return "cam%d" % (max(nums, default=0) + 1)


def lista():
    importlib.reload(config)
    return [{"cid": c["cid"], "nome": c["nome"], "tipo": c["tipo"], "ip": c.get("ip", ""),
             "som": bool(c.get("xm"))} for c in config.cameras()]


def adicionar(d):
    """Valida, (se pedido) mexe na conta da 34567 e grava a câmera no config.py."""
    if not _trava.acquire(blocking=False):
        return {"ok": False, "erro": "já tem uma câmera sendo adicionada", "passos": []}
    try:
        return _adicionar(d)
    finally:
        _trava.release()


def _adicionar(d):
    prov = _prov()
    tipo = d.get("tipo")
    ip = (d.get("ip") or "").strip()
    nome = (d.get("nome") or "").strip()[:40]
    if tipo not in ("icsee", "elsys"):
        return {"ok": False, "erro": "tipo de câmera desconhecido", "passos": []}
    if not _ip_valido(ip):
        return {"ok": False, "erro": "IP inválido", "passos": []}
    for c in config.cameras():
        if c.get("ip") == ip:
            return {"ok": False, "erro": "esse IP já está no painel (%s)" % c["nome"], "passos": []}
    cid = _novo_cid()
    nome = nome or ("Câmera %s" % ip.rsplit(".", 1)[1])

    if tipo == "elsys":
        senha = d.get("senha") or ""
        if not senha:
            return {"ok": False, "erro": "preencha a senha do vídeo da Elsys", "passos": []}
        bloco = {"cid": cid, "tipo": "elsys", "nome": nome, "ip": ip, "senha": senha}
        if int(d.get("porta") or 554) != 554:
            bloco["porta"] = int(d["porta"])
        backup = _insere(_monta_bloco(bloco))
        return {"ok": True, "cid": cid, "nome": nome, "backup": backup,
                "passos": ["Elsys gravada como %s (só vídeo)." % cid]}

    usuario, senha = (d.get("usuario") or "").strip(), d.get("senha") or ""
    if not usuario or not senha:
        return {"ok": False, "erro": "preencha o e-mail e a senha do app", "passos": []}
    som = d.get("som") or "nenhum"
    bloco = {"cid": cid, "tipo": "icsee", "nome": nome, "ip": ip, "usuario": usuario,
             "senha": senha, "porta_onvif": int(d.get("porta_onvif") or 8899),
             "xm": som != "nenhum", "ptz": bool(d.get("ptz", True))}
    passos = []

    if som == "resetada":
        fixa = (d.get("senha_fixa") or "").strip()
        if len(fixa) < 6 or not set(fixa) <= SENHA_OK:
            return {"ok": False, "erro": "senha fixa: mínimo 6 caracteres, só letras, números e @#_.-!*",
                    "passos": []}
        conta, passos = _com_captura(prov.recupera_e_fixa, ip, fixa)
        if not conta:
            return {"ok": False, "passos": passos,
                    "erro": "não consegui descobrir a conta. A câmera foi resetada agora há pouco? "
                            "(se ela já funciona em outro PC, use \"Já sei a conta\")"}
        bloco["admin_usuario"], bloco["admin_senha"] = conta
    elif som == "conta":
        au, asenha = (d.get("admin_usuario") or "").strip(), (d.get("admin_senha") or "").strip()
        if not au or not asenha:
            return {"ok": False, "erro": "preencha usuário e senha fixa da câmera", "passos": []}
        if not _porta_aberta(ip, 34567, 3):
            return {"ok": False, "erro": "a porta 34567 (som/luz) não respondeu em %s" % ip, "passos": []}
        ok, passos = _com_captura(prov.confere_conta, ip, au, asenha)
        if not ok:
            return {"ok": False, "passos": passos, "erro": "essa conta não logou na câmera (nada foi mudado)"}
        bloco["admin_usuario"], bloco["admin_senha"] = au, asenha
    elif som != "nenhum":
        return {"ok": False, "erro": "opção de som desconhecida", "passos": []}

    backup = _insere(_monta_bloco(bloco))
    passos.append("gravada no config.py como %s (backup: %s)" % (cid, backup))
    return {"ok": True, "cid": cid, "nome": nome, "backup": backup, "passos": passos}


def remover(cid):
    prov = _prov()
    cam = next((c for c in config.cameras() if c["cid"] == cid), None)
    if cam is None:
        return {"ok": False, "erro": "câmera não está no config.py"}
    with open(prov.CONFIG_PY, "r", encoding="utf-8") as f:
        texto = f.read()
    a, b = prov._acha_bloco(texto, cid, cam.get("ip"))
    fim = b
    while fim < len(texto) and texto[fim] in " \t":
        fim += 1
    if fim < len(texto) and texto[fim] == ",":
        fim += 1
    if fim < len(texto) and texto[fim] == "\n":
        fim += 1
    ini = texto.rfind("\n", 0, a) + 1
    if texto[ini:a].strip():                 # bloco não começa no início da linha
        ini = a
    backup = _grava(prov, texto, texto[:ini] + texto[fim:])
    return {"ok": True, "backup": backup, "nome": cam["nome"]}
