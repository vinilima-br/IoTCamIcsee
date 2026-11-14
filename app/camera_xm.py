# -*- coding: utf-8 -*-
"""
camera_xm.py  -  Sessao PERSISTENTE com cameras XM/iCSee (porta 34567).

Usado pelo servidor (etapa7_servidor_web.py). Cada camera tem UMA sessao:
loga uma vez, mantem viva com KeepAlive e todos os comandos passam por ela
(falar, volume, luz branca, alarme, LED). Nada de login repetido.

Protecao contra o erro 205 (anti-forca-bruta da camera), gravada em
sessao_estado.json para valer mesmo se o servidor for reiniciado:
  - 1 tentativa de login por vez, nunca em loop rapido
  - apos login com sucesso: minimo 20 s ate o proximo login
  - apos falha: 60 s
  - apos 205 (bloqueio): 35 min sem tentar
  - apos 203 (senha errada): para de tentar ate voce pedir (botao na pagina)
  - conexao caiu: reconecta com espera crescente (30 s, 1, 2, 4 ... 10 min)

Protocolo do "falar" igual ao go2rtc (testado na camera 3.67):
  OPTalk Claim (1434) -> OPTalk Start (1430) -> audio G.711A (1432) -> Stop (1430)
"""
import hashlib
import json
import math
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
from collections import deque

PORTA_CAMERA = 34567

ESPERA_APOS_SUCESSO = 20
ESPERA_APOS_FALHA = 60
ESPERA_APOS_205 = 35 * 60        # a camera pode manter o bloqueio ~30 min; tentar antes renova o bloqueio

# Sessao separada (sessao_xm.py): quando ela esta rodando, SO ela pode logar
# na porta 34567. Qualquer outro programa (servidor antigo, diag_*.py) que
# tentar logar e barrado aqui, antes de mandar a senha para a camera.
PORTA_SESSAO = 5051
PROCESSO_DA_SESSAO = False       # sessao_xm.py liga isto no proprio processo
ESPERA_RECONEXAO_BASE = 30
ESPERA_RECONEXAO_MAX = 10 * 60
# Depois de uma QUEDA (rede mudou, Wi-Fi oscilou), a camera pode continuar com a
# sessao antiga aberta por um tempo. Relogar o mesmo admin antes disso - ainda
# mais vindo de outro IP - foi o que deu 205 na cam2 em 09/11 22:07. Espera mais.
ESPERA_APOS_QUEDA = 120
# IP DESTE PC pelo qual falar com as cameras (sessao_xm.py le XM_IP_LOCAL do
# config.py). Vazio = o Windows escolhe. Com ele, se essa placa cair, a sessao
# espera em vez de sair por outro caminho (e a camera ver outro IP).
IP_LOCAL = ""
# SENTINELA: com a sessao logada, a cada SENTINELA_S faz um login de teste (senha
# certa) e sai na hora. Se vier 205 ("User is locked"), o bloqueio e pego NO
# MOMENTO em que acontece - com a sessao principal ainda viva - e o registro
# interno da camera dos minutos anteriores e salvo na hora (diag_bloqueio\).
# 0 = desligada.
SENTINELA_S = 600

ARQ_ESTADO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "sessao_estado.json")
ARQ_MODO_FALA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "xm_fala_modo.json")

# Formas de abrir o canal de voz (o etapa31 descobre qual a camera aceita
# repetidas vezes e grava em xm_fala_modo.json):
#   "sub"      conexao auxiliar SEM login: Claim nela, Start/Stop na sessao
#   "sub_tudo" conexao auxiliar SEM login: Claim/Start/Stop tudo nela
#   "mesma"    tudo na sessao principal (so funciona 1x em algumas cameras)
#   "login"    conexao nova COM login a cada som (igual etapa30; usa logins)
ARQ_LUZ_ALERTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "xm_luz_alerta.json")
# Luz de alerta (LED vermelho/azul) = saida de alarme da camera (AlarmOut).
# Descoberto com ferramentas/diag_luz_alerta.py na cam2: MANUAL+OPEN acende,
# voltar para AUTO+OPEN apaga (e volta a piscar sozinha no movimento).
LUZ_ALERTA_PADRAO = {"nome": "Alarm.AlarmOut",
                     "ligar": {"AlarmOutType": "MANUAL", "AlarmOutStatus": "OPEN"},
                     "original": [{"AlarmOutType": "AUTO", "AlarmOutStatus": "OPEN"}]}
ALERTA_MAX_S = 10 * 60          # "ate desligar" nunca passa de 10 min

MODOS_FALA = ("sub", "sub_tudo", "mesma", "login")
MODO_FALA_PADRAO = "sub"         # o que funcionou nas X6S/X6E sem login extra ("login" gasta 1 login por som)

LOGIN, LOGOUT, KEEPALIVE = 1000, 1001, 1006
SET_CONFIG, GET_CONFIG = 1040, 1042
OPTALK_REQ, OPTALK_DATA, OPTALK_CLAIM = 1430, 1432, 1434
# Alertas da PROPRIA camera (o "Alarme inteligente" do app iCSee: corpo humano,
# movimento...). Depois do login, GUARD (1500) = "me avise dos alarmes"; a camera
# responde 1501 e, a cada deteccao, EMPURRA um 1504 (AlarmInfo) nesta mesma sessao.
GUARD_REQ, ALARM_INFO = 1500, 1504
ARQ_LOG_ALARMES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "alarmes_camera.log")

CHUNK = 320           # 320 bytes A-law = 40 ms
SILENCIO = 0xD5

CODIGOS = {100: "OK", 101: "erro desconhecido", 103: "nao suportado",
           203: "senha errada", 204: "usuario ilegal", 205: "usuario BLOQUEADO na camera (User is locked)",
           206: "usuario na lista negra", 207: "usuario ja logado",
           503: "canal de voz ja aberto", 504: "canal de voz nao aberto",
           515: "OK", 605: "recurso nao suportado", 607: "configuracao nao existe",
           608: "erro ao interpretar a configuracao"}

# Modos conhecidos da luz branca (Camera.WhiteLight.WorkMode).
# "Intelligent" foi lido da sua camera; os outros sao os nomes usados pelas
# cameras XM. Se algum for recusado, a pagina mostra a resposta da camera.
MODOS_LUZ = [
    ("Intelligent", "Inteligente (acende ao detectar)"),
    ("Auto", "Automatica (colorida a noite)"),
    ("KeepOpen", "Sempre acesa"),
    ("Close", "Desligada (so infravermelho)"),
]


class ErroXM(Exception):
    pass


def descreve(ret):
    return "%s (%s)" % (ret, CODIGOS.get(ret, "?"))


def agora():
    return time.time()


def hora(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts)) if ts else None


# ------------------------------------------------------------------
#  Estado persistido (trava anti-205 que sobrevive a reinicios)
# ------------------------------------------------------------------
_trava_estado = threading.Lock()


def le_estado():
    try:
        with open(ARQ_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def grava_estado(ip, **campos):
    with _trava_estado:
        d = le_estado()
        d.setdefault(ip, {}).update(campos)
        tmp = ARQ_ESTADO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, ARQ_ESTADO)


def modo_fala_salvo(ip):
    try:
        with open(ARQ_MODO_FALA, "r", encoding="utf-8") as f:
            m = json.load(f).get(ip)
        return m if m in MODOS_FALA else None
    except Exception:
        return None


def salva_modo_fala(ip, modo):
    try:
        with open(ARQ_MODO_FALA, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d[ip] = modo
    with open(ARQ_MODO_FALA, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def config_luz_alerta(ip):
    try:
        with open(ARQ_LUZ_ALERTA, "r", encoding="utf-8") as f:
            c = json.load(f).get(ip)
        if c and c.get("nome") and c.get("ligar"):
            return c
    except Exception:
        pass
    return LUZ_ALERTA_PADRAO


ARQ_RECUSAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "diag_bloqueio", "recusas_login.log")


def registra_recusa(ip, usuario, motivo, resposta=None, ip_local="?"):
    """Guarda a resposta COMPLETA da camera a cada login recusado (para descobrir a causa dos 205)."""
    try:
        os.makedirs(os.path.dirname(ARQ_RECUSAS), exist_ok=True)
        with open(ARQ_RECUSAS, "a", encoding="utf-8") as f:
            f.write("%s  camera=%s  saindo_por=%s  usuario=%s  %s  resposta=%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), ip, ip_local, usuario, motivo,
                json.dumps(resposta, ensure_ascii=False) if resposta is not None else "-"))
    except Exception:
        pass


def sessao_separada_rodando():
    """True se o sessao_xm.py esta aberto neste PC."""
    try:
        with socket.create_connection(("127.0.0.1", PORTA_SESSAO), timeout=0.5):
            return True
    except OSError:
        return False


def liberado_em(ip):
    """(timestamp a partir do qual pode logar, motivo). None = nao tentar."""
    e = le_estado().get(ip, {})
    ts = e.get("ultima_tentativa", 0)
    ret = e.get("ultimo_ret")
    if ret == 203:
        return None, "senha do admin recusada (203)"
    if ret == 205:
        return ts + ESPERA_APOS_205, "camera bloqueou (205) - esperando %d min" % (ESPERA_APOS_205 // 60)
    if ret in (100, 515):
        return ts + ESPERA_APOS_SUCESSO, "intervalo minimo entre logins"
    if ts:
        return ts + ESPERA_APOS_FALHA, "ultima tentativa falhou"
    return 0, ""


# ------------------------------------------------------------------
#  Audio
# ------------------------------------------------------------------
def lin2alaw(amostra):
    """PCM 16 bits -> 1 byte G.711 A-law (ITU-T G.711)."""
    if amostra >= 0:
        mascara = 0xD5
    else:
        mascara = 0x55
        amostra = -amostra - 1
    if amostra > 32767:
        amostra = 32767
    seg_fim = (0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF)
    a = amostra >> 3
    seg = 0
    while seg < 8 and a > seg_fim[seg]:
        seg += 1
    if seg >= 8:
        return 0x7F ^ mascara
    aval = seg << 4
    aval |= ((a >> 1) if seg < 2 else (a >> seg)) & 0x0F
    return aval ^ mascara


def gera_sirene(segundos=4.0, amp=26000):
    out = bytearray()
    for n in range(int(8000 * segundos)):
        t = n / 8000.0
        f = 1200 if int(t / 0.3) % 2 == 0 else 800
        out.append(lin2alaw(int(amp * math.sin(2 * math.pi * f * t))))
    return bytes(out)


def acha_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def arquivo_para_alaw(caminho):
    """Qualquer audio (mp3/wav/ogg/m4a...) -> bytes G.711 A-law 8 kHz mono."""
    ffmpeg = acha_ffmpeg()
    if not ffmpeg:
        raise ErroXM("ffmpeg nao encontrado (pip install imageio-ffmpeg)")
    r = subprocess.run([ffmpeg, "-loglevel", "error", "-i", caminho,
                        "-ac", "1", "-ar", "8000", "-f", "alaw", "pipe:1"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise ErroXM("nao consegui converter o audio: %s"
                     % r.stderr.decode("utf-8", "replace")[-200:].strip())
    return r.stdout


def sofia_hash(senha):
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    h = hashlib.md5(senha.encode("utf-8")).digest()
    return "".join(chars[(h[i] + h[i + 1]) % 62] for i in range(0, 16, 2))


# ------------------------------------------------------------------
#  Conexao auxiliar (so para o audio da fala)
# ------------------------------------------------------------------
class ConexaoAux:
    """Socket extra para a camera, com leitor proprio. Pode usar a sessao
    da conexao principal (sem login) ou logar (modo "login")."""

    def __init__(self, ip, session=0, timeout=6):
        self.sock = socket.create_connection((ip, PORTA_CAMERA), timeout=timeout)
        self.session = session
        self.seq = 0
        self._envio = threading.Lock()
        self._cond = threading.Condition()
        self._resp = {}
        self._fim = threading.Event()
        self.respostas = []                 # tudo que chegou em JSON (debug)
        self._t = threading.Thread(target=self._leitor, daemon=True)
        self._t.start()

    def envia(self, msgid, payload):
        cab = bytearray(20)
        cab[0] = 255
        struct.pack_into("<I", cab, 4, self.session)
        struct.pack_into("<I", cab, 8, self.seq)
        struct.pack_into("<H", cab, 14, msgid)
        struct.pack_into("<I", cab, 16, len(payload))
        with self._envio:
            self.sock.sendall(bytes(cab) + payload)
            self.seq += 1

    def _leitor(self):
        self.sock.settimeout(0.5)
        while not self._fim.is_set():
            try:
                cab = SessaoCamera._le_exato(self.sock, 20)
                tam = struct.unpack_from("<I", cab, 16)[0]
                corpo = SessaoCamera._le_exato(self.sock, tam) if tam else b""
            except socket.timeout:
                continue
            except Exception:
                break
            if cab[0] != 255:
                break
            msgid = struct.unpack_from("<H", cab, 14)[0]
            if corpo[:1] == b"{":
                j = SessaoCamera._json(corpo)
                if len(self.respostas) < 20:
                    self.respostas.append((msgid, j.get("Ret")))
                with self._cond:
                    sid = struct.unpack_from("<I", cab, 4)[0]
                    if sid and not self.session:
                        self.session = sid
                    self._resp[msgid] = j
                    self._cond.notify_all()

    def comando(self, msgid, texto, timeout=3.0):
        with self._cond:
            self._resp.pop(msgid + 1, None)
        self.envia(msgid, texto.encode("utf-8") + b"\x0a\x00")
        limite = agora() + timeout
        with self._cond:
            while msgid + 1 not in self._resp:
                resta = limite - agora()
                if resta <= 0:
                    return None
                self._cond.wait(resta)
            return self._resp.pop(msgid + 1)

    def fecha(self):
        self._fim.set()
        try:
            self.sock.close()
        except Exception:
            pass


# ------------------------------------------------------------------
#  Sessao persistente
# ------------------------------------------------------------------
class SessaoCamera:
    def __init__(self, nome, ip, usuario="admin", senha="", log=print):
        self.nome, self.ip, self.usuario, self.senha = nome, ip, usuario, senha
        self._log = log
        self.sock = None
        self.session = 0
        self.seq = 0
        self.conectada = False
        self.desde = None
        self.alive_interval = 20
        self.ultimo_erro = ""
        self.proxima_tentativa = 0
        self.desistiu = False
        self.keepalives_ok = 0

        # o que a camera tem (lido depois do login)
        self.volume = None
        self.luz = None             # {"modo":..., "brilho":...}
        self.alarme = None          # {"ligado":bool, "voz":int}
        self.vozes = []             # [{"id":24,"texto":"Alarme"}, ...]
        self.led = None             # True/False ou None (sem suporte)
        self._chave_led = None

        self.falando = None         # {"som":..., "inicio":ts, "segundos":s}
        self.modo_fala = modo_fala_salvo(ip) or MODO_FALA_PADRAO
        self.ultima_fala = None     # diagnostico da ultima vez que tocou
        self.alerta_disponivel = False   # camera tem saida de alarme (LED vermelho/azul)
        self.alerta_ligado = False
        self.alerta_ate = None
        self._timer_alerta = None
        self._trava_alerta = threading.Lock()
        self._ultimo_login_fala = 0
        self._parar_fala = threading.Event()

        self._envio = threading.Lock()
        self._cmd = threading.Lock()
        self._fala = threading.Lock()
        self._resp_cond = threading.Condition()
        self._respostas = {}
        self._ultimo_rx = 0
        self._parar = threading.Event()
        self._acorda = threading.Event()
        self._falha_seguida = 0
        self._thread = None

        # alertas da propria camera (deteccao de corpo humano do app)
        self.guard_ret = None            # Ret do GUARD (100 = assinado)
        self._alarmes = deque(maxlen=200)
        self._alarme_seq = 0
        self._trava_alarmes = threading.Lock()
        self._boot = "%s-%d" % (nome, int(time.time() * 1000))   # muda se a sessao reiniciar

    def log(self, msg):
        self._log("[xm:%s] %s" % (self.nome, msg))

    # ---------------- baixo nivel ----------------
    def _envia(self, msgid, payload):
        cab = bytearray(20)
        cab[0] = 255
        struct.pack_into("<I", cab, 4, self.session)
        struct.pack_into("<I", cab, 8, self.seq)
        struct.pack_into("<H", cab, 14, msgid)
        struct.pack_into("<I", cab, 16, len(payload))
        with self._envio:
            if not self.sock:
                raise ConnectionError("sem conexao")
            self.sock.sendall(bytes(cab) + payload)
            self.seq += 1

    @staticmethod
    def _le_exato(sock, n):
        buf = b""
        while len(buf) < n:
            b = sock.recv(n - len(buf))
            if not b:
                raise ConnectionError("a camera fechou a conexao")
            buf += b
        return buf

    def _le_pacote(self, sock):
        cab = self._le_exato(sock, 20)
        if cab[0] != 255:
            raise ConnectionError("pacote invalido")
        msgid = struct.unpack_from("<H", cab, 14)[0]
        tam = struct.unpack_from("<I", cab, 16)[0]
        corpo = self._le_exato(sock, tam) if tam else b""
        return struct.unpack_from("<I", cab, 4)[0], msgid, corpo

    @staticmethod
    def _json(corpo):
        txt = corpo.rstrip(b"\x00\n\r ").decode("utf-8", "replace")
        try:
            return json.loads(txt)
        except ValueError:
            return {"__bruto__": txt[:200]}

    @staticmethod
    def _cmd_bytes(obj):
        if isinstance(obj, str):
            return obj.encode("utf-8") + b"\x0a\x00"
        return json.dumps(obj, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8") + b"\x0a\x00"

    # ---------------- login (uma tentativa, com trava) ----------------
    def _tenta_login(self):
        if not PROCESSO_DA_SESSAO and sessao_separada_rodando():
            self.desistiu = True
            self.ultimo_erro = ("a sessao separada (sessao_xm.py) ja esta logada nesta camera - "
                                "feche a janela dela antes de rodar diagnosticos")
            self.log("NAO vou logar: " + self.ultimo_erro)
            return False
        libera, motivo = liberado_em(self.ip)
        if libera is None:
            self.desistiu = True
            self.ultimo_erro = motivo
            self.log("NAO vou tentar logar: %s" % motivo)
            return False
        if agora() < libera:
            self.proxima_tentativa = libera
            self.ultimo_erro = self.ultimo_erro or motivo
            self.log("aguardando ate %s antes de logar (%s)" % (hora(libera), motivo))
            while agora() < libera and not self._parar.is_set():
                self._parar.wait(1)
            if self._parar.is_set():
                return False

        self.log("conectando em %s:%d (1 tentativa)%s..." % (
            self.ip, PORTA_CAMERA, " saindo por " + IP_LOCAL if IP_LOCAL else ""))
        grava_estado(self.ip, ultima_tentativa=agora(), ultimo_ret="conectando")
        try:
            sock = socket.create_connection((self.ip, PORTA_CAMERA), timeout=6,
                                            source_address=(IP_LOCAL, 0) if IP_LOCAL else None)
        except OSError as e:
            if IP_LOCAL and getattr(e, "errno", None) in (10049, 99):   # IP nao existe mais neste PC
                self.ultimo_erro = "este PC nao esta com o IP %s (XM_IP_LOCAL) - placa de rede caiu?" % IP_LOCAL
            else:
                self.ultimo_erro = "camera nao responde na rede (%s)" % e
            grava_estado(self.ip, ultimo_ret="tcp")
            self.log(self.ultimo_erro)
            return False
        try:
            ip_local = sock.getsockname()[0]
        except OSError:
            ip_local = "?"
        anterior = le_estado().get(self.ip, {}).get("ip_local")
        if anterior and anterior != ip_local:
            self.log("ATENCAO: este PC agora fala com a camera pelo IP %s (antes era %s). "
                     "A camera pode recusar o login (205)." % (ip_local, anterior))
        self.ip_local = ip_local

        try:
            self.sock, self.session, self.seq = sock, 0, 0
            dados = ('{"EncryptType":"MD5","LoginType":"DVRIP-Web",'
                     '"PassWord":"%s","UserName":"%s"}') % (sofia_hash(self.senha), self.usuario)
            self._envia(LOGIN, self._cmd_bytes(dados))
            sock.settimeout(6)
            sessao, _, corpo = self._le_pacote(sock)
            r = self._json(corpo)
        except Exception as e:
            self.ultimo_erro = "login sem resposta: %s" % e
            grava_estado(self.ip, ultimo_ret="sem_resposta")
            registra_recusa(self.ip, self.usuario, "sem resposta (%s)" % e, ip_local=ip_local)
            self._fecha_socket()
            self.log(self.ultimo_erro)
            return False

        ret = r.get("Ret")
        grava_estado(self.ip, ultimo_ret=ret)
        if ret not in (100, 515):
            self.ultimo_erro = "login recusado: %s" % descreve(ret)
            registra_recusa(self.ip, self.usuario, "Ret %s" % ret, r, ip_local=ip_local)
            self._fecha_socket()
            self.log(self.ultimo_erro)
            if ret == 203:
                self.desistiu = True
            return False

        try:
            self.session = int(str(r.get("SessionID", "0")), 16)
        except ValueError:
            self.session = sessao
        self.alive_interval = max(5, int(r.get("AliveInterval", 20) or 20))
        self.conectada = True
        self.desde = agora()
        self.ultimo_erro = ""
        self._ultimo_rx = agora()
        grava_estado(self.ip, ip_local=ip_local)
        self.log("LOGADO  session=0x%08X  keepalive a cada %ds  (este PC: %s)" % (
            self.session, self.alive_interval, ip_local))
        return True

    # ---------------- sentinela (pega o bloqueio no flagrante) ----------------
    def _sonda(self):
        """Login de teste numa conexao separada + logout. Retorna (Ret, resposta) ou (None, erro)."""
        try:
            s = socket.create_connection((self.ip, PORTA_CAMERA), timeout=6,
                                         source_address=(IP_LOCAL, 0) if IP_LOCAL else None)
        except OSError as e:
            return None, str(e)
        try:
            s.settimeout(6)
            corpo = self._cmd_bytes(('{"EncryptType":"MD5","LoginType":"DVRIP-Web",'
                                     '"PassWord":"%s","UserName":"%s"}') % (sofia_hash(self.senha), self.usuario))
            cab = bytearray(20)
            cab[0] = 255
            struct.pack_into("<H", cab, 14, LOGIN)
            struct.pack_into("<I", cab, 16, len(corpo))
            s.sendall(bytes(cab) + corpo)
            _, _, resp = self._le_pacote(s)
            r = self._json(resp)
            if r.get("Ret") in (100, 515):
                sid = str(r.get("SessionID", "0x0"))
                saida = self._cmd_bytes({"Name": "", "SessionID": sid})
                cab = bytearray(20)
                cab[0] = 255
                try:
                    struct.pack_into("<I", cab, 4, int(sid, 16))
                except ValueError:
                    pass
                struct.pack_into("<H", cab, 14, LOGOUT)
                struct.pack_into("<I", cab, 16, len(saida))
                s.sendall(bytes(cab) + saida)
                try:
                    self._le_pacote(s)
                except Exception:
                    pass
            return r.get("Ret"), r
        except Exception as e:
            return None, str(e)
        finally:
            try:
                s.close()
            except Exception:
                pass

    def _flagrante(self, ret, resposta, ip_local):
        """Salva o registro interno da camera (ultimas 3 h) enquanto a sessao ainda esta viva."""
        quando = time.strftime("%Y%m%d_%H%M%S")
        pasta = os.path.dirname(ARQ_RECUSAS)
        entradas = []
        try:
            fim = time.localtime()
            ini = time.localtime(time.time() - 3 * 3600)
            fmt = "%Y-%m-%d %H:%M:%S"
            posicao = 0
            for _ in range(20):
                r = self.comando(1442, {"Name": "OPLogQuery", "SessionID": "0x%08X" % self.session,
                                        "OPLogQuery": {"BeginTime": time.strftime(fmt, ini),
                                                       "EndTime": time.strftime(fmt, fim),
                                                       "LogPosition": posicao, "Type": "LogAll"}}, timeout=12)
                pagina = (r or {}).get("OPLogQuery") or []
                if not isinstance(pagina, list) or not pagina:
                    break
                novas = [e for e in pagina if e not in entradas]
                if not novas:
                    break
                entradas.extend(novas)
                ultima = pagina[-1].get("Position")
                if not isinstance(ultima, int) or ultima + 1 <= posicao:
                    break
                posicao = ultima + 1
        except Exception as e:
            self.log("sentinela: nao consegui ler o registro da camera: %s" % e)
        entradas.sort(key=lambda e: e.get("Position", 0))
        arq = os.path.join(pasta, "%s_FLAGRANTE_%s.json" % (self.nome, quando))
        try:
            os.makedirs(pasta, exist_ok=True)
            with open(arq, "w", encoding="utf-8") as f:
                json.dump({"camera": self.nome, "ip": self.ip, "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "ret_sentinela": ret, "resposta": resposta, "este_pc": ip_local,
                           "registro": entradas}, f, ensure_ascii=False, indent=1)
            self.log("sentinela: registro da camera salvo em %s (%d entradas)" % (arq, len(entradas)))
        except Exception as e:
            self.log("sentinela: nao salvei o flagrante: %s" % e)

    def _sentinela(self):
        sock = self.sock
        while not self._parar.is_set() and self.sock is sock and SENTINELA_S > 0:
            for _ in range(int(SENTINELA_S)):
                if self._parar.is_set() or self.sock is not sock:
                    return
                time.sleep(1)
            ret, r = self._sonda()
            ip_local = getattr(self, "ip_local", "?")
            if ret in (100, 515):
                self.sentinela_ok = getattr(self, "sentinela_ok", 0) + 1
                continue
            if ret is None:
                continue                      # sem rede no momento: tenta na proxima rodada
            self.log("SENTINELA: login de teste recusado com Ret %s (%s) - a sessao ainda esta viva, "
                     "salvando o registro da camera AGORA" % (ret, descreve(ret)))
            registra_recusa(self.ip, self.usuario, "SENTINELA Ret %s (sessao principal ainda logada)" % ret,
                            r, ip_local=ip_local)
            self._flagrante(ret, r, ip_local)
            return                            # nao insiste: nada de tentativas repetidas

    def _fecha_socket(self):
        s, self.sock = self.sock, None
        self.conectada = False
        self.guard_ret = None
        if s:
            try:
                s.close()
            except Exception:
                pass
        with self._resp_cond:
            self._resp_cond.notify_all()

    # ---------------- threads ----------------
    def _leitor(self):
        sock = self.sock
        sock.settimeout(1.0)
        while not self._parar.is_set() and self.sock is sock:
            try:
                _, msgid, corpo = self._le_pacote(sock)
            except socket.timeout:
                continue
            except Exception as e:
                if self.sock is sock and not self._parar.is_set():
                    self.ultimo_erro = "conexao caiu: %s" % e
                    self.log(self.ultimo_erro)
                break
            self._ultimo_rx = agora()
            if msgid == ALARM_INFO:              # alarme empurrado pela camera
                try:
                    self._recebe_alarme(self._json(corpo) if corpo else {})
                except Exception as e:
                    self.log("alarme recebido mas nao entendi: %r" % e)
                continue
            if corpo[:1] == b"{":
                with self._resp_cond:
                    self._respostas[msgid] = self._json(corpo)
                    self._resp_cond.notify_all()
        if self.sock is sock:
            self._fecha_socket()

    def _keepalive(self):
        sock = self.sock
        while not self._parar.is_set() and self.sock is sock:
            for _ in range(self.alive_interval):
                if self._parar.is_set() or self.sock is not sock:
                    return
                time.sleep(1)
            try:
                r = self.comando(KEEPALIVE, {"Name": "KeepAlive",
                                             "SessionID": "0x%08X" % self.session},
                                 timeout=self.alive_interval)
            except ConnectionError:
                return
            if r is None:
                if agora() - self._ultimo_rx > 3 * self.alive_interval:
                    self.ultimo_erro = "keepalive sem resposta - sessao perdida"
                    self.log(self.ultimo_erro)
                    self._fecha_socket()
                    return
            else:
                self.keepalives_ok += 1

    def _rodar(self):
        while not self._parar.is_set():
            if self.desistiu:
                self._acorda.wait()
                self._acorda.clear()
                continue
            caiu = False
            if self._tenta_login():
                self._falha_seguida = 0
                threading.Thread(target=self._leitor, daemon=True).start()
                threading.Thread(target=self._keepalive, daemon=True).start()
                threading.Thread(target=self._sentinela, daemon=True).start()
                try:
                    self.descobrir()
                except Exception as e:
                    self.log("nao li as configuracoes: %s" % e)
                try:
                    self._assina_alarmes()
                except Exception as e:
                    self.log("nao assinei os alertas da camera: %s" % e)
                while self.conectada and not self._parar.is_set():
                    self._parar.wait(0.5)
                if self._parar.is_set():
                    break
                caiu = True
            if self.desistiu:
                continue
            self._falha_seguida += 1
            espera = min(ESPERA_RECONEXAO_MAX,
                         ESPERA_RECONEXAO_BASE * (2 ** (self._falha_seguida - 1)))
            if caiu:
                espera = max(espera, ESPERA_APOS_QUEDA)    # deixa a camera fechar a sessao antiga
            self.proxima_tentativa = agora() + espera
            self.log("nova tentativa as %s" % hora(self.proxima_tentativa))
            self._acorda.wait(espera)
            self._acorda.clear()

    def iniciar(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._rodar, daemon=True)
            self._thread.start()

    def tentar_de_novo(self):
        """Botao 'tentar de novo': libera a trava do 203 e acorda a espera.
        A trava do 205 (15 min) e o intervalo minimo continuam valendo."""
        if self.conectada:
            return
        e = le_estado().get(self.ip, {})
        if e.get("ultimo_ret") == 203:
            grava_estado(self.ip, ultimo_ret="liberado_manual")
        self.desistiu = False
        self._falha_seguida = 0
        self._acorda.set()

    def encerrar(self):
        if self.alerta_ligado and self.conectada:
            try:
                self.set_alerta(False)          # nunca deixa a luz presa acesa
            except Exception:
                pass
        self._parar.set()
        self._parar_fala.set()
        self._acorda.set()
        if self.conectada:
            try:
                self._envia(LOGOUT, self._cmd_bytes(
                    {"Name": "", "SessionID": "0x%08X" % self.session}))
                time.sleep(0.2)
            except Exception:
                pass
        self._fecha_socket()

    # ---------------- alertas da propria camera ----------------
    def _assina_alarmes(self):
        r = self.comando(GUARD_REQ, {"Name": "", "SessionID": "0x%08X" % self.session}, timeout=5)
        self.guard_ret = None if r is None else r.get("Ret")
        if self.guard_ret in (100, 515):
            self.log("ALERTAS da camera assinados (GUARD Ret %s) - deteccao do app chega aqui" % self.guard_ret)
        else:
            self.log("GUARD (assinar alertas) respondeu %s" % (descreve(self.guard_ret) if r else "nada"))
        return self.guard_ret

    def _recebe_alarme(self, j):
        info = j.get("AlarmInfo") if isinstance(j.get("AlarmInfo"), dict) else j
        item = {"ts": agora(), "evento": info.get("Event"), "status": info.get("Status"),
                "canal": info.get("Channel"), "inicio": info.get("StartTime"), "bruto": j}
        with self._trava_alarmes:
            self._alarme_seq += 1
            item["id"] = self._alarme_seq
            self._alarmes.append(item)
        self.log("ALERTA DA CAMERA: evento=%s status=%s canal=%s" % (item["evento"], item["status"], item["canal"]))
        try:
            os.makedirs(os.path.dirname(ARQ_LOG_ALARMES), exist_ok=True)
            with open(ARQ_LOG_ALARMES, "a", encoding="utf-8") as f:
                f.write("%s  %s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), self.nome,
                                          json.dumps(j, ensure_ascii=False)))
        except Exception:
            pass

    # Tipo de deteccao da camera (o mesmo que o app mexe em "Alarme inteligente"):
    #   Detect.HumanDetection[].Enable -> deteccao de corpo humano (filtro de pessoa)
    #   Detect.MotionDetect[].Enable   -> deteccao de movimento
    MODOS_DETECCAO = ("humano", "movimento", "ambos")

    @staticmethod
    def _blocos(v):
        return [b for b in (v if isinstance(v, list) else [v]) if isinstance(b, dict)]

    def deteccao_bruta(self):
        """As duas configs inteiras (o servidor compara e registra o que o app mudou)."""
        return {"Detect.MotionDetect": self.ler("Detect.MotionDetect"),
                "Detect.HumanDetection": self.ler("Detect.HumanDetection")}

    @classmethod
    def resumo_deteccao(cls, bruto):
        """MotionDetect.Enable = chave geral do "Alarme inteligente" (sem ela a
        camera nao avisa nada); HumanDetection.Enable = filtro de pessoa."""
        md = cls._blocos(bruto.get("Detect.MotionDetect"))
        hd = cls._blocos(bruto.get("Detect.HumanDetection"))
        mov = any(b.get("Enable") for b in md)
        hum = any(b.get("Enable") for b in hd)
        modo = "desligado" if not mov else ("humano" if hum else "movimento")
        return {"modo": modo, "ligado": mov, "movimento": mov, "humano": hum,
                "blocos_movimento": len(md), "blocos_humano": len(hd)}

    def modo_deteccao(self):
        return self.resumo_deteccao(self.deteccao_bruta())

    def set_alarme_inteligente(self, ligado):
        """Liga/desliga o "Alarme inteligente" (o mesmo "Ligado" do app)."""
        md = self.ler("Detect.MotionDetect")
        if any(bool(b.get("Enable")) != bool(ligado) for b in self._blocos(md)):
            for b in self._blocos(md):
                b["Enable"] = bool(ligado)
            self.gravar("Detect.MotionDetect", md)
        r = self.modo_deteccao()
        self.log("alarme inteligente %s -> camera agora %s" % ("LIGADO" if ligado else "desligado", r["modo"]))
        return r

    def set_modo_deteccao(self, modo):
        if modo not in self.MODOS_DETECCAO:
            raise ErroXM("modo invalido: %r (use humano, movimento ou ambos)" % modo)
        antes = self.modo_deteccao()
        quer_hum = modo in ("humano", "ambos")
        quer_mov = True          # MotionDetect e a chave geral: os dois modos precisam dela
        hd = self.ler("Detect.HumanDetection")
        if any(bool(b.get("Enable")) != quer_hum for b in self._blocos(hd)):
            for b in self._blocos(hd):
                b["Enable"] = quer_hum
            self.gravar("Detect.HumanDetection", hd)
        if quer_mov:
            md = self.ler("Detect.MotionDetect")
            if any(not b.get("Enable") for b in self._blocos(md)):
                for b in self._blocos(md):
                    b["Enable"] = True
                self.gravar("Detect.MotionDetect", md)
        depois = self.modo_deteccao()
        self.log("modo de deteccao: %s -> pedido %s -> camera agora %s (humano=%s movimento=%s)"
                 % (antes["modo"], modo, depois["modo"], depois["humano"], depois["movimento"]))
        return depois

    def alarmes(self, desde=0):
        """Alertas recebidos com id > desde (o servidor busca so os novos)."""
        try:
            desde = int(desde or 0)
        except (TypeError, ValueError):
            desde = 0
        with self._trava_alarmes:
            itens = [dict(a) for a in self._alarmes if a["id"] > desde]
            ultimo = self._alarme_seq
        return {"boot": self._boot, "ultimo": ultimo, "guard": self.guard_ret,
                "conectada": self.conectada, "itens": itens}

    # ---------------- comandos ----------------
    def comando(self, msgid, obj, timeout=4.0):
        """Envia um JSON e espera a resposta (msgid+1). None se nao veio."""
        if not self.conectada:
            raise ConnectionError("camera nao esta logada (%s)" % (self.ultimo_erro or "conectando"))
        with self._cmd:
            with self._resp_cond:
                self._respostas.pop(msgid + 1, None)
            self._envia(msgid, self._cmd_bytes(obj))
            limite = agora() + timeout
            with self._resp_cond:
                while msgid + 1 not in self._respostas:
                    resta = limite - agora()
                    if resta <= 0 or not self.conectada:
                        return None
                    self._resp_cond.wait(resta)
                return self._respostas.pop(msgid + 1)

    def ler(self, nome):
        r = self.comando(GET_CONFIG, {"Name": nome, "SessionID": "0x%08X" % self.session})
        if r is None:
            raise ErroXM("a camera nao respondeu (%s)" % nome)
        if r.get("Ret") not in (100, 515):
            raise ErroXM("camera recusou ler %s: %s" % (nome, descreve(r.get("Ret"))))
        return r.get(nome)

    def gravar(self, nome, dados):
        r = self.comando(SET_CONFIG, {"Name": nome, "SessionID": "0x%08X" % self.session,
                                      nome: dados})
        if r is None:
            raise ErroXM("a camera nao respondeu (%s)" % nome)
        if r.get("Ret") not in (100, 515):
            raise ErroXM("camera recusou gravar %s: %s" % (nome, descreve(r.get("Ret"))))
        return r

    def descobrir(self):
        """Le volume, luz, alarme, vozes e LED (pela sessao ja aberta)."""
        try:
            v = self.ler("fVideo.Volume")
            self.volume = int(v[0]["LeftVolume"])
        except Exception as e:
            self.log("volume: %s" % e)
        try:
            w = self.ler("Camera.WhiteLight")
            self.luz = {"modo": w.get("WorkMode"), "brilho": w.get("Brightness")}
        except Exception as e:
            self.luz = None
            self.log("luz branca: %s" % e)
        try:
            ab = self.ler("Ability.VoiceTipType") or {}
            self.vozes = [{"id": x.get("VoiceEnum"), "texto": x.get("VoiceText")}
                          for x in ab.get("VoiceTip", []) if "VoiceEnum" in x]
        except Exception as e:
            self.log("vozes: %s" % e)
        try:
            md = self.ler("Detect.MotionDetect")
            blocos = md if isinstance(md, list) else [md]
            eh = (blocos[0] if blocos else {}).get("EventHandler", {})
            voz_on = bool(eh.get("VoiceEnable") and eh.get("TipEnable"))
            self.alarme = {"ligado": voz_on, "voz": eh.get("VoiceType")}
            # auto-reparo: alarme de voz desligado, mas a luz de alerta ainda
            # aciona no movimento (AlarmOutEnable preso de um teste antigo) -> limpa,
            # senão o botão "Desligar" da luz não segura (ela reacende no movimento).
            if not voz_on and any((b.get("EventHandler", {}) if isinstance(b, dict) else {}).get("AlarmOutEnable")
                                  for b in blocos):
                for b in blocos:
                    if isinstance(b, dict):
                        b.setdefault("EventHandler", {})["AlarmOutEnable"] = False
                self.gravar("Detect.MotionDetect", md)
                self.log("a luz de alerta estava acionando no movimento - desliguei isso")
        except Exception as e:
            self.log("alarme: %s" % e)
        try:
            led = self.ler("FbExtraStateCtrl")
            chave = next((k for k in (led or {}) if k.lower() == "ison"), None)
            self._chave_led = chave
            self.led = bool(led[chave]) if chave else None
        except Exception:
            self.led = None           # camera sem esse controle: esconde na pagina
        try:
            cfg = config_luz_alerta(self.ip)
            saida = self.ler(cfg["nome"])
            self.alerta_disponivel = isinstance(saida, list) and len(saida) > 0
            # se ficou presa ligada (servidor caiu com ela acesa), devolve ao normal
            if self.alerta_disponivel and not self.alerta_ligado and \
                    any(i.get("AlarmOutType") == cfg["ligar"].get("AlarmOutType") for i in saida):
                self._grava_saida(cfg, False, saida)
                self.log("luz de alerta estava presa ligada - voltei ao normal")
        except Exception:
            self.alerta_disponivel = False
        self.log("config: volume=%s luz=%s alarme=%s led=%s alerta=%s"
                 % (self.volume, self.luz, self.alarme, self.led, self.alerta_disponivel))

    def set_volume(self, v):
        v = max(0, min(100, int(v)))
        self.gravar("fVideo.Volume", [{"AudioMode": "Single", "LeftVolume": v, "RightVolume": v}])
        self.volume = v
        return v

    def set_luz(self, modo=None, brilho=None):
        w = self.ler("Camera.WhiteLight")
        if modo is not None:
            w["WorkMode"] = str(modo)
        if brilho is not None:
            w["Brightness"] = max(0, min(100, int(brilho)))
        self.gravar("Camera.WhiteLight", w)
        w2 = self.ler("Camera.WhiteLight")          # confirma o que ficou
        self.luz = {"modo": w2.get("WorkMode"), "brilho": w2.get("Brightness")}
        return self.luz

    def set_alarme(self, ligado, voz=None):
        md = self.ler("Detect.MotionDetect")
        for blk in (md if isinstance(md, list) else [md]):
            if not isinstance(blk, dict):
                continue
            eh = blk.setdefault("EventHandler", {})
            if ligado:
                blk["Enable"] = True
                eh["VoiceEnable"] = True
                eh["TipEnable"] = True
                eh["AlarmOutEnable"] = True
                if voz is not None:
                    eh["VoiceType"] = int(voz)
            else:
                eh["VoiceEnable"] = False
                eh["TipEnable"] = False
                eh["AlarmOutEnable"] = False   # senão a luz de alerta fica presa acendendo no movimento
        self.gravar("Detect.MotionDetect", md)
        eh = (md[0] if isinstance(md, list) else md).get("EventHandler", {})
        self.alarme = {"ligado": bool(ligado), "voz": eh.get("VoiceType")}
        return self.alarme

    def set_led(self, ligado):
        led = self.ler("FbExtraStateCtrl")
        chave = next((k for k in (led or {}) if k.lower() == "ison"), None)
        if not chave:
            raise ErroXM("esta camera nao tem controle do LED de status")
        led[chave] = 1 if ligado else 0
        self.gravar("FbExtraStateCtrl", led)
        self.led = bool(ligado)
        return self.led

    # ---------------- luz de alerta (LED vermelho/azul) ----------------
    def _grava_saida(self, cfg, ligar, atual=None):
        atual = atual if atual is not None else self.ler(cfg["nome"])
        if not isinstance(atual, list) or not atual:
            raise ErroXM("esta camera nao tem saida de alarme (luz de alerta)")
        orig = (cfg.get("original") or LUZ_ALERTA_PADRAO["original"])[0]
        novo = []
        for item in atual:
            item = dict(item)
            if ligar:
                item.update(cfg["ligar"])
            else:
                item["AlarmOutType"] = orig.get("AlarmOutType", "AUTO")
                item["AlarmOutStatus"] = orig.get("AlarmOutStatus", "OPEN")
            novo.append(item)
        self.gravar(cfg["nome"], novo)

    def set_alerta(self, ligar, segundos=0):
        """Liga/desliga a luz de alerta. segundos=0 -> ate desligar (max 10 min).
        Desliga sozinha no fim do tempo, mesmo sem a pagina aberta."""
        cfg = config_luz_alerta(self.ip)
        with self._trava_alerta:
            if self._timer_alerta is not None:
                self._timer_alerta.cancel()
                self._timer_alerta = None
            self._grava_saida(cfg, bool(ligar))
            self.alerta_ligado = bool(ligar)
            if ligar:
                dur = ALERTA_MAX_S if not segundos or segundos <= 0 else min(float(segundos), ALERTA_MAX_S)
                self.alerta_ate = agora() + dur
                self._timer_alerta = threading.Timer(dur, self._fim_alerta)
                self._timer_alerta.daemon = True
                self._timer_alerta.start()
            else:
                self.alerta_ate = None
        self.log("luz de alerta %s" % (("LIGADA por %ds" % round(self.alerta_ate - agora()))
                                       if ligar else "desligada"))
        return self.alerta_ligado

    def _fim_alerta(self):
        try:
            self.set_alerta(False)
        except Exception as e:
            self.log("nao consegui apagar a luz de alerta: %s" % e)

    def _json_talk(self, acao):
        return ('{"Name":"OPTalk","SessionID":"0x%08X","OPTalk":{"Action":"%s",'
                '"AudioFormat":{"EncodeType":"G711_ALAW"}}}') % (self.session, acao)

    def _talk(self, msgid, acao, timeout=3.0):
        return self.comando(msgid, self._json_talk(acao), timeout=timeout)

    def parar_fala(self):
        self._parar_fala.set()

    def _abre_aux_logada(self):
        """Modo "login": conexao nova com login, respeitando a trava anti-205."""
        libera = max(self._ultimo_login_fala + 10, 0)
        if agora() < libera:
            time.sleep(libera - agora())
        aux = ConexaoAux(self.ip, 0)
        dados = ('{"EncryptType":"MD5","LoginType":"DVRIP-Web",'
                 '"PassWord":"%s","UserName":"%s"}') % (sofia_hash(self.senha), self.usuario)
        self._ultimo_login_fala = agora()
        r = aux.comando(LOGIN, dados, timeout=6)
        ret = r.get("Ret") if r else None
        if ret not in (100, 515):
            aux.fecha()
            if ret == 205:
                grava_estado(self.ip, ultima_tentativa=agora(), ultimo_ret=205)
            raise ErroXM("login da fala recusado: %s" % (descreve(ret) if ret else "sem resposta"))
        try:
            aux.session = int(str(r.get("SessionID", "0")), 16)
        except ValueError:
            pass
        return aux

    def falar(self, alaw, nome_som="audio", modo=None):
        """Toca audio A-law 8 kHz no alto-falante (bloqueia ate terminar)."""
        modo = modo or self.modo_fala
        if modo not in MODOS_FALA:
            raise ErroXM("modo de fala desconhecido: %s" % modo)
        if not self.conectada:
            raise ConnectionError("camera nao esta logada (%s)" % (self.ultimo_erro or "conectando"))
        if not self._fala.acquire(blocking=False):
            raise ErroXM("ja esta tocando um som nesta camera")
        self._parar_fala.clear()
        aux = None
        diag = {"modo": modo, "claim": None, "start": None, "stop": None}

        def ret(r):
            return r.get("Ret") if isinstance(r, dict) else None

        try:
            # ---- abre o canal ----
            if modo == "mesma":
                r = self._talk(OPTALK_CLAIM, "Claim")
                if ret(r) == 503:
                    self._talk(OPTALK_REQ, "Stop", timeout=1.5)
                    r = self._talk(OPTALK_CLAIM, "Claim")
                diag["claim"] = ret(r)
                if diag["claim"] not in (100, 515):
                    raise ErroXM("camera recusou o canal de voz: %s"
                                 % (descreve(diag["claim"]) if r else "sem resposta"))
                diag["start"] = ret(self._talk(OPTALK_REQ, "Start", timeout=1.5))
                envia = self._envia
            else:
                if modo == "login":
                    aux = self._abre_aux_logada()
                else:
                    aux = ConexaoAux(self.ip, self.session)
                sid = aux.session
                jt = lambda acao: self._json_talk(acao).replace("0x%08X" % self.session, "0x%08X" % sid)
                r = aux.comando(OPTALK_CLAIM, jt("Claim"), timeout=2.0)
                diag["claim"] = ret(r)
                if diag["claim"] == 503 and modo == "sub":
                    self._talk(OPTALK_REQ, "Stop", timeout=1.5)
                    r = aux.comando(OPTALK_CLAIM, jt("Claim"))
                    diag["claim"] = ret(r)
                if r is not None and diag["claim"] not in (100, 515):
                    raise ErroXM("camera recusou o canal de voz: %s" % descreve(diag["claim"]))
                if modo == "sub":
                    diag["start"] = ret(self._talk(OPTALK_REQ, "Start", timeout=1.5))
                else:
                    diag["start"] = ret(aux.comando(OPTALK_REQ, jt("Start"), timeout=1.5))
                envia = aux.envia

            # ---- audio ----
            n = (len(alaw) + CHUNK - 1) // CHUNK
            self.falando = {"som": nome_som, "inicio": agora(), "segundos": round(n * 0.04, 1)}
            t0 = agora()
            enviados = 0
            for k in range(n):
                if self._parar_fala.is_set() or not self.conectada:
                    break
                ped = alaw[k * CHUNK:(k + 1) * CHUNK]
                if len(ped) < CHUNK:
                    ped += bytes([SILENCIO]) * (CHUNK - len(ped))
                envia(OPTALK_DATA, b"\x00\x00\x01\xfa\x0e\x02" + struct.pack("<H", len(ped)) + ped)
                enviados += 1
                espera = t0 + (k + 1) * 0.04 - agora()
                if espera > 0:
                    time.sleep(espera)
            if not self._parar_fala.is_set():
                time.sleep(0.8)                      # termina de tocar o buffer

            # ---- fecha o canal ----
            try:
                if modo in ("mesma", "sub"):
                    diag["stop"] = ret(self._talk(OPTALK_REQ, "Stop", timeout=1.5))
                else:
                    diag["stop"] = ret(aux.comando(OPTALK_REQ, jt("Stop"), timeout=1.5))
            except (ConnectionError, OSError):
                pass
            diag.update({"pacotes": enviados, "interrompido": self._parar_fala.is_set()})
            if aux is not None:
                diag["aux"] = aux.respostas[:8]
            return diag
        finally:
            if aux is not None:
                if modo == "login":
                    try:
                        aux.envia(LOGOUT, self._cmd_bytes({"Name": "", "SessionID": "0x%08X" % aux.session}))
                    except Exception:
                        pass
                aux.fecha()
            self.falando = None
            self.ultima_fala = dict(diag, hora=hora(agora()))
            self._fala.release()

    # ---------------- status para a pagina ----------------
    def status(self):
        libera, motivo = liberado_em(self.ip)
        if self.conectada:
            estado = "conectada"
        elif self.desistiu:
            estado = "parada"
        else:
            estado = "aguardando"
        f = self.falando
        return {
            "estado": estado,
            "logada": self.conectada,
            "ip": self.ip,
            "desde": hora(self.desde) if self.conectada else None,
            "erro": None if self.conectada else (self.ultimo_erro or motivo or "conectando..."),
            "proxima_tentativa": None if self.conectada else hora(max(self.proxima_tentativa, libera or 0)),
            "falando": ({"som": f["som"], "resta": max(0, round(f["segundos"] - (agora() - f["inicio"]), 1))}
                        if f else None),
            "volume": self.volume,
            "luz": self.luz,
            "alarme": self.alarme,
            "vozes": self.vozes,
            "led": self.led,
            "modo_fala": self.modo_fala,
            "alertas_cam": self.guard_ret,
            "ip_local": getattr(self, "ip_local", None),
            "ultima_fala": self.ultima_fala,
            "alerta": ({"ligada": self.alerta_ligado,
                        "resta": max(0, round(self.alerta_ate - agora())) if self.alerta_ligado and self.alerta_ate else None}
                       if self.alerta_disponivel else None),
        }
