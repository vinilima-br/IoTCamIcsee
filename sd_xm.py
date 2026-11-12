# -*- coding: utf-8 -*-
"""
sd_xm.py  -  Gravacoes do cartao SD das cameras XM/iCSee (porta 34567).

Usa a sessao ja logada (camera_xm.SessaoCamera), sem login extra, e:
  - le o cartao (tamanho/livre) e a hora da camera
  - lista as gravacoes de um periodo (OPFileQuery, 64 por pagina)
  - baixa uma gravacao (OPPlayBack Claim 1424 + DownloadStart 1420)
  - tira os cabecalhos proprietarios XM e gera um .mp4

Formas de baixar (o diag_sd descobre qual a camera aceita e salva em
xm_sd_modo.json, igual a fala):
  "sub"      conexao auxiliar SEM login: Claim nela, Start/Stop na sessao
  "sub_tudo" conexao auxiliar SEM login: tudo nela
  "login"    conexao nova COM login (como a biblioteca python-dvr faz)
"""
import json
import os
import re
import socket
import struct
import subprocess
import threading
import time
from datetime import datetime, timedelta

import camera_xm as xm

PASTA_BASE = os.path.dirname(os.path.abspath(__file__))
PASTA_SD = os.path.join(PASTA_BASE, "sd_baixados")
ARQ_MODO_SD = os.path.join(PASTA_BASE, "xm_sd_modo.json")
MODOS_SD = ("sub", "sub_tudo", "login")
FORMATO = "%Y-%m-%d %H:%M:%S"

SYSINFO, TIME_QUERY = 1020, 1452
FILE_QUERY = 1440
PLAY_REQ, PLAY_CLAIM = 1420, 1424

TIPOS = {"R": "Contínua", "M": "Movimento", "A": "Alarme", "H": "Manual"}


class ErroSD(Exception):
    pass


def _hex(v):
    try:
        return int(str(v), 16)
    except (TypeError, ValueError):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0


def modo_salvo(ip):
    try:
        with open(ARQ_MODO_SD, "r", encoding="utf-8") as f:
            m = json.load(f).get(ip)
        return m if m in MODOS_SD else None
    except Exception:
        return None


def salva_modo(ip, modo):
    try:
        with open(ARQ_MODO_SD, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d[ip] = modo
    with open(ARQ_MODO_SD, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


# ------------------------------------------------------------------
#  Consultas pela sessao
# ------------------------------------------------------------------
def _cmd(sessao, msgid, nome, extra=None, timeout=8.0):
    corpo = {"Name": nome, "SessionID": "0x%08X" % sessao.session}
    if extra:
        corpo.update(extra)
    r = sessao.comando(msgid, corpo, timeout=timeout)
    if r is None:
        raise ErroSD("a camera nao respondeu (%s)" % nome)
    return r


def hora_camera(sessao):
    r = _cmd(sessao, TIME_QUERY, "OPTimeQuery")
    try:
        return datetime.strptime(r.get("OPTimeQuery", ""), FORMATO)
    except ValueError:
        return None


def armazenamento(sessao):
    """{"total_mb", "livre_mb", "discos"} ou None se nao tiver cartao."""
    r = _cmd(sessao, SYSINFO, "StorageInfo")
    if r.get("Ret") not in (100, 515):
        return None
    total = livre = 0
    discos = 0
    for disco in r.get("StorageInfo") or []:
        discos += 1
        for p in disco.get("Partition", []) or []:
            total += _hex(p.get("TotalSpace"))
            livre += _hex(p.get("RemainSpace"))
    if not total:
        return None
    return {"total_mb": total, "livre_mb": livre, "discos": discos}


def _tipo(nome):
    m = re.findall(r"\[([A-Za-z])\]", nome or "")
    return TIPOS.get(m[0].upper(), m[0]) if m else "?"


def listar(sessao, inicio, fim, tipo="h264", limite=2000):
    """Lista as gravacoes entre dois datetime (mais recentes primeiro)."""
    vistos, arquivos = set(), []
    comeco = inicio.strftime(FORMATO)
    for _ in range(60):                       # 60 paginas x 64 = bem mais que o limite
        r = _cmd(sessao, FILE_QUERY, "OPFileQuery", {"OPFileQuery": {
            "BeginTime": comeco, "EndTime": fim.strftime(FORMATO), "Channel": 0,
            "DriverTypeMask": "0x0000FFFF", "Event": "*", "StreamType": "0x00000000",
            "Type": tipo}}, timeout=12)
        if r.get("Ret") not in (100, 515):
            break                              # 119/sem resultado = acabou
        pagina = r.get("OPFileQuery") or []
        novos = 0
        for item in pagina:
            nome = item.get("FileName")
            if not nome or nome in vistos:
                continue
            vistos.add(nome)
            novos += 1
            arquivos.append({
                "nome": nome,
                "inicio": item.get("BeginTime"),
                "fim": item.get("EndTime"),
                "kb": _hex(item.get("FileLength")),
                "tipo": _tipo(nome),
            })
        if len(pagina) < 64 or not novos or len(arquivos) >= limite:
            break
        comeco = pagina[-1].get("BeginTime") or comeco
    arquivos.sort(key=lambda a: a["inicio"] or "", reverse=True)
    return arquivos


def nome_local(arquivo):
    """'/idea0/2026-11-09/001/10.59.58-11.00.36[M][@20b4][0].h264' -> '2026-11-09_10-59-58_M'"""
    ini = (arquivo.get("inicio") or "").replace(":", "-").replace(" ", "_")
    base = ini or re.sub(r"[^A-Za-z0-9]+", "_", arquivo.get("nome", "video"))[-40:]
    tipo = re.findall(r"\[([A-Za-z])\]", arquivo.get("nome", ""))
    return re.sub(r"[^A-Za-z0-9_-]", "_", base + ("_" + tipo[0].upper() if tipo else ""))


# ------------------------------------------------------------------
#  Download
# ------------------------------------------------------------------
def _json_play(session, acao, arquivo, claim=False):
    p = {"PlayMode": "ByName", "FileName": arquivo["nome"], "StreamType": 0,
         "Value": 0, "TransMode": "TCP"}
    if not claim:
        p["Channel"] = 0
    return json.dumps({"Name": "OPPlayBack", "SessionID": "0x%08X" % session,
                       "OPPlayBack": {"Action": acao, "Parameter": p,
                                      "StartTime": arquivo["inicio"], "EndTime": arquivo["fim"]}},
                      separators=(",", ":"))


class _Canal:
    """Socket cru para o download (le pacotes de midia e JSON)."""

    def __init__(self, ip, session=0):
        self.sock = socket.create_connection((ip, xm.PORTA_CAMERA), timeout=8)
        self.session = session
        self.seq = 0

    def envia(self, msgid, texto):
        payload = texto.encode("utf-8") + b"\x0a\x00"
        cab = bytearray(20)
        cab[0] = 255
        struct.pack_into("<I", cab, 4, self.session)
        struct.pack_into("<I", cab, 8, self.seq)
        struct.pack_into("<H", cab, 14, msgid)
        struct.pack_into("<I", cab, 16, len(payload))
        self.sock.sendall(bytes(cab) + payload)
        self.seq += 1

    def _exato(self, n, ocioso):
        buf = bytearray()
        ultimo = time.time()
        while len(buf) < n:
            try:
                b = self.sock.recv(min(65536, n - len(buf)))
            except socket.timeout:
                if time.time() - ultimo > ocioso:
                    raise
                continue
            if not b:
                raise ConnectionError("a camera fechou a conexao")
            buf += b
            ultimo = time.time()
        return bytes(buf)

    def pacote(self, ocioso=10.0):
        self.sock.settimeout(1.0)
        cab = self._exato(20, ocioso)
        if cab[0] != 255:
            raise ConnectionError("pacote invalido")
        sid = struct.unpack_from("<I", cab, 4)[0]
        msgid = struct.unpack_from("<H", cab, 14)[0]
        tam = struct.unpack_from("<I", cab, 16)[0]
        corpo = self._exato(tam, ocioso) if tam else b""
        return sid, msgid, corpo

    def resposta(self, msgid_esperado, timeout=6.0):
        """Le pacotes ate a resposta JSON esperada (ignora o resto)."""
        limite = time.time() + timeout
        while time.time() < limite:
            try:
                sid, mid, corpo = self.pacote(ocioso=max(0.5, limite - time.time()))
            except socket.timeout:
                return None
            if corpo[:1] == b"{":
                j = xm.SessaoCamera._json(corpo)
                if mid == msgid_esperado:
                    if sid and not self.session:
                        self.session = sid
                    return j
        return None

    def fecha(self):
        try:
            self.sock.close()
        except Exception:
            pass


def baixar(sessao, arquivo, destino, modo="sub", progresso=None, parar=None):
    """Baixa o arquivo bruto do SD. Retorna {"bytes", "segundos", "modo", ...}.
    progresso(bytes_recebidos, bytes_esperados) e chamado durante o download."""
    if modo not in MODOS_SD:
        raise ErroSD("modo desconhecido: %s" % modo)
    esperado = arquivo.get("kb", 0) * 1024
    canal = None
    info = {"modo": modo, "claim": None, "start": None}
    os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
    try:
        # ---- abre o canal ----
        if modo == "login":
            canal = _Canal(sessao.ip, 0)
            dados = ('{"EncryptType":"MD5","LoginType":"DVRIP-Web",'
                     '"PassWord":"%s","UserName":"%s"}') % (xm.sofia_hash(sessao.senha), sessao.usuario)
            canal.envia(xm.LOGIN, dados)
            r = canal.resposta(xm.LOGIN + 1)
            if not r or r.get("Ret") not in (100, 515):
                raise ErroSD("login do download recusado: %s" % (xm.descreve(r.get("Ret")) if r else "sem resposta"))
            try:
                canal.session = int(str(r.get("SessionID", "0")), 16)
            except ValueError:
                pass
        else:
            canal = _Canal(sessao.ip, sessao.session)

        canal.envia(PLAY_CLAIM, _json_play(canal.session, "Claim", arquivo, claim=True))
        r = canal.resposta(PLAY_CLAIM + 1, timeout=5)
        info["claim"] = r.get("Ret") if r else None
        if r is not None and info["claim"] not in (100, 515):
            raise ErroSD("camera recusou o download (Claim): %s" % xm.descreve(info["claim"]))

        if modo == "sub":
            r = sessao.comando(PLAY_REQ, _json_play(sessao.session, "DownloadStart", arquivo), timeout=6)
            info["start"] = r.get("Ret") if r else None
        else:
            canal.envia(PLAY_REQ, _json_play(canal.session, "DownloadStart", arquivo))
        if info["start"] is not None and info["start"] not in (100, 515):
            raise ErroSD("camera recusou o download (Start): %s" % xm.descreve(info["start"]))

        # ---- recebe ----
        total = 0
        t0 = time.time()
        ultimo_aviso = 0
        with open(destino, "wb") as f:
            while True:
                if parar is not None and parar.is_set():
                    info["interrompido"] = True
                    break
                try:
                    sid, mid, corpo = canal.pacote(ocioso=8.0 if total else 12.0)
                except socket.timeout:
                    info["fim"] = "parou de chegar dados"
                    break
                except ConnectionError as e:
                    info["fim"] = str(e)
                    break
                if not corpo:
                    info["fim"] = "pacote final"
                    break
                if corpo[:1] == b"{":
                    j = xm.SessaoCamera._json(corpo)
                    if mid == PLAY_REQ + 1:
                        info["start"] = j.get("Ret")
                        if info["start"] not in (100, 515):
                            raise ErroSD("camera recusou o download (Start): %s" % xm.descreve(info["start"]))
                    continue
                f.write(corpo)
                total += len(corpo)
                if progresso and time.time() - ultimo_aviso > 0.5:
                    progresso(total, esperado)
                    ultimo_aviso = time.time()
        info.update({"bytes": total, "segundos": round(time.time() - t0, 1), "esperado": esperado})
        if progresso:
            progresso(total, esperado)
        return info
    finally:
        if canal is not None:
            try:
                if modo == "sub":
                    sessao.comando(PLAY_REQ, _json_play(sessao.session, "DownloadStop", arquivo), timeout=2)
                else:
                    canal.envia(PLAY_REQ, _json_play(canal.session, "DownloadStop", arquivo))
                    if modo == "login":
                        canal.envia(xm.LOGOUT, json.dumps({"Name": "", "SessionID": "0x%08X" % canal.session}))
                    time.sleep(0.2)
            except Exception:
                pass
            canal.fecha()


# ------------------------------------------------------------------
#  Formato XM -> MP4
# ------------------------------------------------------------------
#  O arquivo do SD nao e H.264 "puro": cada quadro tem um cabecalho XM:
#   00 00 01 FC + 12 bytes  -> quadro I (codec, fps, largura/8, altura/8, data, tamanho)
#   00 00 01 FD +  4 bytes  -> quadro P (tamanho)
#   00 00 01 FA +  4 bytes  -> audio (tipo, taxa, tamanho 2 bytes) - 0x0E = G.711 A-law
#   00 00 01 F9 +  4 bytes  -> informacao extra (ignorado)
#   00 00 01 FE + 12 bytes  -> foto JPEG (ignorado)
_MARCADOR = re.compile(b"\x00\x00\x01[\xf9\xfa\xfc\xfd\xfe]")
_CODECS = {1: "mpeg4", 2: "h264", 3: "h265"}


def _data_xm(v):
    try:
        return datetime(((v & 0xFC000000) >> 26) + 2000, (v & 0x3C00000) >> 22, (v & 0x3E0000) >> 17,
                        (v & 0x1F000) >> 12, (v & 0xFC0) >> 6, v & 0x3F).strftime(FORMATO)
    except ValueError:
        return None


def _seg_xm(v):
    return ((v & 0x1F000) >> 12) * 3600 + ((v & 0xFC0) >> 6) * 60 + (v & 0x3F)


def extrair(caminho_bruto, caminho_video, caminho_audio):
    with open(caminho_bruto, "rb") as f:
        dados = f.read()
    info = {"codec": None, "fps": 0, "fps_cabecalho": 0, "quadros_i": 0,
            "quadros_p": 0, "bytes_audio": 0, "bytes_ignorados": 0, "inicio_gravacao": None}
    n, pos = len(dados), 0
    quadros = 0
    marcas = []                     # (quadros antes deste I, segundos do relogio XM)
    ultimo_video = False            # o bloco anterior era um quadro de video?
    info["bytes_recuperados"] = 0
    with open(caminho_video, "wb") as sv, open(caminho_audio, "wb") as sa:
        while pos + 8 <= n:
            if not (dados[pos:pos + 3] == b"\x00\x00\x01" and dados[pos + 3] in (0xF9, 0xFA, 0xFC, 0xFD, 0xFE)):
                m = _MARCADOR.search(dados, pos + 1)
                fim_sobra = m.start() if m else n
                sobra = dados[pos:fim_sobra]
                if ultimo_video and sobra.strip(b"\xff\x00"):
                    # a camera as vezes grava no cabecalho um tamanho MENOR que o
                    # quadro: o resto vem logo em seguida -> devolve ao quadro
                    sv.write(sobra)
                    info["bytes_recuperados"] += len(sobra)
                else:
                    info["bytes_ignorados"] += len(sobra)
                ultimo_video = False
                if m is None:
                    break
                pos = m.start()
                continue
            t = dados[pos + 3]
            if t in (0xFC, 0xFE):
                if pos + 16 > n:
                    break
                media, fps, _l8, _a8, data, comp = struct.unpack_from("<BBBBII", dados, pos + 4)
                cab = 16
            elif t == 0xFD:
                (comp,) = struct.unpack_from("<I", dados, pos + 4)
                media, cab = None, 8
            else:
                media, _x, comp = struct.unpack_from("<BBH", dados, pos + 4)
                cab = 8
            ini = pos + cab
            fim = min(ini + comp, n)
            conteudo = dados[ini:fim]
            ultimo_video = t in (0xFC, 0xFD)
            if t == 0xFC:
                info["quadros_i"] += 1
                if info["codec"] is None:
                    # o nibble baixo e o codec; o alto sao flags (ex.: 0x52 = H.264)
                    info["codec"] = _CODECS.get(media & 0x0F, "desconhecido(%s)" % media)
                    info["fps_cabecalho"] = fps
                    info["inicio_gravacao"] = _data_xm(data)
                marcas.append((quadros, _seg_xm(data)))
                sv.write(conteudo)
                quadros += 1
            elif t == 0xFD:
                info["quadros_p"] += 1
                sv.write(conteudo)
                quadros += 1
            elif t == 0xFA:
                info["bytes_audio"] += len(conteudo)
                if media == 0x0E:
                    sa.write(conteudo)
            pos = max(fim, pos + 1)
    # fps real pelo relogio gravado nos quadros I (o do cabecalho e arredondado)
    fps = info["fps_cabecalho"] or 15
    if len(marcas) >= 2:
        dq = marcas[-1][0] - marcas[0][0]
        ds = marcas[-1][1] - marcas[0][1]
        if ds > 0 and dq > 0:
            real = dq / ds
            if 0.5 * fps <= real <= 2 * fps:
                fps = round(real, 2)
    info["fps"] = fps
    info["duracao_s"] = round(quadros / fps, 1) if fps else 0
    return info


def _sonda(ffmpeg, arquivo):
    """Le resolucao e se tem audio de um arquivo (via 'ffmpeg -i')."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", arquivo], capture_output=True, text=True)
    txt = r.stderr or ""
    res = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", txt)
    return {"largura": int(res.group(1)) if res else 0,
            "altura": int(res.group(2)) if res else 0,
            "tem_audio": "Audio:" in txt}


def versao_ffmpeg():
    ffmpeg = xm.acha_ffmpeg()
    if not ffmpeg:
        return None, None
    try:
        r = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True)
        return ffmpeg, (r.stdout or "").splitlines()[0][:60]
    except Exception:
        return ffmpeg, "?"


def _roda(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0, (r.stderr or "")[-300:]


def para_mp4(caminho_bruto, saida, recodificar=False, apagar_temporarios=True):
    """Converte o arquivo XM baixado em .mp4. Retorna info (codec, resolucao, duracao...)."""
    ffmpeg = xm.acha_ffmpeg()
    if not ffmpeg:
        raise ErroSD("ffmpeg nao encontrado (pip install imageio-ffmpeg)")
    base = os.path.splitext(saida)[0]
    video, audio = base + ".video.tmp", base + ".audio.tmp"
    m4a, wav = base + ".audio.m4a", base + ".audio.wav"
    temporarios = [video, audio, m4a, wav]
    try:
        info = extrair(caminho_bruto, video, audio)
        if not info["quadros_i"]:
            raise ErroSD("nao achei video no arquivo (formato diferente do esperado)")
        fps = str(info["fps"])

        # 1) audio separado primeiro (G.711 -> AAC); se falhar, tenta WAV
        trilha = None
        if os.path.getsize(audio) > 0:
            ok, _ = _roda([ffmpeg, "-y", "-loglevel", "error", "-f", "alaw", "-ar", "8000", "-ac", "1",
                           "-i", audio, "-c:a", "aac", "-b:a", "64k", m4a])
            if ok and os.path.getsize(m4a) > 0:
                trilha = (m4a, ["-c:a", "copy"])
            else:
                ok, _ = _roda([ffmpeg, "-y", "-loglevel", "error", "-f", "alaw", "-ar", "8000", "-ac", "1",
                               "-i", audio, wav])
                if ok and os.path.getsize(wav) > 0:
                    trilha = (wav, ["-c:a", "aac", "-b:a", "64k"])

        # 2) junta com o video (copia, sem recodificar)
        formatos = ["hevc", "h264"] if info["codec"] == "h265" else ["h264", "hevc"]
        erro = ""
        for fmt in formatos:                         # se o codec veio errado, tenta o outro
            for com_audio in ([True, False] if trilha else [False]):
                cmd = [ffmpeg, "-y", "-loglevel", "error", "-fflags", "+genpts",
                       "-r", fps, "-f", fmt, "-i", video]
                if com_audio:
                    cmd += ["-i", trilha[0], "-map", "0:v:0", "-map", "1:a:0"]
                else:
                    cmd += ["-map", "0:v:0"]
                if recodificar:
                    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
                else:
                    cmd += ["-c:v", "copy"] + (["-tag:v", "hvc1"] if fmt == "hevc" else [])
                if com_audio:
                    cmd += trilha[1]
                cmd += ["-movflags", "+faststart", saida]
                ok, erro = _roda(cmd)
                if not (ok and os.path.isfile(saida) and os.path.getsize(saida) > 0):
                    continue
                sonda = _sonda(ffmpeg, saida)
                if com_audio and not sonda["tem_audio"]:
                    erro = "o audio nao entrou no arquivo"
                    continue                          # tenta de novo (sem audio, pelo menos o video)
                info.update({"formato_usado": fmt, "com_audio": sonda["tem_audio"],
                             "largura": sonda["largura"], "altura": sonda["altura"],
                             "audio_no_cartao": bool(trilha)})
                return info
        raise ErroSD("ffmpeg nao conseguiu converter: %s" % erro.strip())
    finally:
        if apagar_temporarios:
            for p in temporarios:
                try:
                    os.remove(p)
                except OSError:
                    pass


# ------------------------------------------------------------------
#  Download em segundo plano (usado pela pagina)
# ------------------------------------------------------------------
def pasta_camera(cid):
    return os.path.join(PASTA_SD, re.sub(r"[^A-Za-z0-9_-]", "_", cid))


def caminho_mp4(cid, arquivo):
    return os.path.join(pasta_camera(cid), nome_local(arquivo) + ".mp4")


class TarefaSD:
    """Baixa + converte UMA gravacao numa thread, com progresso e cancelar."""

    def __init__(self, cid, sessao, arquivo):
        self.cid, self.sessao, self.arquivo = cid, sessao, arquivo
        self.estado = "na fila"          # baixando | convertendo | pronto | erro | cancelado
        self.recebido = 0
        self.esperado = arquivo.get("kb", 0) * 1024
        self.erro = None
        self.mp4 = caminho_mp4(cid, arquivo)
        self.info = None
        self.inicio = time.time()
        self._parar = threading.Event()
        self.thread = threading.Thread(target=self._rodar, daemon=True)

    def iniciar(self):
        self.thread.start()
        return self

    def cancelar(self):
        self._parar.set()

    def ativa(self):
        return self.estado in ("na fila", "baixando", "convertendo")

    def _progresso(self, recebido, esperado):
        self.recebido = recebido
        if esperado:
            self.esperado = esperado

    def _rodar(self):
        os.makedirs(pasta_camera(self.cid), exist_ok=True)
        bruto = os.path.splitext(self.mp4)[0] + ".h264"
        try:
            ordem = list(MODOS_SD)
            salvo = modo_salvo(self.sessao.ip)
            if salvo:
                ordem.remove(salvo)
                ordem.insert(0, salvo)
            self.estado = "baixando"
            ok = False
            for modo in ordem:
                r = baixar(self.sessao, self.arquivo, bruto, modo=modo,
                           progresso=self._progresso, parar=self._parar)
                if self._parar.is_set():
                    self.estado = "cancelado"
                    return
                if r["bytes"] > 1024:
                    if modo != salvo:
                        salva_modo(self.sessao.ip, modo)
                    ok = True
                    break
            if not ok:
                raise ErroSD("a camera nao enviou o arquivo")
            self.estado = "convertendo"
            self.info = para_mp4(bruto, self.mp4)
            self.estado = "pronto"
        except Exception as e:
            self.erro = str(e)
            self.estado = "erro"
        finally:
            try:
                os.remove(bruto)
            except OSError:
                pass
            if self.estado != "pronto":
                try:
                    os.remove(self.mp4)
                except OSError:
                    pass

    def status(self):
        return {"estado": self.estado, "nome": self.arquivo.get("nome"),
                "inicio": self.arquivo.get("inicio"), "recebido": self.recebido,
                "esperado": self.esperado, "erro": self.erro,
                "segundos": round(time.time() - self.inicio),
                "url": "/sd/%s/%s" % (self.cid, os.path.basename(self.mp4)) if self.estado == "pronto" else None,
                "com_audio": (self.info or {}).get("com_audio")}
