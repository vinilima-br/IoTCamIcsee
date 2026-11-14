# -*- coding: utf-8 -*-
"""
elsys_xm.py  -  Sessao com cameras Elsys (login RSA "DVRIP-FutureHome", porta 34567).

Mesma ideia do camera_xm.py (iCSee), mas para as Elsys, que usam login RSA:
  - abre-alas 1413 -> 1414 (chave publica efemera; a camera reveza um punhado delas)
  - login 1000 em TEXTO PURO + \\x00, cabecalho com a sessao do 1414,
    reusando UserName/PassWord capturados + uma CommunicateKey NOSSA (que ciframos
    com a chave da captura). Pegamos a conexao cuja chave bate com a da captura.
  - sessao cifrada: AES-128-CBC, IV=0, chave = a nossa CommunicateKey, base64, +\\x00.
  - falar: Claim(1434 texto puro, conexao aux) -> Start(1430 cifrado) -> audio(1432
    texto puro) -> Stop(1430 cifrado).
  - "alerta" nesta camera = LUZ BRANCA (Camera.WhiteLight), pois ela NAO tem AlarmOut.

Interface compativel com camera_xm.SessaoCamera (o que servidor.py/rosto usam):
  atributos: conectada, falando, alerta_disponivel, alerta_ligado, session
  metodos:   iniciar, encerrar, status, falar, parar_fala, set_alerta, set_luz,
             set_volume, ler, comando, tentar_de_novo

Material por camera (gerado da captura): ao lado, em ferramentas/:
  elsys_<ip>_material.json  (PublicKey, UserName_rsa, PassWord_rsa, alvo_md5_1414)
  elsys_<ip>_abre.bin       (o abre-alas 1413)
"""
import base64
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

PORTA_CAMERA = 34567
CHUNK = 320
SILENCIO = 0xD5
LOGIN, LOGOUT, KEEPALIVE = 1000, 1001, 1006
GET_CONFIG, SET_CONFIG = 1042, 1040
OPTALK_REQ, OPTALK_DATA, OPTALK_CLAIM = 1430, 1432, 1434

MAX_CONEXOES = 15          # conexoes por caçada (a chave da captura reaparece ~1/3)
RETRY_HUNT_S = 300         # espera entre caçadas quando a chave nao aparece (evita martelar)
KEEPALIVE_S = 20
ALERTA_MAX_S = 10 * 60

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_MAT = os.path.join(PASTA, "ferramentas")

# modos de luz branca a tentar para "acender" (o 1o que a camera aceitar vale)
LUZ_ON_MODES = ["KeepOpen", "Open", "Manual"]


class ErroXM(Exception):
    pass


def _nome_ip(ip):
    return ip.replace(".", "_")


# ---------------- G.711 A-law ----------------
def lin2alaw(amostra):
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


def gera_tom(segundos=2.0):
    out = bytearray()
    for n in range(int(8000 * segundos)):
        t = n / 8000.0
        f = 1000 if int(t / 0.25) % 2 == 0 else 1500
        amp = 22000 if (t % 0.25) < 0.2 else 0
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
    ff = acha_ffmpeg()
    if not ff:
        raise ErroXM("ffmpeg nao encontrado (pip install imageio-ffmpeg)")
    r = subprocess.run([ff, "-loglevel", "error", "-i", caminho, "-ac", "1",
                        "-ar", "8000", "-f", "alaw", "pipe:1"], capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise ErroXM("falha ao converter: %s" % r.stderr.decode("utf-8", "replace")[-200:])
    return r.stdout


# ---------------- RSA (puro-python) + AES ----------------
def rsa_pkcs1v15(msg, N, e):
    k = (N.bit_length() + 7) // 8
    ps = bytearray()
    while len(ps) < k - 3 - len(msg):
        b = os.urandom(1)
        if b[0] != 0:
            ps.append(b[0])
    em = b"\x00\x02" + bytes(ps) + b"\x00" + msg
    return pow(int.from_bytes(em, "big"), e, N).to_bytes(k, "big")


def _aes():
    from Crypto.Cipher import AES
    return AES


# ---------------- DVRIP baixo nivel ----------------
def _recv_frame(sock, timeout=4):
    sock.settimeout(timeout)
    cab = b""
    try:
        while len(cab) < 20:
            ch = sock.recv(20 - len(cab))
            if not ch:
                return None, 0, b""
            cab += ch
    except (socket.timeout, OSError):
        return None, 0, b""
    sess = struct.unpack_from("<I", cab, 4)[0]
    mid = struct.unpack_from("<H", cab, 14)[0]
    tam = struct.unpack_from("<I", cab, 16)[0]
    corpo = b""
    while len(corpo) < tam:
        try:
            ch = sock.recv(min(65536, tam - len(corpo)))
        except (socket.timeout, OSError):
            break
        if not ch:
            break
        corpo += ch
    return mid, sess, corpo


def _frame(msgid, payload, sessao=0, seq=0):
    cab = bytearray(20)
    cab[0] = 255
    struct.pack_into("<I", cab, 4, sessao)
    struct.pack_into("<I", cab, 8, seq)
    struct.pack_into("<H", cab, 14, msgid)
    struct.pack_into("<I", cab, 16, len(payload))
    return bytes(cab) + payload


class ElsysSessao:
    def __init__(self, cid, ip, usuario="admin", senha="", log=print,
                 chave_sessao=b"ABCDEF0123456789"):
        self.cid = cid
        self.ip = ip
        self.usuario = usuario
        self.senha = senha           # nao usado (login e por material capturado)
        self._log = log
        self.K = chave_sessao if isinstance(chave_sessao, bytes) else chave_sessao.encode()
        # material da camera
        base = os.path.join(PASTA_MAT, "elsys_%s" % _nome_ip(ip))
        self._mat = json.load(open(base + "_material.json"))
        self._abre = open(base + "_abre.bin", "rb").read()
        mod_hex, exp_hex = self._mat["PublicKey"].split(",")
        self._N, self._e = int(mod_hex, 16), int(exp_hex, 16)
        self._alvo = self._mat["alvo_md5_1414"]
        # estado
        self.sock = None
        self.session = 0
        self.conectada = False
        self.falando = None
        self.alerta_disponivel = True     # luz branca
        self.alerta_ligado = False
        self.ultimo_erro = None
        self._luz_original = None
        self._trava = threading.RLock()
        self._fala = threading.Lock()
        self._parar = threading.Event()
        self._fim = threading.Event()
        self._t_ka = None
        self._apaga_em = 0.0

    def log(self, m):
        try:
            self._log("[elsys:%s] %s" % (self.cid, m))
        except Exception:
            pass

    # ---------------- cifra da sessao ----------------
    def _enc(self, body_bytes):
        AES = _aes()
        data = body_bytes + b"\x00" * ((-len(body_bytes)) % 16)
        return AES.new(self.K, AES.MODE_CBC, b"\x00" * 16).encrypt(data)

    def _dec(self, cipher):
        AES = _aes()
        return AES.new(self.K, AES.MODE_CBC, b"\x00" * 16).decrypt(cipher)

    def _cmd(self, msgid, body_json, timeout=6):
        """Comando cifrado na sessao principal. Retorna dict ou None."""
        payload = base64.b64encode(self._enc(body_json.encode() + b"\x00")) + b"\x00"
        self.sock.sendall(_frame(msgid, payload, sessao=self.session))
        mid, sess, corpo = _recv_frame(self.sock, timeout)
        if mid is None:
            return None
        s = corpo.rstrip(b"\x00\r\n ")
        # resposta pode vir cifrada (base64) ou em texto (erros 117 etc.)
        if s[:1] in (b"{", b"["):
            try:
                return json.loads(s.decode("utf-8", "replace"))
            except Exception:
                return None
        try:
            plain = self._dec(base64.b64decode(s + b"=" * (-len(s) % 4))).rstrip(b"\x00\r\n ")
            return json.loads(plain.decode("utf-8", "replace"))
        except Exception:
            return None

    # ---------------- login forjado ----------------
    def _forja(self):
        ck = rsa_pkcs1v15(self.K, self._N, self._e).hex().upper()
        login = {"EncryptType": "MD5", "LoginType": "DVRIP-FutureHome",
                 "UserName": self._mat["UserName_rsa"], "PassWord": self._mat["PassWord_rsa"],
                 "CommunicateKey": ck}
        lb = json.dumps(login, separators=(",", ":")).encode() + b"\x00"
        for _ in range(MAX_CONEXOES):
            try:
                s = socket.create_connection((self.ip, PORTA_CAMERA), timeout=6)
            except OSError:
                time.sleep(0.8)
                continue
            s.sendall(self._abre)
            s14 = None
            for _ in range(4):
                mid, sess, corpo = _recv_frame(s, 3)
                if mid is None:
                    break
                if mid == 1414:
                    if hashlib.md5(corpo.rstrip(b"\x00\r\n ")).hexdigest() == self._alvo:
                        s14 = sess
                    break
            if s14 is None:
                s.close()
                time.sleep(0.4)
                continue
            s.sendall(_frame(LOGIN, lb, sessao=s14))
            for _ in range(5):
                mid, sess, corpo = _recv_frame(s, 6)
                if mid == 1001:
                    try:
                        j = json.loads(corpo.rstrip(b"\x00\r\n ").decode())
                        if j.get("Ret") == 100:
                            self.sock = s
                            self.session = int(str(j.get("SessionID")), 16)
                            return True
                    except Exception:
                        pass
                if mid is None:
                    break
            s.close()
        return False

    def iniciar(self):
        """Nao bloqueia: sobe um worker que forja a sessao, mantem viva e re-forja
        sozinho. conectada vira True quando a sessao esta pronta."""
        with self._trava:
            if self._t_ka and self._t_ka.is_alive():
                return True
            self._fim.clear()
            self._t_ka = threading.Thread(target=self._worker, daemon=True)
            self._t_ka.start()
        return True

    def aguardar(self, timeout=40):
        """Espera a sessao ficar pronta (para testes/uso sincrono). True se conectou."""
        fim = time.time() + timeout
        while time.time() < fim:
            if self.conectada:
                return True
            if self._fim.is_set():
                return False
            time.sleep(0.5)
        return self.conectada

    def _worker(self):
        while not self._fim.is_set():
            if not self.conectada:
                self.log("forjando sessao (cacando a chave da captura)...")
                with self._trava:
                    ok = self._forja()
                    self.conectada = ok
                if ok:
                    self.ultimo_erro = None
                    self.log("sessao OK (SID=0x%X)" % self.session)
                else:
                    self.ultimo_erro = "chave da captura nao apareceu (revezamento) - tentando de novo"
                    self.log(self.ultimo_erro)
                    self._fim.wait(RETRY_HUNT_S)      # espera antes de nova caçada
                    continue
            # conectada: keepalive + apaga a luz no tempo
            if self._fim.wait(KEEPALIVE_S):
                break
            with self._trava:
                if not self.conectada:
                    continue
                if self.alerta_ligado and self._apaga_em and time.time() >= self._apaga_em:
                    try:
                        self._luz(False)
                    except Exception:
                        pass
                try:
                    r = self._cmd(KEEPALIVE, '{"Name":"KeepAlive","SessionID":"0x%08X"}' % self.session, timeout=5)
                    if r is None:
                        raise ConnectionError("keepalive sem resposta")
                except Exception as e:
                    self.log("keepalive falhou (%s); vou re-forjar..." % e)
                    try:
                        if self.sock:
                            self.sock.close()
                    except Exception:
                        pass
                    self.conectada = False
                    self.session = 0

    def encerrar(self):
        self._fim.set()
        with self._trava:
            try:
                if self.conectada and self.alerta_ligado:
                    self._luz(False)
            except Exception:
                pass
            try:
                if self.sock:
                    self.sock.sendall(_frame(LOGOUT, json.dumps({"Name": "", "SessionID": "0x%08X" % self.session}).encode() + b"\x00", sessao=self.session))
                    time.sleep(0.15)
            except Exception:
                pass
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass
            self.conectada = False

    # ---------------- falar ----------------
    def _json_talk(self, acao):
        return ('{"Name":"OPTalk","SessionID":"0x%08X","OPTalk":{"Action":"%s",'
                '"AudioFormat":{"BitRate":0,"EncodeType":"G711_ALAW","SampleBit":8,"SampleRate":8}}}'
                % (self.session, acao))

    def falar(self, alaw, nome_som="audio", modo=None):
        if not self.conectada:
            self.iniciar()
            self.aguardar(12)
        if not self.conectada:
            raise ConnectionError("sessao Elsys nao conectou (%s)" % (self.ultimo_erro or ""))
        if not self._fala.acquire(blocking=False):
            raise ErroXM("ja esta tocando um som nesta camera")
        self._parar.clear()
        self.falando = nome_som
        aux = None
        enviados, interrompido = 0, False
        try:
            with self._trava:
                aux = socket.create_connection((self.ip, PORTA_CAMERA), timeout=6)
                aux.sendall(_frame(OPTALK_CLAIM, self._json_talk("Claim").encode() + b"\x00", sessao=self.session))
                _recv_frame(aux, 3)
                self._cmd(OPTALK_REQ, self._json_talk("Start"))
            time.sleep(0.15)
            n = (len(alaw) + CHUNK - 1) // CHUNK
            for k in range(n):
                if self._parar.is_set():
                    interrompido = True
                    break
                ped = alaw[k * CHUNK:(k + 1) * CHUNK]
                if len(ped) < CHUNK:
                    ped += bytes([SILENCIO]) * (CHUNK - len(ped))
                pkt = b"\x00\x00\x01\xfa\x0e\x02" + struct.pack("<H", len(ped)) + ped
                aux.sendall(_frame(OPTALK_DATA, pkt, sessao=self.session))
                enviados += 1
                time.sleep(0.037)
            time.sleep(0.25)
            with self._trava:
                self._cmd(OPTALK_REQ, self._json_talk("Stop"))
            # mesmo formato de retorno do camera_xm.falar (o servidor le estas chaves)
            return {"ok": True, "modo": "elsys-rsa", "claim": True, "start": True,
                    "stop": True, "pacotes": enviados, "interrompido": interrompido,
                    "segundos": round(len(alaw) / 8000.0, 1)}
        finally:
            self.falando = None
            try:
                if aux:
                    aux.close()
            except Exception:
                pass
            self._fala.release()

    def falar_arquivo(self, caminho):
        return self.falar(arquivo_para_alaw(caminho), nome_som=os.path.basename(caminho))

    def parar_fala(self):
        self._parar.set()

    # ---------------- luz branca (= "alerta") ----------------
    def _get(self, nome):
        r = self._cmd(GET_CONFIG, '{"Name":"%s","SessionID":"0x%08X"}' % (nome, self.session))
        if r and r.get("Ret") in (100, 515):
            return r.get(nome)
        return None

    def _set(self, nome, valor):
        body = json.dumps({"Name": nome, nome: valor, "SessionID": "0x%08X" % self.session})
        r = self._cmd(SET_CONFIG, body)
        return r.get("Ret") if isinstance(r, dict) else None

    def _luz(self, ligar):
        wl = self._get("Camera.WhiteLight")
        if not isinstance(wl, dict):
            raise ErroXM("camera nao tem luz branca controlavel")
        if ligar:
            if self._luz_original is None:
                # guarda o estado pra restaurar depois
                self._luz_original = {"WorkMode": wl.get("WorkMode", "Auto")}
                if isinstance(wl.get("WorkPeriod"), dict):
                    self._luz_original["Enable"] = wl["WorkPeriod"].get("Enable", 1)
            for modo in LUZ_ON_MODES:
                novo = dict(wl)
                novo["WorkMode"] = modo
                novo["Brightness"] = 100
                # tira a janela de horario (18h-06h), senao de dia nao acende
                if isinstance(novo.get("WorkPeriod"), dict):
                    wp = dict(novo["WorkPeriod"])
                    wp["Enable"] = 0
                    novo["WorkPeriod"] = wp
                ret = self._set("Camera.WhiteLight", novo)
                if ret in (100, 515):
                    self.alerta_ligado = True
                    self.log("luz branca LIGADA (modo %s)" % modo)
                    return True
            raise ErroXM("a camera recusou os modos de luz branca %s" % LUZ_ON_MODES)
        else:
            orig = self._luz_original or {}
            novo = dict(wl)
            novo["WorkMode"] = orig.get("WorkMode", "Auto")
            if isinstance(novo.get("WorkPeriod"), dict) and "Enable" in orig:
                wp = dict(novo["WorkPeriod"])
                wp["Enable"] = orig["Enable"]
                novo["WorkPeriod"] = wp
            self._set("Camera.WhiteLight", novo)
            self.alerta_ligado = False
            self.log("luz branca restaurada (%s)" % novo["WorkMode"])
            return True

    def set_alerta(self, ligar, segundos=0):
        """Compat com iCSee: aqui o 'alerta' e a LUZ BRANCA. BEST-EFFORT: esta Elsys
        so acende a luz branca de NOITE (trava de hardware de dia), e nao tem LED
        de alerta controlavel. Entao nunca estouramos erro aqui - o 'negado' usa a
        VOZ como sinal principal, e a luz pisca quando a camera deixa (a noite)."""
        if not self.conectada and not self.iniciar():
            raise ConnectionError("sessao Elsys nao conectou")
        with self._trava:
            try:
                if ligar:
                    self._luz(True)
                    self._apaga_em = time.time() + min(segundos or 10, ALERTA_MAX_S) if segundos else 0.0
                else:
                    self._apaga_em = 0.0
                    self._luz(False)
            except Exception as e:
                self.log("luz branca best-effort (%s)" % e)
        return {"ok": True, "alerta_ligado": self.alerta_ligado}

    def set_luz(self, modo=None, brilho=None):
        with self._trava:
            wl = self._get("Camera.WhiteLight")
            if not isinstance(wl, dict):
                raise ErroXM("sem luz branca")
            if modo is not None:
                wl["WorkMode"] = modo
            if brilho is not None:
                wl["Brightness"] = int(brilho)
            ret = self._set("Camera.WhiteLight", wl)
            return {"ok": ret in (100, 515), "ret": ret, "WorkMode": wl.get("WorkMode")}

    def set_volume(self, v):
        with self._trava:
            cur = self._get("fVideo.Volume")
            val = [{"LeftVolume": int(v), "RightVolume": int(v)}]
            if isinstance(cur, list) and cur and isinstance(cur[0], dict):
                cur[0].update({"LeftVolume": int(v), "RightVolume": int(v)})
                val = cur
            ret = self._set("fVideo.Volume", val)
            return {"ok": ret in (100, 515), "ret": ret}

    def ler(self, nome):
        with self._trava:
            return self._get(nome)

    def comando(self, msgid, obj, timeout=4.0):
        with self._trava:
            return self._cmd(int(msgid), obj if isinstance(obj, str) else json.dumps(obj), timeout=timeout)

    def tentar_de_novo(self):
        return self._reconecta()

    def gravar(self, nome, dados):
        with self._trava:
            ret = self._set(nome, dados)
            return {"ok": ret in (100, 515), "ret": ret}

    def set_alarme(self, ligado, voz=None):
        raise ErroXM("o alarme desta Elsys não é configurável por aqui (use a luz branca/fala)")

    def set_led(self, ligado):
        raise ErroXM("esta Elsys não tem LED de status controlável")

    def descobrir(self):
        return {"ok": True, "info": "Elsys usa RTSP direto (sem ONVIF)"}

    def status(self):
        return {"estado": "logada" if self.conectada else "aguardando",
                "logada": self.conectada, "ip": self.ip, "falando": self.falando,
                "alerta": self.alerta_ligado, "alerta_disponivel": True,
                "erro": self.ultimo_erro, "modo_fala": "elsys-rsa",
                "luz": None, "alarme": None, "vozes": [], "led": None, "volume": None}
