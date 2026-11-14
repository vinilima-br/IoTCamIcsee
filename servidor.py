# =============================================================
#  SERVIDOR - Central das câmeras (versão final organizada)
#
#  O que ele faz:
#   - Vídeo ao vivo das câmeras (Elsys por RTSP, iCSee via ONVIF)
#   - Qualidade Leve/Alta, foto, ouvir o áudio ambiente
#   - Movimento (PTZ) nas iCSee
#   - IA de detecção de pessoas  -> SEMPRE começa DESLIGADA
#   - Gravação                   -> só grava se você ligar na página
#                                   (ao detectar pessoa e/ou manual)
#   - Alto-falante, sons, voz, volume, luz branca, alarme e LED das
#     iCSee, por uma sessão persistente na porta 34567 (sem bloqueio 205)
#   - Reconhecimento facial (aba Rostos) -> SEMPRE começa DESLIGADO
#
#  Como rodar:
#   pip install -r requirements.txt
#   python servidor.py
#   Abra: http://localhost:5050   (ou http://IP-DO-MINI-PC:5050 no celular)
#
#  NÃO rode junto outros scripts que loguem na câmera (pasta historico/).
# =============================================================

import atexit
import importlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta

# RTSP via TCP (estável em Wi-Fi). Precisa vir ANTES do import cv2.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

import cv2  # noqa: E402
from flask import Flask, Response, jsonify, render_template, request, send_from_directory  # noqa: E402

import config  # noqa: E402
import onvif_rtsp  # noqa: E402
import biblioteca_sons  # noqa: E402
import camera_xm  # noqa: E402
import cliente_xm  # noqa: E402
import cameras_cfg  # noqa: E402  (menu ➕ Câmeras)
import atualizador  # noqa: E402  (atualização automática pelo GitHub)
try:
    import elsys_xm  # noqa: E402  (cameras Elsys com login RSA)
except Exception as _e_elsys:
    elsys_xm = None
    print("aviso: elsys_xm indisponivel (%r); Elsys sem audio/luz" % _e_elsys)
import rosto_servidor  # noqa: E402
import lentes  # noqa: E402
import sd_xm  # noqa: E402
import gravador  # noqa: E402
import ptz as mod_ptz  # noqa: E402
from detector_pessoas import DetectorPessoas, desenhar_pessoas, MODELO_PADRAO  # noqa: E402

# ---- Configurações ----
WEB_PORTA = getattr(config, "WEB_PORTA", 5050)
JPEG_QUALIDADE = getattr(config, "JPEG_QUALIDADE", 80)
FOTO_QUALIDADE = 95

# Câmera sem espectador, sem IA e sem rosto: solta o vídeo depois deste tempo
# ocioso (poupa CPU no mini PC). Volta em 1-2 s quando alguém abrir de novo.
PAUSA_OCIOSA_S = getattr(config, "PAUSA_OCIOSA_S", 4.0)

# Apaga gravações, fotos, cópias do SD e logs com mais de X dias (0 = nunca).
# Os cadastros de rosto (pasta rostos/) NUNCA são apagados.
GUARDAR_DIAS = getattr(config, "GUARDAR_DIAS", 30)

IA_ATIVA = False   # a IA SEMPRE começa desligada (liga pela página)
IA_CONFIANCA = getattr(config, "IA_CONFIANCA", 0.4)
IA_MAX_POR_SEGUNDO = getattr(config, "IA_MAX_POR_SEGUNDO", 3)
IA_CONFIRMACOES = getattr(config, "IA_CONFIRMACOES", 2)
IA_SEGUNDOS_SAIDA = getattr(config, "IA_SEGUNDOS_SAIDA", 5)
IA_FOTO_INTERVALO_S = getattr(config, "IA_FOTO_INTERVALO_S", 1)
# Alertas da PRÓPRIA câmera (Alarme inteligente do app)
ALERTA_CAM_FOTO = getattr(config, "ALERTA_CAM_FOTO", False)       # tirar foto a cada alerta
ALERTA_CAM_FOTO_S = getattr(config, "ALERTA_CAM_FOTO_S", 10)      # (no máx. 1 a cada N s)
# "Só quando a câmera detectar" (IA/Rostos): fica liberado durante o alerta e
# mais ALERTA_CAM_POS_S depois do fim; sem "fim", no máximo ALERTA_CAM_MAX_S.
ALERTA_CAM_POS_S = getattr(config, "ALERTA_CAM_POS_S", 10)
ALERTA_CAM_MAX_S = getattr(config, "ALERTA_CAM_MAX_S", 120)

PASTA_BASE = os.path.dirname(os.path.abspath(__file__))
PASTA_FOTOS_BASE = os.path.join(PASTA_BASE, "fotos")
PASTA_GRAV_BASE = os.path.join(PASTA_BASE, "gravacoes")

# Gravação por evento (quando a IA detecta pessoa)
# Gravação: começa DESLIGADA em todas as câmeras; liga pela página.
GRAV_DURACAO_MAX_S = getattr(config, "GRAV_DURACAO_MAX_S", 300)

TIMEOUT_MS = 6000
ESPERA_RECONEXAO_S = 3
NOMES_STREAM = {0: "Alta", 1: "Leve"}


def pasta_da_camera(cid):
    return os.path.join(PASTA_FOTOS_BASE, cid)


def pasta_gravacoes(cid):
    return os.path.join(PASTA_GRAV_BASE, cid)


def monta_url_xm(ip, porta, usuario, senha, stream):
    return "rtsp://{ip}:{porta}/user={u}_password={s}_channel=1_stream={st}.sdp".format(
        ip=ip, porta=porta, u=usuario, s=senha, st=stream)


def abre_captura(url):
    try:
        return cv2.VideoCapture(
            url, cv2.CAP_FFMPEG,
            [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, TIMEOUT_MS,
             cv2.CAP_PROP_READ_TIMEOUT_MSEC, TIMEOUT_MS])
    except (TypeError, AttributeError, cv2.error):
        return cv2.VideoCapture(url, cv2.CAP_FFMPEG)


def salvar_imagem(frame, prefixo, pasta):
    """Salva em <pasta>/AAAA-MM-DD/<prefixo>_HH-MM-SS.jpg. Retorna o caminho relativo (dia/nome)."""
    agora = datetime.now()
    pasta_dia = agora.strftime("%Y-%m-%d")
    base = "{}_{}".format(prefixo, agora.strftime("%H-%M-%S"))
    os.makedirs(os.path.join(pasta, pasta_dia), exist_ok=True)

    nome = base + ".jpg"
    extra = 2
    while os.path.exists(os.path.join(pasta, pasta_dia, nome)):
        nome = "{}_{}.jpg".format(base, extra)
        extra += 1

    caminho = os.path.join(pasta, pasta_dia, nome)
    if not cv2.imwrite(caminho, frame, [int(cv2.IMWRITE_JPEG_QUALITY), FOTO_QUALIDADE]):
        raise RuntimeError("falha ao gravar o arquivo")
    return "{}/{}".format(pasta_dia, nome)


def lista_fotos(pasta, limite=8):
    fotos = []
    if not os.path.isdir(pasta):
        return fotos
    for pasta_dia in os.listdir(pasta):
        caminho_dia = os.path.join(pasta, pasta_dia)
        if not os.path.isdir(caminho_dia):
            continue
        for nome in os.listdir(caminho_dia):
            if nome.lower().endswith(".jpg"):
                caminho = os.path.join(caminho_dia, nome)
                fotos.append((os.path.getmtime(caminho), "{}/{}".format(pasta_dia, nome)))
    fotos.sort(reverse=True)
    return [f for _, f in fotos[:limite]]


# =============================================================
#  Câmera
# =============================================================
class Camera:
    """Lê uma câmera numa thread e guarda o último quadro (limpo e em JPEG).

    urls:        dict {0: url_alta, 1: url_leve}  (endereços RTSP fixos)
    descobridor: função() -> lista de URLs (quando o endereço vem do ONVIF)
    """

    def __init__(self, cid, nome, stream_inicial=1, urls=None, descobridor=None):
        self.cid = cid
        self.nome = nome
        self.stream = stream_inicial
        self.urls = dict(urls) if urls else {}
        self.descobridor = descobridor
        self.erro = None

        self._pedido_troca = False
        self.sobreposicao = None
        self.jpeg = None
        self.frame = None
        self.id_quadro = 0
        self.online = False
        self.largura = 0
        self.altura = 0
        self.fps = 0.0
        self.ultimo_quadro_em = 0.0
        self.trava_foto = threading.Lock()
        self.espectadores = 0          # navegadores assistindo (só gera JPEG se > 0)
        self.precisa_frames = None     # callback()->bool; None = captura sempre
        self.pausada = False           # True = soltou o vídeo por ociosidade
        self._ocioso_desde = 0.0
        self.cond = threading.Condition()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def iniciar(self):
        self.thread.start()

    def _quer_pausar(self):
        """Ninguém precisa dos frames: nem espectador, nem IA, nem rosto."""
        return self.precisa_frames is not None and not self.precisa_frames()

    def _mapeia(self, lista):
        if not lista:
            return {}
        if len(lista) == 1:
            return {0: lista[0], 1: lista[0]}
        return {0: lista[0], 1: lista[1]}

    def trocar_stream(self, stream):
        with self.cond:
            if stream == self.stream or stream not in (0, 1):
                return
            self.stream = stream
            self._pedido_troca = True
        print("[{}] Trocando para stream {} ({})".format(self.cid, stream, NOMES_STREAM.get(stream)))

    def _loop(self):
        parametros_jpeg = [int(cv2.IMWRITE_JPEG_QUALITY), int(JPEG_QUALIDADE)]
        while True:
            # Sem espectador/IA/rosto: fica em pausa, sem nem abrir o vídeo.
            if self._quer_pausar():
                if not self.pausada:
                    self.pausada = True
                    self._marca_offline()
                    print("[{}] Em pausa (ninguém assistindo).".format(self.cid))
                time.sleep(0.3)
                continue
            if self.pausada:
                self.pausada = False
                self._ocioso_desde = 0.0
                print("[{}] Retomando o vídeo.".format(self.cid))

            # Descobre o endereço via ONVIF, se for o caso
            if self.descobridor and not self.urls:
                try:
                    lista = self.descobridor()
                    self.urls = self._mapeia(lista)
                    self.erro = None
                    print("[{}] Endereço descoberto ({} perfil(is)).".format(self.cid, len(lista)))
                except Exception as erro:
                    self.erro = str(erro)
                    print("[{}] Não descobriu o endereço: {}".format(self.cid, erro))
                    self._marca_offline()
                    time.sleep(ESPERA_RECONEXAO_S)
                    continue

            with self.cond:
                stream_atual = self.stream
                self._pedido_troca = False

            url = self.urls.get(stream_atual) or self.urls.get(0)
            if not url:
                self.erro = "sem endereço de vídeo"
                self._marca_offline()
                time.sleep(ESPERA_RECONEXAO_S)
                continue

            print("[{}] Conectando ({})...".format(self.cid, NOMES_STREAM.get(stream_atual, stream_atual)))
            cap = abre_captura(url)
            if not cap.isOpened():
                print("[{}] Falha ao conectar. Nova tentativa em {}s.".format(self.cid, ESPERA_RECONEXAO_S))
                self.erro = "não conectou no vídeo"
                self._marca_offline()
                if self.descobridor:          # pode ser endereço vencido: redescobre
                    self.urls = {}
                time.sleep(ESPERA_RECONEXAO_S)
                continue

            self.erro = None
            print("[{}] Conectada.".format(self.cid))
            contador = 0
            inicio_janela = time.time()
            troca_pedida = False
            pausar = False
            self._ocioso_desde = 0.0

            while True:
                if self._pedido_troca:
                    troca_pedida = True
                    break

                # Ficou ocioso (ninguém precisa dos frames) por um tempinho:
                # solta o vídeo para poupar CPU. A margem evita fica abre/fecha.
                if self._quer_pausar():
                    if self._ocioso_desde == 0.0:
                        self._ocioso_desde = time.time()
                    elif time.time() - self._ocioso_desde >= PAUSA_OCIOSA_S:
                        pausar = True
                        break
                else:
                    self._ocioso_desde = 0.0

                ok, frame = cap.read()
                if not ok or frame is None:
                    print("[{}] Stream caiu. Reconectando...".format(self.cid))
                    break

                # Só comprime em JPEG se tem alguém assistindo: câmera
                # escondida na página = menos CPU no mini PC.
                jpeg = None
                if self.espectadores > 0:
                    para_video = frame
                    if self.sobreposicao is not None:
                        para_video = self.sobreposicao(frame)
                    ok, buffer = cv2.imencode(".jpg", para_video, parametros_jpeg)
                    if ok:
                        jpeg = buffer.tobytes()

                contador += 1
                agora = time.time()
                if agora - inicio_janela >= 2.0:
                    self.fps = contador / (agora - inicio_janela)
                    contador = 0
                    inicio_janela = agora

                with self.cond:
                    self.frame = frame
                    self.jpeg = jpeg
                    self.id_quadro += 1
                    self.altura, self.largura = frame.shape[:2]
                    self.online = True
                    self.ultimo_quadro_em = agora
                    self.cond.notify_all()

            cap.release()
            if troca_pedida or pausar:
                continue      # pausar: volta ao topo, que entra em pausa sem reconectar
            self._marca_offline()
            time.sleep(ESPERA_RECONEXAO_S)

    def _marca_offline(self):
        with self.cond:
            self.online = False
            self.fps = 0.0
            self.cond.notify_all()

    def proximo_jpeg(self, ultimo_id, timeout=5.0):
        with self.cond:
            self.cond.wait_for(lambda: self.id_quadro != ultimo_id, timeout=timeout)
            if self.id_quadro == ultimo_id or self.jpeg is None:
                return ultimo_id, None
            return self.id_quadro, self.jpeg

    def proximo_frame(self, ultimo_id, timeout=1.0):
        with self.cond:
            self.cond.wait_for(lambda: self.id_quadro != ultimo_id and self.online, timeout=timeout)
            if self.id_quadro == ultimo_id or self.frame is None or not self.online:
                return ultimo_id, None
            return self.id_quadro, self.frame

    def quadro_alta_atual(self):
        with self.cond:
            recente = time.time() - self.ultimo_quadro_em < 2.0
            if self.stream == 0 and self.online and recente and self.frame is not None:
                return self.frame.copy()
        return None

    def status(self):
        with self.cond:
            return {
                "nome": self.nome,
                "online": self.online,
                "largura": self.largura,
                "altura": self.altura,
                "fps": round(self.fps, 1),
                "stream": self.stream,
                "stream_nome": NOMES_STREAM.get(self.stream, "?"),
                "erro": self.erro,
                "espectadores": self.espectadores,
                "pausada": self.pausada,
            }


# =============================================================
#  IA - detecção de pessoas (uma por câmera que tiver)
# =============================================================
class IA:
    def __init__(self, camera, pasta_fotos, ativa):
        self.camera = camera
        self.pasta_fotos = pasta_fotos
        self.ativa = ativa
        self.erro = None
        self.detector = None
        self.gravador = None     # preenchido em monta_cameras
        self.gravar_auto = False # grava ao detectar pessoa (liga pela página)
        self.so_com_alerta = False   # só analisa quando a PRÓPRIA câmera detectar
        self.portao = None           # função () -> bool, ligada em _liga_portoes()
        self.gravacao_manual = False
        self.trava = threading.Lock()

        self.pessoas = []
        self.detectado_em = 0.0
        self.ms_por_deteccao = 0.0
        self.deteccoes_por_s = 0.0

        self.presenca = False
        self._seguidas = 0
        self._ultima_vez_com_pessoa = 0.0
        self._ultima_foto_auto = 0.0
        self.eventos = deque(maxlen=30)
        self._evento_atual = None

        # O modelo YOLO só é carregado quando a IA for LIGADA (poupa RAM:
        # não há 4 cópias na partida). Aqui só conferimos que o arquivo existe.
        self.modelo_ok = os.path.isfile(MODELO_PADRAO)
        if not self.modelo_ok:
            self.erro = "modelo não encontrado: {}".format(MODELO_PADRAO)
            print("[ia:{}] IA indisponível: {}".format(camera.cid, self.erro))

        self.thread = threading.Thread(target=self._loop, daemon=True)

    def iniciar(self):
        if self.modelo_ok:               # a thread roda, mas só detecta quando ligada
            self.thread.start()

    def _carrega_detector(self):
        """Carrega o YOLO na primeira vez que a IA é ligada."""
        if self.detector is not None:
            return True
        if not self.modelo_ok:
            return False
        try:
            self.detector = DetectorPessoas(confianca_min=IA_CONFIANCA)
            print("[ia:{}] Modelo carregado (sob demanda).".format(self.camera.cid))
            return True
        except Exception as erro:
            self.erro = str(erro)
            self.modelo_ok = False
            print("[ia:{}] Falha ao carregar o modelo: {}".format(self.camera.cid, erro))
            return False

    def ligar(self, ativa):
        ativa = bool(ativa)
        if ativa and not self._carrega_detector():
            return False
        with self.trava:
            self.ativa = ativa
            if not self.ativa:
                self._zera()
        print("[ia:{}] {}".format(self.camera.cid, "Ligada" if ativa else "Desligada"))
        return True

    def liberada(self):
        """False = "só quando a câmera detectar" ligado e a câmera sem alerta agora."""
        if not self.so_com_alerta or self.portao is None:
            return True
        try:
            return bool(self.portao())
        except Exception:
            return True

    def set_so_com_alerta(self, ligado):
        self.so_com_alerta = bool(ligado)
        print("[ia:{}] Só quando a câmera detectar: {}".format(self.camera.cid, "SIM" if ligado else "não"))

    def _zera(self):
        self.pessoas = []
        self._seguidas = 0
        if self.presenca:
            self._registra_saida()
        self.presenca = False

    def _loop(self):
        ultimo_id = 0
        intervalo_min = 1.0 / max(IA_MAX_POR_SEGUNDO, 0.1)
        contador = 0
        inicio_janela = time.time()

        while True:
            if not self.ativa or self.detector is None:
                time.sleep(0.3)
                continue
            if not self.liberada():               # esperando o alerta da câmera
                with self.trava:
                    if self.pessoas or self.presenca:
                        self.pessoas = []
                        self._atualiza_presenca(0, None)
                time.sleep(0.3)
                continue

            ultimo_id, frame = self.camera.proximo_frame(ultimo_id)
            if frame is None:
                with self.trava:
                    self.pessoas = []
                    self._atualiza_presenca(0, None)
                continue

            inicio = time.time()
            parte, dy = lentes.recorta(frame, getattr(self, "lente", "ambas"))
            try:
                pessoas = self.detector.detectar(parte)
                if parte is not frame:            # câmera de 2 lentes: só uma metade
                    pessoas = lentes.pessoas_no_quadro_inteiro(pessoas, dy, parte.shape[0], frame.shape[0])
            except cv2.error as erro:
                print("[ia:{}] Erro na detecção: {}".format(self.camera.cid, erro))
                time.sleep(1)
                continue
            fim = time.time()

            contador += 1
            if fim - inicio_janela >= 2.0:
                self.deteccoes_por_s = contador / (fim - inicio_janela)
                contador = 0
                inicio_janela = fim

            with self.trava:
                if not self.ativa:
                    continue
                self.pessoas = pessoas
                self.detectado_em = fim
                self.ms_por_deteccao = (fim - inicio) * 1000
                self._atualiza_presenca(len(pessoas), frame)

            espera = intervalo_min - (time.time() - inicio)
            if espera > 0:
                time.sleep(espera)

    def _atualiza_presenca(self, quantidade, frame):
        agora = time.time()
        if quantidade > 0:
            self._seguidas += 1
            self._ultima_vez_com_pessoa = agora
            if self._evento_atual is not None:
                self._evento_atual["max_pessoas"] = max(self._evento_atual["max_pessoas"], quantidade)
            if not self.presenca and self._seguidas >= IA_CONFIRMACOES:
                self.presenca = True
                self._registra_entrada(quantidade, frame)
        else:
            self._seguidas = 0
            if self.presenca and agora - self._ultima_vez_com_pessoa >= IA_SEGUNDOS_SAIDA:
                self.presenca = False
                self._registra_saida()

    def _registra_entrada(self, quantidade, frame):
        evento = {
            "entrada": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "saida": None,
            "max_pessoas": quantidade,
            "foto": None,
        }
        agora = time.time()
        if frame is not None and agora - self._ultima_foto_auto >= IA_FOTO_INTERVALO_S:
            try:
                marcada = desenhar_pessoas(frame.copy(), self.pessoas)
                rel = salvar_imagem(marcada, "pessoa", self.pasta_fotos)
                evento["foto"] = "/fotos/{}/{}".format(self.camera.cid, rel)
                self._ultima_foto_auto = agora
            except RuntimeError as erro:
                print("[ia:{}] Não salvou a foto automática: {}".format(self.camera.cid, erro))
        self._evento_atual = evento
        self.eventos.appendleft(evento)
        print("[ia:{}] PESSOA DETECTADA ({}) {}".format(
            self.camera.cid, quantidade, evento["foto"] or "(sem foto: intervalo)"))
        # grava o trecho só se a gravação automática estiver ligada
        if self.gravador is not None and self.gravar_auto:
            self.gravador.inicia(getattr(self, "lente", "ambas"))   # mesma lente da detecção

    def _registra_saida(self):
        if self._evento_atual is not None:
            self._evento_atual["saida"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print("[ia:{}] Cena vazia novamente.".format(self.camera.cid))
        self._evento_atual = None
        # encerra a gravação do trecho (a manual só para no botão)
        if self.gravador is not None and not self.gravacao_manual:
            self.gravador.para()

    def set_gravar_auto(self, ligado):
        with self.trava:
            self.gravar_auto = bool(ligado)
            gravando_evento = self.presenca and not self.gravacao_manual
        if self.gravador is None:
            return False
        if ligado and self.ativa and self.presenca:
            self.gravador.inicia(getattr(self, "lente", "ambas"))   # já tem gente: começa agora
        elif not ligado and gravando_evento:
            self.gravador.para()
        print("[grav:{}] Gravação automática {}".format(self.camera.cid, "LIGADA" if ligado else "desligada"))
        return True

    def gravar_manual(self, ligar, lente="ambas"):
        """lente: a que está na tela ("ambas" | "cima" = Lente 1 | "baixo" = Lente 2)."""
        if self.gravador is None or not self.gravador.disponivel():
            return False
        with self.trava:
            self.gravacao_manual = bool(ligar)
            continua_por_evento = self.gravar_auto and self.ativa and self.presenca
        if ligar:
            self.gravador.inicia(lente)
        elif not continua_por_evento:
            self.gravador.para()
        print("[grav:{}] Gravação manual {}".format(self.camera.cid, "iniciada" if ligar else "parada"))
        return True

    def sobreposicao(self, frame):
        with self.trava:
            if not self.ativa or not self.pessoas or time.time() - self.detectado_em > 1.5:
                return frame
            pessoas = list(self.pessoas)
        return desenhar_pessoas(frame.copy(), pessoas)

    def status(self):
        gravando = self.gravador.gravando() if self.gravador else False
        if self.gravacao_manual and not gravando:
            self.gravacao_manual = False      # parou sozinha (tempo máximo)
        with self.trava:
            return {
                "disponivel": self.modelo_ok,
                "ativa": self.ativa,
                "so_com_alerta": self.so_com_alerta,
                "aguardando_alerta": bool(self.ativa and not self.liberada()),
                "erro": self.erro,
                "pessoas": len(self.pessoas) if self.ativa else 0,
                "presenca": self.presenca,
                "ms_por_deteccao": round(self.ms_por_deteccao),
                "deteccoes_por_s": round(self.deteccoes_por_s, 1),
                "gravando": gravando,
                "gravar_auto": self.gravar_auto,
                "gravacao_manual": self.gravacao_manual,
                "gravacao_disponivel": bool(self.gravador and self.gravador.disponivel()),
            }

    def lista_eventos(self, limite=10):
        with self.trava:
            return [dict(e) for e in list(self.eventos)[:limite]]


def tirar_foto(camera, pasta):
    """Salva uma foto em alta (sem caixas). Retorna (caminho relativo, largura, altura)."""
    with camera.trava_foto:
        frame = camera.quadro_alta_atual()

        if frame is None:
            url0 = camera.urls.get(0)
            if not url0:
                raise RuntimeError("sem endereço de alta resolução")
            cap = abre_captura(url0)
            try:
                if not cap.isOpened():
                    raise RuntimeError("não conectou no stream de alta")
                for _ in range(3):
                    ok, f = cap.read()
                    if ok and f is not None:
                        frame = f
            finally:
                cap.release()

        if frame is None:
            raise RuntimeError("não chegou imagem da câmera")

        arquivo = salvar_imagem(frame, "foto", pasta)
        altura, largura = frame.shape[:2]
        print("[foto:{}] Salva: {} ({}x{})".format(camera.cid, arquivo, largura, altura))
        return arquivo, largura, altura


# =============================================================
#  Montagem das câmeras
# =============================================================
CAMERAS = {}      # cid -> Camera
IPS = {}          # cid -> IP da câmera na rede (do config), mostrado no título do cartão
IAS = {}          # cid -> IA
GRAVADORES = {}   # cid -> Gravador
PTZS = {}         # cid -> ptz.Controle
ARQ_PTZ_INV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ptz_inverter.json")
_ptz_inv_trava = threading.Lock()


def ptz_inversao(cid=None):
    """{"pan": bool, "tilt": bool} de cada câmera (botão ⇄ do cartão)."""
    try:
        with open(ARQ_PTZ_INV, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        dados = {}
    if cid is None:
        return dados
    d = dados.get(cid) or {}
    return {"pan": bool(d.get("pan")), "tilt": bool(d.get("tilt"))}


def grava_ptz_inversao(cid, pan, tilt):
    with _ptz_inv_trava:
        dados = ptz_inversao()
        dados[cid] = {"pan": bool(pan), "tilt": bool(tilt)}
        tmp = ARQ_PTZ_INV + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=1)
        os.replace(tmp, ARQ_PTZ_INV)
    return dados[cid]
XMS = {}          # cid -> sessão da porta 34567 (alto-falante, luz, alarme)
# True (padrão): quem fala com a porta 34567 é o sessao_xm.py, numa janela
# separada que fica sempre aberta. False: volta ao jeito antigo (o próprio
# servidor loga, e cada reinício é um login novo).
SESSAO_SEPARADA = getattr(config, "XM_SESSAO_SEPARADA", True)
ORDEM = []        # ordem de exibição
RECS = {}         # cid -> rosto_servidor.Reconhecedor (aba Rostos)
MOTOR_ROSTO = None


def _liga_gravador(cid, camera, ia):
    """Cria o gravador da câmera (só grava quando ligado na página).
    Grava o stream leve (mesma URL que a câmera já tem)."""
    grav = gravador.Gravador(
        cid, pasta_gravacoes(cid),
        obtem_url=lambda c=camera: c.urls.get(1) or c.urls.get(0),
        duracao_max_s=GRAV_DURACAO_MAX_S,
        nome=camera.nome,
    )
    ia.gravador = grav
    GRAVADORES[cid] = grav


def _monta_icsee(cid, nome, ip, usuario, senha, porta_onvif, perfil_ptz="000",
                 senha_admin="", tem_xm=True, tem_ptz=True, usuario_admin="admin"):
    """Monta uma câmera iCSee/XM: vídeo via ONVIF + IA + gravação + PTZ."""
    porta = porta_onvif or None

    def descobre():
        if not senha:
            raise onvif_rtsp.ErroOnvif("preencha a senha da {} no config.py".format(nome))
        return onvif_rtsp.descobre_urls(ip, usuario, senha, porta_onvif=porta)

    cam = Camera(cid, nome, stream_inicial=1, descobridor=descobre)
    CAMERAS[cid] = cam
    ORDEM.append(cid)
    ia = IA(cam, pasta_da_camera(cid), False)
    cam.sobreposicao = ia.sobreposicao
    IAS[cid] = ia
    _liga_gravador(cid, cam, ia)
    if tem_ptz:
        PTZS[cid] = mod_ptz.Controle(ip, usuario, senha, porta_onvif=porta, perfil=perfil_ptz)
    # porta 34567: conta REAL do APARELHO (não o e-mail do app). Padrão "admin"
    # (de fábrica), mas o certo é a conta real recuperada (ver config.py).
    if tem_xm:
        ALERTAS_CIDS.add(cid)    # iCSee: a sessão 34567 também traz os alertas da câmera
        if SESSAO_SEPARADA:      # a sessão 34567 fica no sessao_xm.py (não reloga ao reiniciar)
            XMS[cid] = cliente_xm.SessaoRemota(cid, ip, usuario_admin, senha_admin)
        else:
            XMS[cid] = camera_xm.SessaoCamera(cid, ip, usuario_admin, senha_admin)


def _monta_elsys(cid, nome, ip, porta, usuario, senha, stream):
    """Monta uma câmera Elsys: vídeo RTSP direto + IA + gravação.
    O áudio (falar) e a luz branca ('alerta') vêm do XMS (login RSA)."""
    cam = Camera(cid, nome,
                 stream_inicial=stream if stream in (0, 1) else 1,
                 urls={0: monta_url_xm(ip, porta, usuario, senha, 0),
                       1: monta_url_xm(ip, porta, usuario, senha, 1)})
    CAMERAS[cid] = cam
    ORDEM.append(cid)
    ia = IA(cam, pasta_da_camera(cid), False)
    cam.sobreposicao = ia.sobreposicao
    IAS[cid] = ia
    _liga_gravador(cid, cam, ia)


def monta_cameras():
    """Monta todas as câmeras a partir da lista única config.cameras()."""
    for c in config.cameras():
        cid = c["cid"]
        IPS[cid] = c.get("ip", "")
        try:
            if c["tipo"] == "elsys":
                _monta_elsys(cid, c["nome"], c["ip"], c["porta"],
                             c["usuario"], c["senha"], c["stream"])
            else:  # icsee
                _monta_icsee(cid, c["nome"], c["ip"], c["usuario"], c["senha"],
                             c["porta_onvif"], perfil_ptz=c["ptz_perfil"],
                             usuario_admin=c["admin_usuario"], senha_admin=c["admin_senha"],
                             tem_xm=c["xm"], tem_ptz=c["ptz"])
        except Exception as ex:
            print("[%s] câmera não montou: %r" % (cid, ex))

    # ---- XMS (alto-falante + luz branca) das Elsys (as iCSee já montam no _monta_icsee) ----
    for c in config.cameras():
        if c["tipo"] != "elsys" or not c["xm"]:
            continue
        cid, ip = c["cid"], c["ip"]
        if cid in XMS or cid not in CAMERAS:
            continue
        try:
            if SESSAO_SEPARADA:        # a sessão RSA fica no sessao_xm.py
                XMS[cid] = cliente_xm.SessaoRemota(cid, ip, "admin", "")
            elif elsys_xm is not None:
                XMS[cid] = elsys_xm.ElsysSessao(cid, ip)
        except Exception as ex:
            print("[%s] XMS Elsys não montou: %r" % (cid, ex))


def monta_rostos():
    """Um reconhecedor facial por câmera (começa desligado)."""
    global MOTOR_ROSTO
    MOTOR_ROSTO = rosto_servidor.Motor()
    escolhidas = lentes.le()
    for cid, ia_cam in IAS.items():
        ia_cam.lente = escolhidas.get(cid, "ambas")
    for cid in ORDEM:
        _monta_rosto(cid)


def _monta_rosto(cid):
    cam = CAMERAS[cid]
    falar = alerta = holofote = None
    if cid in XMS:
        falar = lambda texto, voz=None, cid=cid: _rosto_falar(cid, texto, voz)  # noqa: E731
        alerta = lambda ligar, segundos, cid=cid: _xm(cid).set_alerta(ligar, segundos)  # noqa: E731
        holofote = lambda estado, cid=cid: _holofote(cid, estado)  # noqa: E731
    rec = rosto_servidor.Reconhecedor(cam, MOTOR_ROSTO, falar, alerta, holofote)
    RECS[cid] = rec
    anterior = cam.sobreposicao          # junta com as caixas da IA de pessoas
    if anterior is None:
        cam.sobreposicao = rec.sobreposicao
    else:
        cam.sobreposicao = lambda f, a=anterior, r=rec: r.sobreposicao(a(f))  # noqa: E731
    return rec


# ---------------- câmera nova / removida COM a Central rodando (sem reiniciar) ----------------
_montagem_trava = threading.Lock()
REMOVIDAS = set()


def adiciona_ao_vivo(cid):
    """Monta e liga uma câmera que acabou de entrar no config.py (menu ➕ Câmeras)."""
    with _montagem_trava:
        importlib.reload(config)
        c = next((x for x in config.cameras() if x["cid"] == cid), None)
        if c is None:
            raise RuntimeError("{} não está no config.py".format(cid))
        if cid in CAMERAS:
            raise RuntimeError("{} já está montada".format(cid))
        REMOVIDAS.discard(cid)
        IPS[cid] = c.get("ip", "")
        if c["tipo"] == "elsys":
            _monta_elsys(cid, c["nome"], c["ip"], c["porta"], c["usuario"], c["senha"], c["stream"])
            if c["xm"] and SESSAO_SEPARADA:
                XMS[cid] = cliente_xm.SessaoRemota(cid, c["ip"], "admin", "")
        else:
            _monta_icsee(cid, c["nome"], c["ip"], c["usuario"], c["senha"], c["porta_onvif"],
                         perfil_ptz=c["ptz_perfil"], usuario_admin=c["admin_usuario"],
                         senha_admin=c["admin_senha"], tem_xm=c["xm"], tem_ptz=c["ptz"])
        if cid in IAS:
            IAS[cid].lente = lentes.le().get(cid, "ambas")
        if MOTOR_ROSTO is not None and cid in CAMERAS:
            _monta_rosto(cid)
        _liga_portoes()
        _liga_pausa_ociosa()
        CAMERAS[cid].iniciar()
        if cid in IAS:
            IAS[cid].iniciar()
        if cid in XMS:
            XMS[cid].iniciar()
            _xm_status[cid] = {"estado": "aguardando", "logada": False, "ip": getattr(XMS[cid], "ip", None)}
            threading.Thread(target=_ronda_status_xm, args=(cid, XMS[cid]), daemon=True).start()
        if cid in RECS:
            RECS[cid].iniciar()
        if cid in ALERTAS_CIDS and cid in XMS:
            ALERTAS_INFO[cid] = {"guard": None, "erro": "iniciando"}
            threading.Thread(target=_ronda_alertas_cam, args=(cid, XMS[cid]), daemon=True).start()
        if cid in PTZS:
            threading.Thread(target=_ronda_ptz, args=(cid, PTZS[cid]), daemon=True).start()
        print("[{}] câmera montada AO VIVO (sem reiniciar): {}".format(cid, c["nome"]))


def remove_ao_vivo(cid):
    """Tira a câmera do painel com a Central rodando: solta o vídeo e para IA/rosto/gravação."""
    with _montagem_trava:
        REMOVIDAS.add(cid)
        g = GRAVADORES.pop(cid, None)
        if g is not None:
            try:
                g.para()
            except Exception:
                pass
        ia = IAS.pop(cid, None)
        if ia is not None:
            try:
                ia.ligar(False)
            except Exception:
                pass
        rec = RECS.pop(cid, None)
        if rec is not None:
            rec.ativo = False
            rec.cadastro = None
        cam = CAMERAS.pop(cid, None)
        if cam is not None:
            cam.precisa_frames = lambda: False      # o laço da câmera solta o vídeo e fica parado
            cam.espectadores = 0
        if cid in ORDEM:
            ORDEM.remove(cid)
        for d in (XMS, PTZS, IPS, ALERTAS_INFO):
            d.pop(cid, None)
        ALERTAS_CIDS.discard(cid)
        print("[{}] câmera removida AO VIVO (sem reiniciar)".format(cid))


# =============================================================
#  Flask
# =============================================================
app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True     # mudou o painel.html? basta atualizar a página
app.jinja_env.auto_reload = True
app.config["MAX_CONTENT_LENGTH"] = biblioteca_sons.TAMANHO_MAX + 1024 * 1024


def _camera(cid):
    return CAMERAS.get(cid)


@app.route("/")
def index():
    cameras = [{"id": cid, "nome": CAMERAS[cid].nome,
                "tem_ia": cid in IAS, "tem_ptz": cid in PTZS, "tem_xm": cid in XMS,
                "tem_rosto": cid in RECS, "tem_alertas": cid in ALERTAS_CIDS,
                "ip": IPS.get(cid, "")}
               for cid in ORDEM]
    return render_template("painel.html", cameras=cameras, modos_luz=camera_xm.MODOS_LUZ,
                           tem_xm=bool(XMS), sem_cameras=not cameras)


@app.route("/video/<cid>")
def video(cid):
    camera = _camera(cid)
    if camera is None:
        return "câmera desconhecida", 404

    def gerar():
        ultimo_id = 0
        with camera.cond:
            camera.espectadores += 1
        try:
            while True:
                ultimo_id, jpeg = camera.proximo_jpeg(ultimo_id)
                if jpeg is None:
                    continue
                yield (b"--quadro\r\n"
                       b"Content-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                       + jpeg + b"\r\n")
        finally:
            with camera.cond:
                camera.espectadores = max(0, camera.espectadores - 1)

    resposta = Response(gerar(), mimetype="multipart/x-mixed-replace; boundary=quadro")
    resposta.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resposta


@app.route("/status")
def status():
    dados = {}
    for cid in ORDEM:
        d = CAMERAS[cid].status()
        if cid in IAS:
            d["ia"] = IAS[cid].status()
        if cid in RECS:
            d["rosto"] = RECS[cid].status()
            d["lente_det"] = RECS[cid].lente
        if cid in PTZS:
            d["ptz"] = PTZS[cid].capaz        # True: se mexe · False: fixa · None: ainda vendo
            d["ptz_inv"] = ptz_inversao(cid)
        if cid in XMS:
            with _xm_status_trava:          # lê do cache (nunca bloqueia a página)
                d["xm"] = _xm_status.get(cid)
            if d["xm"] is None:
                d["xm"] = XMS[cid].status()  # só na primeiríssima vez (cache vazio)
            t = SD_TAREFAS.get(cid)
            d["sd"] = t.status() if t else None
        dados[cid] = d
    return jsonify(dados)


@app.route("/api/stream/<cid>", methods=["POST"])
def api_stream(cid):
    camera = _camera(cid)
    if camera is None:
        return jsonify({"ok": False, "erro": "câmera desconhecida"}), 404
    dados = request.get_json(silent=True) or {}
    stream = dados.get("stream")
    if stream not in (0, 1):
        return jsonify({"ok": False, "erro": "stream deve ser 0 (Alta) ou 1 (Leve)"}), 400
    camera.trocar_stream(stream)
    return jsonify({"ok": True, "stream": stream})


@app.route("/api/foto/<cid>", methods=["POST"])
def api_foto(cid):
    camera = _camera(cid)
    if camera is None:
        return jsonify({"ok": False, "erro": "câmera desconhecida"}), 404
    try:
        arquivo, largura, altura = tirar_foto(camera, pasta_da_camera(cid))
    except RuntimeError as erro:
        return jsonify({"ok": False, "erro": str(erro)}), 503
    return jsonify({
        "ok": True,
        "arquivo": arquivo,
        "url": "/fotos/{}/{}".format(cid, arquivo),
        "resolucao": "{}x{}".format(largura, altura),
    })


@app.route("/api/fotos/<cid>")
def api_fotos(cid):
    if _camera(cid) is None:
        return jsonify([])
    fotos = lista_fotos(pasta_da_camera(cid))
    return jsonify([{"arquivo": f, "url": "/fotos/{}/{}".format(cid, f)} for f in fotos])


@app.route("/fotos/<cid>/<path:arquivo>")
def servir_foto(cid, arquivo):
    return send_from_directory(pasta_da_camera(cid), arquivo)


@app.route("/api/gravacoes/<cid>")
def api_gravacoes(cid):
    if _camera(cid) is None:
        return jsonify([])
    return jsonify(gravador.lista_gravacoes(pasta_gravacoes(cid)))


@app.route("/gravacoes/<cid>/<path:arquivo>")
def servir_gravacao(cid, arquivo):
    return send_from_directory(pasta_gravacoes(cid), arquivo)


@app.route("/api/ia/<cid>", methods=["POST"])
def api_ia(cid):
    ia = IAS.get(cid)
    if ia is None:
        return jsonify({"ok": False, "erro": "essa câmera não tem IA"}), 404
    dados = request.get_json(silent=True) or {}
    if isinstance(dados.get("so_com_alerta"), bool):
        ia.set_so_com_alerta(dados["so_com_alerta"])
        if "ativa" not in dados:
            return jsonify({"ok": True, "so_com_alerta": ia.so_com_alerta})
    ativa = dados.get("ativa")
    if not isinstance(ativa, bool):
        return jsonify({"ok": False, "erro": "envie {\"ativa\": true} ou {\"ativa\": false}"}), 400
    if not ia.ligar(ativa):
        return jsonify({"ok": False, "erro": ia.erro or "IA indisponível"}), 503
    return jsonify({"ok": True, "ativa": ativa})


@app.route("/api/gravacao/<cid>", methods=["POST"])
def api_gravacao(cid):
    """{"auto": true/false}  e/ou  {"manual": true/false}"""
    ia = IAS.get(cid)
    if ia is None or ia.gravador is None or not ia.gravador.disponivel():
        return jsonify({"ok": False, "erro": "gravação indisponível (ffmpeg?)"}), 503
    dados = request.get_json(silent=True) or {}
    if "auto" in dados:
        if not isinstance(dados["auto"], bool):
            return jsonify({"ok": False, "erro": "auto deve ser true/false"}), 400
        ia.set_gravar_auto(dados["auto"])
    if "manual" in dados:
        if not isinstance(dados["manual"], bool):
            return jsonify({"ok": False, "erro": "manual deve ser true/false"}), 400
        lente = dados.get("lente") if dados.get("lente") in lentes.OPCOES else "ambas"
        ia.gravar_manual(dados["manual"], lente)
    s = ia.status()
    return jsonify({"ok": True, "gravar_auto": s["gravar_auto"],
                    "gravacao_manual": s["gravacao_manual"], "gravando": s["gravando"]})


@app.route("/api/gravacoes/<cid>/<path:arquivo>", methods=["DELETE"])
def api_apagar_gravacao(cid, arquivo):
    if _camera(cid) is None:
        return jsonify({"ok": False, "erro": "câmera desconhecida"}), 404
    base = os.path.realpath(pasta_gravacoes(cid))
    alvo = os.path.realpath(os.path.join(base, arquivo))
    if not alvo.startswith(base + os.sep) or not os.path.isfile(alvo):
        return jsonify({"ok": False, "erro": "gravação não encontrada"}), 404
    ia = IAS.get(cid)
    if ia and ia.gravador and ia.gravador.gravando() and ia.gravador.arquivo_atual \
            and os.path.realpath(ia.gravador.arquivo_atual) == alvo:
        return jsonify({"ok": False, "erro": "essa gravação ainda está em andamento"}), 409
    os.remove(alvo)
    return jsonify({"ok": True})


@app.route("/api/eventos/<cid>")
def api_eventos(cid):
    ia = IAS.get(cid)
    if ia is None:
        return jsonify([])
    return jsonify(ia.lista_eventos())


@app.route("/api/ptz/<cid>/mover", methods=["POST"])
def api_ptz_mover(cid):
    controle = PTZS.get(cid)
    if controle is None:
        return jsonify({"ok": False, "erro": "essa câmera não tem movimento"}), 404
    dados = request.get_json(silent=True) or {}

    def faixa(v):
        try:
            return max(-1.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    inv = ptz_inversao(cid)                     # botão ⇄: câmera instalada ao contrário
    try:
        controle.mover(pan=faixa(dados.get("pan", 0)) * (-1 if inv["pan"] else 1),
                       tilt=faixa(dados.get("tilt", 0)) * (-1 if inv["tilt"] else 1),
                       zoom=faixa(dados.get("zoom", 0)))
    except mod_ptz.ErroPTZ as erro:
        return jsonify({"ok": False, "erro": str(erro)}), 503
    return jsonify({"ok": True})


@app.route("/api/ptz/<cid>/inverter", methods=["GET", "POST"])
def api_ptz_inverter(cid):
    """GET: {"pan","tilt"} · POST {"pan": bool, "tilt": bool}: inverte os comandos do joystick."""
    if cid not in PTZS:
        return jsonify({"ok": False, "erro": "essa câmera não tem movimento"}), 404
    if request.method == "GET":
        return jsonify(dict(ok=True, **ptz_inversao(cid)))
    d = request.get_json(silent=True) or {}
    atual = ptz_inversao(cid)
    pan = d["pan"] if isinstance(d.get("pan"), bool) else atual["pan"]
    tilt = d["tilt"] if isinstance(d.get("tilt"), bool) else atual["tilt"]
    try:
        novo = grava_ptz_inversao(cid, pan, tilt)
    except OSError as e:
        return jsonify({"ok": False, "erro": "não salvei: {}".format(e)}), 500
    print("[{}] PTZ invertido: esquerda/direita={} cima/baixo={}".format(
        cid, "SIM" if novo["pan"] else "não", "SIM" if novo["tilt"] else "não"))
    return jsonify(dict(ok=True, **novo))


@app.route("/api/ptz/<cid>/parar", methods=["POST"])
def api_ptz_parar(cid):
    controle = PTZS.get(cid)
    if controle is None:
        return jsonify({"ok": False, "erro": "essa câmera não tem movimento"}), 404
    try:
        controle.parar()
    except mod_ptz.ErroPTZ as erro:
        return jsonify({"ok": False, "erro": str(erro)}), 503
    return jsonify({"ok": True})


@app.route("/api/ptz/<cid>/presets")
def api_ptz_presets(cid):
    controle = PTZS.get(cid)
    if controle is None:
        return jsonify([])
    return jsonify([{"token": t, "nome": n} for t, n in controle.presets()])


@app.route("/api/ptz/<cid>/preset", methods=["POST"])
def api_ptz_preset(cid):
    controle = PTZS.get(cid)
    if controle is None:
        return jsonify({"ok": False, "erro": "essa câmera não tem movimento"}), 404
    dados = request.get_json(silent=True) or {}
    token = dados.get("token")
    if not token:
        return jsonify({"ok": False, "erro": "faltou o token do preset"}), 400
    try:
        controle.ir(token)
    except mod_ptz.ErroPTZ as erro:
        return jsonify({"ok": False, "erro": str(erro)}), 503
    return jsonify({"ok": True})


@app.route("/audio/<cid>")
def audio(cid):
    """Áudio ao vivo da câmera (só áudio, convertido para AAC). Sob demanda."""
    camera = _camera(cid)
    if camera is None:
        return "câmera desconhecida", 404
    url = camera.urls.get(1) or camera.urls.get(0)
    if not url:
        return "câmera sem endereço (conectada?)", 503
    ff = gravador.acha_ffmpeg()
    if not ff:
        return "ffmpeg não encontrado", 503

    cmd = [ff, "-loglevel", "error",
           "-fflags", "nobuffer", "-flags", "low_delay",
           "-probesize", "32", "-analyzeduration", "0",
           "-rtsp_transport", "tcp",
           "-i", url, "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "48k",
           "-flush_packets", "1", "-f", "adts", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def gerar():
        try:
            while True:
                chunk = proc.stdout.read(1024)   # pedaços menores = menos atraso
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                proc.kill()
            except Exception:
                pass

    resposta = Response(gerar(), mimetype="audio/aac")
    resposta.headers["Cache-Control"] = "no-cache, no-store"
    return resposta


@app.route("/audio_pcm/<cid>")
def audio_pcm(cid):
    """Áudio cru (PCM 16 bits, 8 kHz mono) para a Web Audio API — baixa latência."""
    camera = _camera(cid)
    if camera is None:
        return "câmera desconhecida", 404
    url = camera.urls.get(1) or camera.urls.get(0)
    if not url:
        return "câmera sem endereço (conectada?)", 503
    ff = gravador.acha_ffmpeg()
    if not ff:
        return "ffmpeg não encontrado", 503

    cmd = [ff, "-loglevel", "error",
           "-fflags", "nobuffer", "-flags", "low_delay",
           "-probesize", "32", "-analyzeduration", "0",
           "-rtsp_transport", "tcp",
           "-i", url, "-vn", "-ac", "1", "-ar", "8000",
           "-flush_packets", "1", "-f", "s16le", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def gerar():
        try:
            while True:
                chunk = proc.stdout.read(512)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                proc.kill()
            except Exception:
                pass

    resposta = Response(gerar(), mimetype="application/octet-stream")
    resposta.headers["Cache-Control"] = "no-cache, no-store"
    return resposta


# =============================================================
#  Alto-falante, luzes e alarme (porta 34567, sessão persistente)
# =============================================================
PASTA_TTS = os.path.join(biblioteca_sons.PASTA_CACHE, "tts")


def _xm(cid):
    s = XMS.get(cid)
    if s is None:
        raise camera_xm.ErroXM("essa câmera não tem controle de alto-falante/luz")
    return s


def _xm_erro(erro):
    if isinstance(erro, ConnectionError):
        return jsonify({"ok": False, "erro": str(erro)}), 503
    return jsonify({"ok": False, "erro": str(erro)}), 400


def _toca_em(cids, alaw, nome_som):
    """Toca o mesmo áudio em várias câmeras, cada uma na sua thread."""
    iniciadas, erros = [], {}
    for cid in cids:
        try:
            s = _xm(cid)
            if not s.conectada:
                raise ConnectionError("câmera não está logada ({})".format(s.status()["erro"]))
            if s.falando:
                raise camera_xm.ErroXM("já está tocando um som")
        except (camera_xm.ErroXM, ConnectionError) as e:
            erros[cid] = str(e)
            continue

        def tarefa(s=s, cid=cid):
            try:
                r = s.falar(alaw, nome_som)
                print("[xm:{}] tocou '{}' modo={} claim={} start={} stop={} ({} pacotes{})".format(
                    cid, nome_som, r["modo"], r["claim"], r["start"], r["stop"],
                    r["pacotes"], ", interrompido" if r["interrompido"] else ""))
            except Exception as e:
                print("[xm:{}] erro ao tocar '{}': {}".format(cid, nome_som, e))

        threading.Thread(target=tarefa, daemon=True).start()
        iniciadas.append(cid)
    return iniciadas, erros


def _cids_do_pedido(dados, cid_padrao=None):
    cams = dados.get("cams")
    if cams == "todas" or cams == ["todas"]:
        return [c for c in ORDEM if c in XMS]
    if isinstance(cams, list) and cams:
        return [c for c in cams if c in XMS]
    return [cid_padrao] if cid_padrao else []


@app.route("/api/xm/<cid>/status")
def api_xm_status(cid):
    try:
        return jsonify(_xm(cid).status())
    except camera_xm.ErroXM as e:
        return jsonify({"erro": str(e)}), 404


# ---------------- menu ➕ Câmeras: buscar / adicionar / remover ----------------
BOOT_ID = "%x" % int(time.time() * 1000)     # muda a cada subida (a página percebe o reinício)
AO_REINICIAR = None                          # janela.py põe aqui como fechar a janela
CODIGO_REINICIO = 3                          # PAINEL.bat / INICIAR.bat sobem de novo com este código
CODIGO_SAIDA = CODIGO_REINICIO               # o que a janela.py usa ao fechar (0 = atualização)
_reiniciando = threading.Event()


def pedir_reinicio(motivo, codigo=CODIGO_REINICIO):
    """Fecha a Central. Código 3: o .bat sobe tudo de novo (câmeras novas montadas).
    Código 0: só fecha (a atualização automática abre de novo depois de trocar os .bat)."""
    global CODIGO_SAIDA
    if _reiniciando.is_set():
        return
    _reiniciando.set()
    CODIGO_SAIDA = codigo

    def _faz():
        time.sleep(1.5)                      # dá tempo da resposta chegar na página
        print(" Reiniciando a Central ({})...".format(motivo))
        if AO_REINICIAR is not None:
            try:
                AO_REINICIAR()
                return
            except Exception as e:  # noqa: BLE001
                print(" [reinicio] janela não fechou: {!r}".format(e))
        t = threading.Thread(target=atexit._run_exitfuncs, daemon=True)
        t.start()
        t.join(8)                            # logout nas câmeras: no máximo 8 s
        os._exit(CODIGO_SAIDA)
    threading.Thread(target=_faz, daemon=True, name="reinicio").start()


# ---------------- atualização automática (GitHub) ----------------
def _lancador():
    return "PAINEL.bat" if AO_REINICIAR is not None else "INICIAR.bat"


_ultimo_clique = [time.time()]                # última ação de alguém na página (POST)
SOSSEGO_ATUALIZAR_S = 10 * 60                 # só atualiza sozinha 10 min depois do último clique


@app.before_request
def _marca_uso():
    if request.method in ("POST", "DELETE") and not request.path.startswith("/api/atualizacao"):
        _ultimo_clique[0] = time.time()


def _pode_atualizar():
    """True, ou o motivo de não atualizar agora (nunca no meio do uso)."""
    if _reiniciando.is_set():
        return "reiniciando"
    if any(g.gravando() for g in GRAVADORES.values()):
        return "gravando"
    if any(r.cadastro and r.cadastro.get("estado") == "capturando" for r in RECS.values()):
        return "cadastrando rosto"
    if cameras_cfg._trava.locked():
        return "adicionando câmera"
    if any(t.estado in ("na fila", "baixando", "convertendo") for t in SD_TAREFAS.values() if t):
        return "baixando do cartão SD"
    parado = time.time() - _ultimo_clique[0]
    if parado < SOSSEGO_ATUALIZAR_S:
        return "alguém usando o painel ({} min atrás)".format(int(parado // 60))
    return True


@app.route("/api/desligar", methods=["POST"])
def api_desligar():
    """Janela do painel fechada no X: desliga a Central (só pedido do próprio PC)."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"ok": False, "erro": "só pelo próprio PC"}), 403
    pedir_reinicio("janela fechada", codigo=0)
    return jsonify({"ok": True})


def _fecha_para_atualizar():
    pedir_reinicio("atualização do GitHub", codigo=0)


@app.route("/api/atualizacao")
def api_atualizacao():
    e = dict(atualizador.estado)
    e["local_curto"] = (e.get("local") or "")[:7]
    e["remoto_curto"] = (e.get("remoto") or "")[:7]
    return jsonify(e)


@app.route("/api/atualizacao/verificar", methods=["POST"])
def api_atualizacao_verificar():
    e = atualizador.verificar()
    e["local_curto"], e["remoto_curto"] = (e.get("local") or "")[:7], (e.get("remoto") or "")[:7]
    return jsonify(e)


@app.route("/api/atualizacao/automatica", methods=["POST"])
def api_atualizacao_automatica():
    ligada = (request.get_json(silent=True) or {}).get("ligada")
    if not isinstance(ligada, bool):
        return jsonify({"ok": False, "erro": "envie {\"ligada\": true/false}"}), 400
    try:
        return jsonify({"ok": True, "automatica": atualizador.grava_automatica(ligada)})
    except OSError as e:
        return jsonify({"ok": False, "erro": "não consegui salvar: {}".format(e)})


@app.route("/api/atualizacao/aplicar", methods=["POST"])
def api_atualizacao_aplicar():
    motivo = _pode_atualizar()
    if motivo in ("gravando", "cadastrando rosto", "adicionando câmera", "baixando do cartão SD"):
        return jsonify({"ok": False, "erro": "agora não: {} (termine e tente de novo)".format(motivo)})
    ok, msg = atualizador.aplicar(_lancador(), _fecha_para_atualizar)
    return jsonify({"ok": ok, "erro": None if ok else msg, "msg": msg})


def _depois_de_mudar_cameras(motivo, cid=None, acao=None):
    """Sessão lê o config de novo; a câmera entra/sai AO VIVO. Só reinicia se isso falhar.
    Devolve True se reiniciou."""
    if SESSAO_SEPARADA:
        r = cliente_xm.recarregar()
        if not r.get("ok"):
            print(" [câmeras] a sessão não recarregou: {}".format(r.get("erro")))
    try:
        if acao == "adicionar" and cid:
            adiciona_ao_vivo(cid)
            return False
        if acao == "remover" and cid:
            remove_ao_vivo(cid)
            return False
    except Exception as e:  # noqa: BLE001
        print(" [câmeras] não montei ao vivo ({!r}): reiniciando a Central".format(e))
    pedir_reinicio(motivo)
    return True


@app.route("/api/boot")
def api_boot():
    return jsonify({"boot": BOOT_ID, "reiniciando": _reiniciando.is_set()})


@app.route("/api/cameras/lista")
def api_cameras_lista():
    try:
        cams = cameras_cfg.lista()
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": "config.py com problema: {}".format(e)}), 500
    for c in cams:
        cam = CAMERAS.get(c["cid"])
        c["no_ar"] = cam is not None
        c["online"] = bool(cam.online) if cam is not None else False
    return jsonify({"ok": True, "cameras": cams})


@app.route("/api/cameras/buscar")
def api_cameras_buscar():
    try:
        return jsonify(cameras_cfg.buscar())
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": "{}: {}".format(type(e).__name__, e)}), 500


@app.route("/api/cameras/testar", methods=["POST"])
def api_cameras_testar():
    try:
        return jsonify(cameras_cfg.testar_video(request.get_json(silent=True) or {}))
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": "{}: {}".format(type(e).__name__, e)})


@app.route("/api/cameras/adicionar", methods=["POST"])
def api_cameras_adicionar():
    try:
        r = cameras_cfg.adicionar(request.get_json(silent=True) or {})
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "erro": "{}: {}".format(type(e).__name__, e), "passos": []}
    if r.get("ok"):
        print("[{}] câmera adicionada pelo painel: {}".format(r["cid"], r["nome"]))
        r["reiniciando"] = _depois_de_mudar_cameras("câmera nova: {}".format(r["nome"]), r["cid"], "adicionar")
    return jsonify(r)


@app.route("/api/cameras/<cid>/remover", methods=["POST"])
def api_cameras_remover(cid):
    try:
        r = cameras_cfg.remover(cid)
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "erro": "{}: {}".format(type(e).__name__, e)}
    if r.get("ok"):
        print("[{}] câmera removida pelo painel: {}".format(cid, r["nome"]))
        r["reiniciando"] = _depois_de_mudar_cameras("câmera removida: {}".format(r["nome"]), cid, "remover")
    return jsonify(r)


# ---------------- menu ⚙ Config: conta da porta 34567 ----------------
@app.route("/api/config/cameras")
def api_config_cameras():
    try:
        importlib.reload(config)
        lista = config.cameras()
    except Exception as e:
        return jsonify({"ok": False, "erro": "config.py com problema: {}".format(e)}), 500
    sessao_ok = cliente_xm.sessao_rodando() if SESSAO_SEPARADA else None
    cams = []
    for c in lista:
        s = XMS.get(c["cid"])
        cams.append({"cid": c["cid"], "nome": c["nome"], "tipo": c["tipo"], "ip": c.get("ip", ""),
                     "admin_usuario": c.get("admin_usuario") if c["tipo"] == "icsee" else None,
                     "tem_senha": bool(c.get("admin_senha")),
                     "pode": c["tipo"] == "icsee" and s is not None,
                     "conectada": bool(s.conectada) if s is not None else False,
                     "erro": (s.status().get("erro") if s is not None and not s.conectada else None)})
    return jsonify({"ok": True, "sessao_separada": SESSAO_SEPARADA, "sessao_rodando": sessao_ok,
                    "cameras": cams})


@app.route("/api/config/<cid>/conta", methods=["POST"])
def api_config_conta(cid):
    dados = request.get_json(silent=True) or {}
    s = XMS.get(cid)
    if s is None:
        return jsonify({"ok": False, "erro": "essa câmera não usa a porta 34567"}), 404
    if not SESSAO_SEPARADA:
        return jsonify({"ok": False, "erro": "precisa da sessão separada (INICIAR_SESSAO.bat)"}), 400
    r = cliente_xm.reprovisionar(cid, dados.get("modo"), dados.get("senha_fixa", ""),
                                 dados.get("usuario", ""), dados.get("senha", ""))
    if r.get("ok"):
        s.usuario, s.senha = r.get("usuario", s.usuario), r.get("senha", s.senha)   # download do SD usa
        print("[{}] conta da 34567 trocada para {} pelo menu Config".format(cid, s.usuario))
    r.pop("senha", None)                                # a senha não volta pra página
    return jsonify(r)


@app.route("/api/xm/<cid>/tentar", methods=["POST"])
def api_xm_tentar(cid):
    try:
        _xm(cid).tentar_de_novo()
    except camera_xm.ErroXM as e:
        return _xm_erro(e)
    return jsonify({"ok": True})


@app.route("/api/xm/<cid>/recarregar", methods=["POST"])
def api_xm_recarregar(cid):
    try:
        s = _xm(cid)
        s.descobrir()
        return jsonify({"ok": True, "status": s.status()})
    except (camera_xm.ErroXM, ConnectionError) as e:
        return _xm_erro(e)


@app.route("/api/xm/<cid>/volume", methods=["POST"])
def api_xm_volume(cid):
    dados = request.get_json(silent=True) or {}
    try:
        v = _xm(cid).set_volume(int(dados.get("volume")))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "volume deve ser 0 a 100"}), 400
    except (camera_xm.ErroXM, ConnectionError) as e:
        return _xm_erro(e)
    return jsonify({"ok": True, "volume": v})


@app.route("/api/xm/<cid>/luz", methods=["POST"])
def api_xm_luz(cid):
    dados = request.get_json(silent=True) or {}
    try:
        luz = _xm(cid).set_luz(modo=dados.get("modo"), brilho=dados.get("brilho"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "brilho deve ser 0 a 100"}), 400
    except (camera_xm.ErroXM, ConnectionError) as e:
        return _xm_erro(e)
    pedido = dados.get("modo")
    aviso = None
    if pedido and luz.get("modo") != pedido:
        aviso = "a câmera aceitou, mas ficou em '{}'".format(luz.get("modo"))
    return jsonify({"ok": True, "luz": luz, "aviso": aviso})


@app.route("/api/xm/<cid>/alarme", methods=["POST"])
def api_xm_alarme(cid):
    dados = request.get_json(silent=True) or {}
    ligado = dados.get("ligado")
    if not isinstance(ligado, bool):
        return jsonify({"ok": False, "erro": "envie {\"ligado\": true ou false}"}), 400
    try:
        a = _xm(cid).set_alarme(ligado, dados.get("voz"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "voz inválida"}), 400
    except (camera_xm.ErroXM, ConnectionError) as e:
        return _xm_erro(e)
    return jsonify({"ok": True, "alarme": a})


@app.route("/api/xm/<cid>/led", methods=["POST"])
def api_xm_led(cid):
    dados = request.get_json(silent=True) or {}
    try:
        led = _xm(cid).set_led(bool(dados.get("ligado")))
    except (camera_xm.ErroXM, ConnectionError) as e:
        return _xm_erro(e)
    return jsonify({"ok": True, "led": led})


@app.route("/api/xm/<cid>/alerta", methods=["POST"])
def api_xm_alerta(cid):
    """{"ligar": true, "segundos": 10, "som": "sirene_policia.wav" | "" (sirene) | null (sem som)}"""
    dados = request.get_json(silent=True) or {}
    ligar = dados.get("ligar")
    if not isinstance(ligar, bool):
        return jsonify({"ok": False, "erro": "envie {\"ligar\": true ou false}"}), 400
    try:
        segundos = float(dados.get("segundos") or 0)
        s = _xm(cid)
        s.set_alerta(ligar, segundos)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "erro": "segundos inválido"}), 400
    except (camera_xm.ErroXM, ConnectionError) as e:
        return _xm_erro(e)
    resp = {"ok": True, "alerta": s.status()["alerta"]}
    som = dados.get("som")
    if ligar and som is not None:
        try:
            alaw = biblioteca_sons.alaw_de(som) if som else camera_xm.gera_sirene(4.0)
            _, erros = _toca_em([cid], alaw, som or "sirene")
            if erros:
                resp["aviso"] = "luz ligada, mas o som não tocou: " + erros[cid]
        except (biblioteca_sons.ErroSom, camera_xm.ErroXM) as e:
            resp["aviso"] = "luz ligada, mas o som não tocou: {}".format(e)
    return jsonify(resp)


# =============================================================
#  Inverter a imagem NA PRÓPRIA CÂMERA (Camera.Param)
#    PictureFlip   = de cima pra baixo
#    PictureMirror = espelho (esquerda/direita)
#    os dois juntos = girar 180° (câmera de cabeça pra baixo)
#  Vale pra tudo (página, gravações no PC, cartão SD, app),
#  porque a mudança é feita no sensor.
# =============================================================
def _flag_ligado(v):
    """'0x1', '0x00000001', 1, True -> True."""
    if isinstance(v, str):
        try:
            return int(v, 16) != 0
        except ValueError:
            return False
    return bool(v)


def _flag_formato(antigo, liga):
    """Mantém o mesmo formato que a câmera usa ('0x1', '0x00000001', int ou bool)."""
    if isinstance(antigo, str):
        dig = len(antigo[2:]) if antigo.lower().startswith("0x") else 1
        return "0x" + ("1" if liga else "0").rjust(max(1, dig), "0")
    if isinstance(antigo, bool):
        return bool(liga)
    return 1 if liga else 0


def _le_camera_param(s):
    """Devolve (dados_crus, [itens com PictureFlip/PictureMirror])."""
    dados = s.ler("Camera.Param")
    itens = dados if isinstance(dados, list) else [dados]
    tem = [i for i in itens if isinstance(i, dict) and "PictureFlip" in i and "PictureMirror" in i]
    return dados, tem


@app.route("/api/xm/<cid>/inverter", methods=["GET", "POST"])
def api_xm_inverter(cid):
    """GET: estado atual. POST {"acao": "girar"|"flip"|"espelho"|"normal"} (padrão girar)."""
    try:
        s = _xm(cid)
        dados, tem = _le_camera_param(s)
    except (camera_xm.ErroXM, ConnectionError) as e:
        return _xm_erro(e)
    if not tem:
        return jsonify({"ok": False, "erro": "esta câmera não expõe inversão de imagem (Camera.Param)"}), 400

    def estado():
        f = _flag_ligado(tem[0]["PictureFlip"])
        m = _flag_ligado(tem[0]["PictureMirror"])
        return {"flip": f, "espelho": m, "girada": f and m}

    if request.method == "GET":
        return jsonify({"ok": True, **estado()})

    acao = (request.get_json(silent=True) or {}).get("acao", "girar")
    if acao not in ("girar", "flip", "espelho", "normal"):
        return jsonify({"ok": False, "erro": "ação inválida"}), 400

    # para "girar", decide o alvo UMA vez (todas as lentes vão juntas)
    girada_agora = all(_flag_ligado(i["PictureFlip"]) and _flag_ligado(i["PictureMirror"]) for i in tem)
    alvo_girar = not girada_agora

    mudou = False
    for i in tem:
        f, m = _flag_ligado(i["PictureFlip"]), _flag_ligado(i["PictureMirror"])
        if acao == "girar":
            nf = nm = alvo_girar
        elif acao == "flip":
            nf, nm = (not f), m
        elif acao == "espelho":
            nf, nm = f, (not m)
        else:
            nf, nm = False, False
        if (nf, nm) != (f, m):
            i["PictureFlip"] = _flag_formato(i["PictureFlip"], nf)
            i["PictureMirror"] = _flag_formato(i["PictureMirror"], nm)
            mudou = True

    if mudou:
        try:
            s.gravar("Camera.Param", dados)
            _, tem_depois = _le_camera_param(s)
            if tem_depois:
                tem = tem_depois
        except (camera_xm.ErroXM, ConnectionError) as e:
            return _xm_erro(e)
    return jsonify({"ok": True, "mudou": mudou, **estado()})


# =============================================================
#  Cartão SD da câmera (gravações dela mesma)
# =============================================================
SD_TAREFAS = {}        # cid -> sd_xm.TarefaSD (uma por câmera)
SD_CACHE = {}          # (cid, dia) -> (quando, lista)
SD_INFO = {}           # cid -> (quando, info)
_trava_sd = threading.Lock()


def _sd_sessao(cid):
    s = _xm(cid)
    if not s.conectada:
        raise ConnectionError("câmera não está conectada ({})".format(s.status()["erro"]))
    return s


def _sd_lista(cid, dia, forcar=False):
    chave = (cid, dia)
    with _trava_sd:
        em_cache = SD_CACHE.get(chave)
    if em_cache and not forcar and time.time() - em_cache[0] < 60:
        return em_cache[1]
    s = _sd_sessao(cid)
    inicio = datetime.strptime(dia, "%Y-%m-%d")
    lista = sd_xm.listar(s, inicio, inicio + timedelta(hours=23, minutes=59, seconds=59))
    with _trava_sd:
        SD_CACHE[chave] = (time.time(), lista)
    return lista


@app.route("/api/sd/<cid>/info")
def api_sd_info(cid):
    try:
        em_cache = SD_INFO.get(cid)
        if em_cache and time.time() - em_cache[0] < 60 and not request.args.get("forcar"):
            return jsonify(em_cache[1])
        s = _sd_sessao(cid)
        cartao = sd_xm.armazenamento(s)
        hora = sd_xm.hora_camera(s)
        pasta = sd_xm.pasta_camera(cid)
        copias = [f for f in os.listdir(pasta) if f.endswith(".mp4")] if os.path.isdir(pasta) else []
        info = {"ok": True, "cartao": cartao,
                "hoje": (hora or datetime.now()).strftime("%Y-%m-%d"),
                "hora_camera": hora.strftime("%Y-%m-%d %H:%M:%S") if hora else None,
                "copias": len(copias),
                "copias_mb": round(sum(os.path.getsize(os.path.join(pasta, f)) for f in copias) / 1048576, 1)}
        SD_INFO[cid] = (time.time(), info)
        return jsonify(info)
    except (camera_xm.ErroXM, sd_xm.ErroSD, ConnectionError) as e:
        return _xm_erro(e)


@app.route("/api/sd/<cid>/lista")
def api_sd_lista(cid):
    dia = request.args.get("dia") or datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(dia, "%Y-%m-%d")
    except ValueError:
        return jsonify({"ok": False, "erro": "dia inválido (use AAAA-MM-DD)"}), 400
    try:
        lista = _sd_lista(cid, dia, forcar=bool(request.args.get("forcar")))
    except (camera_xm.ErroXM, sd_xm.ErroSD, ConnectionError) as e:
        return _xm_erro(e)
    saida = []
    for a in lista:
        mp4 = sd_xm.caminho_mp4(cid, a)
        saida.append(dict(a, id=os.path.basename(mp4),
                          baixado=os.path.isfile(mp4),
                          url="/sd/{}/{}".format(cid, os.path.basename(mp4)) if os.path.isfile(mp4) else None))
    return jsonify({"ok": True, "dia": dia, "arquivos": saida})


@app.route("/api/sd/<cid>/baixar", methods=["POST"])
def api_sd_baixar(cid):
    dados = request.get_json(silent=True) or {}
    nome, dia = dados.get("nome"), dados.get("dia")
    if not nome or not dia:
        return jsonify({"ok": False, "erro": "faltou o arquivo"}), 400
    try:
        s = _sd_sessao(cid)
        atual = SD_TAREFAS.get(cid)
        if atual and atual.ativa():
            return jsonify({"ok": False, "erro": "já está baixando outra gravação desta câmera"}), 409
        arquivo = next((a for a in _sd_lista(cid, dia) if a["nome"] == nome), None)
        if arquivo is None:
            return jsonify({"ok": False, "erro": "gravação não encontrada no cartão (atualize a lista)"}), 404
        if os.path.isfile(sd_xm.caminho_mp4(cid, arquivo)):
            return jsonify({"ok": True, "pronto": True,
                            "url": "/sd/{}/{}".format(cid, os.path.basename(sd_xm.caminho_mp4(cid, arquivo)))})
        SD_TAREFAS[cid] = sd_xm.TarefaSD(cid, s, arquivo).iniciar()
        print("[sd:{}] baixando {} ({} KB)".format(cid, arquivo["inicio"], arquivo["kb"]))
        return jsonify({"ok": True, "tarefa": SD_TAREFAS[cid].status()})
    except (camera_xm.ErroXM, sd_xm.ErroSD, ConnectionError) as e:
        return _xm_erro(e)


@app.route("/api/sd/<cid>/tarefa")
def api_sd_tarefa(cid):
    t = SD_TAREFAS.get(cid)
    return jsonify(t.status() if t else {"estado": None})


@app.route("/api/sd/<cid>/cancelar", methods=["POST"])
def api_sd_cancelar(cid):
    t = SD_TAREFAS.get(cid)
    if t and t.ativa():
        t.cancelar()
    return jsonify({"ok": True})


@app.route("/api/sd/<cid>/copia/<nome>", methods=["DELETE"])
def api_sd_apagar_copia(cid, nome):
    nome = os.path.basename(nome)
    alvo = os.path.join(sd_xm.pasta_camera(cid), nome)
    if not nome.endswith(".mp4") or not os.path.isfile(alvo):
        return jsonify({"ok": False, "erro": "cópia não encontrada"}), 404
    t = SD_TAREFAS.get(cid)
    if t and t.ativa() and os.path.basename(t.mp4) == nome:
        return jsonify({"ok": False, "erro": "essa gravação ainda está sendo baixada"}), 409
    os.remove(alvo)
    SD_INFO.pop(cid, None)
    return jsonify({"ok": True})


@app.route("/sd/<cid>/<nome>")
def servir_sd(cid, nome):
    return send_from_directory(sd_xm.pasta_camera(cid), os.path.basename(nome))


@app.route("/api/alerta_geral", methods=["POST"])
def api_alerta_geral():
    """Botão de pânico: luz de alerta + som em todas as câmeras conectadas.
    {"ligar": true, "segundos": 15, "som": "sirene_policia.wav" | "" | null}"""
    dados = request.get_json(silent=True) or {}
    ligar = bool(dados.get("ligar", True))
    try:
        segundos = float(dados.get("segundos") or 15)
    except (TypeError, ValueError):
        segundos = 15
    som = dados.get("som", "")
    alaw = None
    if ligar and som is not None:
        try:
            alaw = biblioteca_sons.alaw_de(som) if som else camera_xm.gera_sirene(min(segundos, 10))
        except (biblioteca_sons.ErroSom, camera_xm.ErroXM):
            alaw = camera_xm.gera_sirene(min(segundos, 10))
    feitas, erros = [], {}
    for cid in ORDEM:
        s = XMS.get(cid)
        if s is None:
            continue
        if not s.conectada:
            erros[cid] = "não conectada"
            continue
        try:
            if s.alerta_disponivel:
                s.set_alerta(ligar, segundos)
            feitas.append(cid)
        except (camera_xm.ErroXM, ConnectionError) as e:
            erros[cid] = str(e)
        if ligar and alaw is not None:
            s.parar_fala()
    if ligar and alaw is not None:
        limite = time.time() + 3
        while time.time() < limite and any(XMS[c].falando for c in feitas):
            time.sleep(0.1)                      # espera parar o som que estava tocando
        _, e2 = _toca_em(feitas, alaw, som or "sirene")
        for c, msg in e2.items():
            erros.setdefault(c, msg)
    if not ligar:
        for cid in feitas:
            XMS[cid].parar_fala()
    return jsonify({"ok": bool(feitas), "cameras": feitas, "erros": erros}), (200 if feitas else 409)


@app.route("/api/xm/<cid>/parar", methods=["POST"])
def api_xm_parar(cid):
    try:
        _xm(cid).parar_fala()
    except camera_xm.ErroXM as e:
        return _xm_erro(e)
    return jsonify({"ok": True})


@app.route("/api/som/tocar", methods=["POST"])
def api_som_tocar():
    """{"arquivo": "campainha.wav", "cams": ["cam2"] | "todas"}  (sem arquivo = sirene)"""
    dados = request.get_json(silent=True) or {}
    cids = _cids_do_pedido(dados, dados.get("cid"))
    if not cids:
        return jsonify({"ok": False, "erro": "nenhuma câmera escolhida"}), 400
    arquivo = dados.get("arquivo")
    try:
        if arquivo:
            alaw = biblioteca_sons.alaw_de(arquivo)
            nome = arquivo
        else:
            alaw = camera_xm.gera_sirene(4.0)
            nome = "sirene de teste"
    except (biblioteca_sons.ErroSom, camera_xm.ErroXM) as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    iniciadas, erros = _toca_em(cids, alaw, nome)
    return jsonify({"ok": bool(iniciadas), "tocando_em": iniciadas, "erros": erros,
                    "segundos": round(len(alaw) / 8000.0, 1)}), (200 if iniciadas else 409)


@app.route("/api/som/falar", methods=["POST"])
def api_som_falar():
    """{"texto": "...", "cams": [...], "salvar_como": "opcional",
        "voz": "francisca" | "antonio" | "windows" (opcional)}"""
    import gerar_voz
    dados = request.get_json(silent=True) or {}
    texto = (dados.get("texto") or "").strip()
    voz_pedida = (dados.get("voz") or "").strip() or None
    salvar = (dados.get("salvar_como") or "").strip()
    cids = _cids_do_pedido(dados, dados.get("cid"))
    try:
        if salvar:
            nome = biblioteca_sons.nome_seguro(salvar if salvar.lower().endswith(".wav") else salvar + ".wav")
            destino = os.path.join(biblioteca_sons.PASTA_SONS, nome)
        else:
            os.makedirs(PASTA_TTS, exist_ok=True)
            nome = "voz_temporaria.wav"
            destino = os.path.join(PASTA_TTS, nome)
        voz, aviso_voz = gerar_voz.gerar_detalhado(texto, destino, voz=voz_pedida)
        alaw = camera_xm.arquivo_para_alaw(destino)
    except (gerar_voz.ErroVoz, camera_xm.ErroXM) as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    resp = {"ok": True, "voz": voz, "aviso_voz": aviso_voz,
            "segundos": round(len(alaw) / 8000.0, 1),
            "salvo": nome if salvar else None}
    if cids:
        iniciadas, erros = _toca_em(cids, alaw, "voz: " + texto[:30])
        resp.update({"tocando_em": iniciadas, "erros": erros, "ok": bool(iniciadas) or bool(salvar)})
    return jsonify(resp)


@app.route("/api/vozes", methods=["GET"])
def api_vozes():
    """Vozes do seletor do painel: [{"id": "...", "nome": "..."}]"""
    import gerar_voz
    return jsonify(gerar_voz.lista_vozes())


@app.route("/api/sons", methods=["GET"])
def api_sons_lista():
    return jsonify(biblioteca_sons.listar())


@app.route("/api/sons", methods=["POST"])
def api_sons_upload():
    f = request.files.get("arquivo")
    if f is None or not f.filename:
        return jsonify({"ok": False, "erro": "escolha um arquivo de áudio"}), 400
    try:
        info = biblioteca_sons.salvar_upload(f.filename, f.read())
    except biblioteca_sons.ErroSom as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    print("[sons] recebido: {} ({} s)".format(info["nome"], info["segundos"]))
    return jsonify({"ok": True, **info})


@app.route("/api/sons/<nome>", methods=["DELETE"])
def api_sons_apagar(nome):
    try:
        biblioteca_sons.apagar(nome)
    except biblioteca_sons.ErroSom as e:
        return jsonify({"ok": False, "erro": str(e)}), 404
    return jsonify({"ok": True})


@app.route("/sons/<nome>")
def servir_som(nome):
    return send_from_directory(biblioteca_sons.PASTA_SONS, os.path.basename(nome))


@app.errorhandler(413)
def muito_grande(_):
    return jsonify({"ok": False, "erro": "arquivo maior que 20 MB"}), 413


@app.route("/api/presenca")
def api_presenca():
    """Resposta curta para o ESP32 (usa a 1ª câmera com IA)."""
    for cid in ORDEM:
        if cid in IAS:
            s = IAS[cid].status()
            return jsonify({
                "camera": cid,
                "presenca": s["presenca"],
                "pessoas": s["pessoas"],
                "ia_ativa": s["ativa"],
                "camera_online": CAMERAS[cid].status()["online"],
            })
    return jsonify({"erro": "nenhuma câmera com IA"}), 404


# =============================================================
#  Reconhecimento facial (aba Rostos)
# =============================================================
def _rosto_falar(cid, texto, voz=None):
    """Fala na câmera. O áudio é gerado 1 vez por (texto, voz) e guardado na pasta
    sons; trocar a voz gera um arquivo próprio, sem reaproveitar o antigo."""
    import gerar_voz
    base = rosto_servidor.nome_som(texto)
    if voz:
        sufixo = "_" + re.sub(r"[^A-Za-z0-9]+", "", voz)
        nome = (base[:-4] + sufixo + ".wav") if base.lower().endswith(".wav") else (base + sufixo)
    else:
        nome = base
    destino = os.path.join(biblioteca_sons.PASTA_SONS, nome)
    if not os.path.isfile(destino):
        gerar_voz.gerar(texto, destino, voz=voz)
    alaw = biblioteca_sons.alaw_de(nome)
    _, erros = _toca_em([cid], alaw, "rosto: " + texto[:30])
    if erros:
        raise camera_xm.ErroXM(erros.get(cid, "não tocou"))


_LUZ_ORIGINAL = {}       # cid -> Camera.WhiteLight inteira antes do rosto mexer
_luz_trava = threading.Lock()


def _holofote(cid, estado):
    """Luz branca para os Rostos. True = acende, False = apaga,
    None = volta exatamente como estava antes (ex.: "Intelligent").
    Rápido: lê a config UMA vez e depois só grava o WorkMode (~0,23 s por
    troca medido na cam2; o set_luz antigo lia+gravava+lia = ~0,65 s)."""
    s = _xm(cid)
    with _luz_trava:
        if estado is None:
            base = _LUZ_ORIGINAL.pop(cid, None)
            if isinstance(base, dict):
                s.gravar("Camera.WhiteLight", base)
            else:
                s.set_luz(modo="Close")
            return
        base = _LUZ_ORIGINAL.get(cid)
        if base is None:
            try:
                base = s.ler("Camera.WhiteLight")
            except Exception:
                base = None
            _LUZ_ORIGINAL[cid] = base if isinstance(base, dict) else False
        modo = "KeepOpen" if estado else "Close"
        if isinstance(base, dict):
            s.gravar("Camera.WhiteLight", dict(base, WorkMode=modo))
        else:
            s.set_luz(modo=modo)


def _rec(cid):
    r = RECS.get(cid)
    if r is None:
        raise KeyError("câmera desconhecida")
    if not r.motor.disponivel:
        raise RuntimeError(r.motor.erro or "reconhecimento indisponível")
    return r


@app.route("/api/rosto/<cid>", methods=["POST"])
def api_rosto(cid):
    """{"ativo": true/false} e/ou {"acoes": true/false}"""
    dados = request.get_json(silent=True) or {}
    try:
        r = _rec(cid)
    except (KeyError, RuntimeError) as e:
        return jsonify({"ok": False, "erro": str(e)}), 404
    if isinstance(dados.get("acoes"), bool):
        r.set_acoes(dados["acoes"])
    if isinstance(dados.get("so_com_alerta"), bool):
        r.set_so_com_alerta(dados["so_com_alerta"])
    if isinstance(dados.get("ativo"), bool):
        r.ligar(dados["ativo"])
    return jsonify({"ok": True, "rosto": r.status()})


@app.route("/api/rosto/config", methods=["GET", "POST"])
def api_rosto_config():
    """Config das validações (vale para todas as câmeras).
    GET: config atual + vozes + opções. POST: aplica {frase_ok, frase_negado, voz, acao_negado, segundos}."""
    if request.method == "POST":
        try:
            atual = rosto_servidor.set_cfg(request.get_json(silent=True) or {})
        except ValueError as e:
            return jsonify({"ok": False, "erro": str(e)}), 400
        return jsonify({"ok": True, "cfg": atual})
    import gerar_voz
    try:
        vozes = gerar_voz.lista_vozes()
    except Exception:
        vozes = []
    return jsonify({"ok": True, "cfg": rosto_servidor.cfg(), "vozes": vozes,
                    "acoes": [["alerta", "Luz de alerta (vermelho/azul)"],
                              ["holofote", "Holofote (luz branca)"]]})


@app.route("/api/lente/<cid>", methods=["POST"])
def api_lente(cid):
    """Câmera de 2 lentes: {"lente": "ambas" | "cima" | "baixo"} - onde a IA e os rostos procuram."""
    if cid not in CAMERAS:
        return jsonify({"ok": False, "erro": "câmera desconhecida"}), 404
    lente = (request.get_json(silent=True) or {}).get("lente")
    try:
        lentes.grava(cid, lente)
    except (ValueError, OSError) as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    if cid in IAS:
        IAS[cid].lente = lente
    if cid in RECS:
        RECS[cid].set_lente(lente)
    print("[{}] Detecção em: {}".format(cid, {"ambas": "2 lentes", "cima": "Lente 1", "baixo": "Lente 2"}[lente]))
    return jsonify({"ok": True, "lente": lente})


@app.route("/api/rosto/<cid>/eventos")
def api_rosto_eventos(cid):
    r = RECS.get(cid)
    return jsonify(r.lista_eventos() if r else [])


@app.route("/api/rosto/<cid>/cadastrar", methods=["POST"])
def api_rosto_cadastrar(cid):
    dados = request.get_json(silent=True) or {}
    try:
        r = _rec(cid)
        if not CAMERAS[cid].status()["online"]:
            raise ValueError("a câmera está offline")
        r.cadastrar(dados.get("nome"), bool(dados.get("negado")))
    except (KeyError, RuntimeError, ValueError) as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    return jsonify({"ok": True})


@app.route("/api/rosto/<cid>/cadastro")
def api_rosto_cadastro(cid):
    """Andamento do cadastro (janela de cadastro da página, ~4x por segundo)."""
    rec = RECS.get(cid)
    if rec is None:
        return jsonify({"cadastro": None})
    return jsonify(rec.status_cadastro())


@app.route("/api/rosto/<cid>/cancelar", methods=["POST"])
def api_rosto_cancelar(cid):
    r = RECS.get(cid)
    if r:
        r.cancelar_cadastro()
    return jsonify({"ok": True})


@app.route("/api/rostos/pessoas")
def api_rostos_pessoas():
    if MOTOR_ROSTO is None or not MOTOR_ROSTO.disponivel:
        return jsonify([])
    return jsonify(MOTOR_ROSTO.pessoas())


@app.route("/api/rostos/pessoas/<nome>", methods=["POST", "DELETE"])
def api_rostos_pessoa(nome):
    if MOTOR_ROSTO is None or not MOTOR_ROSTO.disponivel:
        return jsonify({"ok": False, "erro": "reconhecimento indisponível"}), 400
    try:
        if request.method == "DELETE":
            destino = MOTOR_ROSTO.remove(nome)
            print("[rosto] '{}' removido (fotos guardadas em {})".format(nome, destino))
            return jsonify({"ok": True})
        dados = request.get_json(silent=True) or {}
        if not isinstance(dados.get("permitido"), bool):
            return jsonify({"ok": False, "erro": "envie {\"permitido\": true ou false}"}), 400
        MOTOR_ROSTO.muda_permissao(nome, dados["permitido"])
        return jsonify({"ok": True})
    except KeyError:
        return jsonify({"ok": False, "erro": "pessoa não cadastrada"}), 404


@app.route("/rostos/foto/<nome>/<arquivo>")
def rostos_foto(nome, arquivo):
    if MOTOR_ROSTO is None or not MOTOR_ROSTO.disponivel or nome not in MOTOR_ROSTO.banco.pessoas:
        return "não encontrado", 404
    return send_from_directory(os.path.join(rosto_servidor.ia.PASTA_PESSOAS, nome), os.path.basename(arquivo))


@app.route("/rostos/eventos/<cid>/<path:arquivo>")
def rostos_evento(cid, arquivo):
    if cid not in RECS:
        return "não encontrado", 404
    return send_from_directory(os.path.join(rosto_servidor.PASTA_EVENTOS, cid), arquivo)


# =============================================================
#  Alertas da PRÓPRIA câmera (detecção de corpo humano do app iCSee)
#  A sessão 34567 (sessao_xm.py) assina os alarmes (GUARD 1500) e guarda
#  cada AlarmInfo (1504) que a câmera empurra. Aqui uma ronda por câmera
#  busca os novos e deixa a lista pronta para a página.
#  Não usa a IA do PC: a detecção é a da câmera.
#   - Tipo (humano / movimento / os dois): grava na câmera
#     Detect.HumanDetection / Detect.MotionDetect e o servidor também filtra.
#   - "Só quando a câmera detectar" (IA e Rostos): camera_em_alerta(cid).
# =============================================================
ALERTAS_CIDS = set()          # câmeras que mandam alertas (iCSee com sessão 34567)
ALERTAS_CAM = deque(maxlen=200)   # eventos de todas as câmeras (mais novo no fim)
ALERTAS_INFO = {}             # cid -> {"guard": Ret, "erro": texto}
_alertas_trava = threading.Lock()
_alertas_seq = [0]
_alerta_ultima_foto = {}      # cid -> ts
_alerta_estado = {}           # cid -> {"ativo": bool, "inicio": ts, "ate": ts}
ARQ_ALERTAS_MODO = os.path.join(PASTA_BASE, "alertas_modo.json")
NOMES_EVENTO = {
    "appEventHumanDetectAlarm": "Pessoa detectada",
    "HumanDetect": "Pessoa detectada", "HumanDetection": "Pessoa detectada",
    "PersonDetect": "Pessoa detectada", "VideoMotion": "Movimento",
    "appEventMotionDetectAlarm": "Movimento", "MotionDetect": "Movimento",
    "FaceDetection": "Rosto detectado", "FaceDetect": "Rosto detectado",
    "CarShapeDetect": "Veículo detectado", "PetDetect": "Animal detectado",
    "VideoBlind": "Câmera tampada", "VideoLoss": "Sem vídeo",
    "LocalAlarm": "Alarme local", "PIRAlarm": "Sensor de presença",
}


def tipo_evento(evento):
    """'humano' para alertas de pessoa; 'movimento' para o resto."""
    e = (evento or "").lower()
    return "humano" if any(k in e for k in ("human", "person", "pedestrian", "body")) else "movimento"


def le_modos_alerta():
    try:
        with open(ARQ_ALERTAS_MODO, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def salva_modo_alerta(cid, modo):
    d = le_modos_alerta()
    d[cid] = modo
    try:
        with open(ARQ_ALERTAS_MODO, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
    except Exception as erro:
        print("[alerta:{}] não salvei o modo: {!r}".format(cid, erro))


def modo_alerta(cid):
    m = le_modos_alerta().get(cid)
    return m if m in ("humano", "movimento", "ambos") else "ambos"


def camera_em_alerta(cid):
    """True enquanto a câmera está detectando (e ALERTA_CAM_POS_S depois do fim)."""
    agora = time.time()
    with _alertas_trava:
        e = _alerta_estado.get(cid)
        if not e:
            return False
        if agora < e["ate"]:
            return True
        return e["ativo"] and agora - e["inicio"] < ALERTA_CAM_MAX_S


def _foto_do_alerta(cid, ev):
    """Foto em alta do momento do alerta (só com ALERTA_CAM_FOTO = True no config)."""
    try:
        arquivo, _, _ = tirar_foto(CAMERAS[cid], pasta_da_camera(cid))
        with _alertas_trava:
            ev["foto"] = "/fotos/{}/{}".format(cid, arquivo)
    except Exception as erro:
        print("[alerta:{}] sem foto: {}".format(cid, erro))


def _registra_alerta_cam(cid, item):
    evento = item.get("evento") or "?"
    status = item.get("status") or ""
    ts = float(item.get("ts") or time.time())
    tipo = tipo_evento(evento)
    modo = modo_alerta(cid)
    recente = time.time() - ts < 15
    if modo == "humano" and tipo != "humano":
        if recente:
            print("[alerta:{}] ignorado ({} {}): modo só humano".format(cid, evento, status))
        return
    with _alertas_trava:
        cam_estado = (ALERTAS_INFO.get(cid) or {}).get("camera") or {}
    if cam_estado.get("ligado") is False and recente:
        print("[alerta:{}] ignorado ({} {}): alarme inteligente desligado".format(cid, evento, status))
        return
    with _alertas_trava:
        _alertas_seq[0] += 1
        ev = {"seq": _alertas_seq[0], "cid": cid,
              "nome": CAMERAS[cid].nome if cid in CAMERAS else cid,
              "ts": ts, "hora": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
              "evento": evento, "texto": NOMES_EVENTO.get(evento, evento), "tipo": tipo,
              "status": status, "canal": item.get("canal"), "foto": None}
        ALERTAS_CAM.append(ev)
        if recente:                                # abre/fecha o "portão" da IA e dos Rostos
            e = _alerta_estado.setdefault(cid, {"ativo": False, "inicio": 0.0, "ate": 0.0})
            if status == "Stop":
                e["ativo"] = False
            else:
                e["ativo"] = True
                e["inicio"] = time.time()
            e["ate"] = time.time() + ALERTA_CAM_POS_S
    if recente:
        print("[alerta:{}] {} ({}) {} canal={}".format(cid, ev["texto"], evento, status, ev["canal"]))
    if ALERTA_CAM_FOTO and status != "Stop" and recente and cid in CAMERAS:
        if time.time() - _alerta_ultima_foto.get(cid, 0) >= ALERTA_CAM_FOTO_S:
            _alerta_ultima_foto[cid] = time.time()
            threading.Thread(target=_foto_do_alerta, args=(cid, ev), daemon=True).start()


ARQ_LOG_ALARME_CFG = os.path.join(PASTA_BASE, "logs", "alarme_config.log")
DETECCAO_A_CADA_S = 10


def _achata(obj, pre=""):
    """{"a":[{"b":1}]} -> {"a[0].b": 1} (para achar o campo que o app mudou)."""
    saida = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            saida.update(_achata(v, "{}.{}".format(pre, k) if pre else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            saida.update(_achata(v, "{}[{}]".format(pre, i)))
    else:
        saida[pre] = obj
    return saida


def _confere_deteccao(cid, sessao, anterior):
    """Lê a config de detecção da câmera; registra em logs\alarme_config.log
    tudo que mudou (ex.: você mexeu no app). Devolve o novo achatado."""
    bruto = sessao.deteccao_bruta()
    try:                                      # rastreamento (seguir pessoa) da lente móvel
        bruto["Detect.DetectTrack"] = sessao.ler("Detect.DetectTrack")
    except Exception:
        pass
    resumo = camera_xm.SessaoCamera.resumo_deteccao(bruto)
    plano = _achata(bruto)
    if anterior is not None and plano != anterior:
        mudou = ["{}: {} -> {}".format(k, json.dumps(anterior.get(k)), json.dumps(plano.get(k)))
                 for k in sorted(set(plano) | set(anterior)) if plano.get(k) != anterior.get(k)]
        print("[alerta:{}] a config de detecção mudou na câmera (app?): {}".format(
            cid, "; ".join(mudou[:6]) + (" ..." if len(mudou) > 6 else "")))
        try:
            os.makedirs(os.path.dirname(ARQ_LOG_ALARME_CFG), exist_ok=True)
            with open(ARQ_LOG_ALARME_CFG, "a", encoding="utf-8") as f:
                f.write("{}  {}  agora={}\n".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                                   cid, resumo["modo"]))
                for linha in mudou:
                    f.write("    " + linha + "\n")
        except Exception:
            pass
    with _alertas_trava:
        ALERTAS_INFO.setdefault(cid, {})["camera"] = resumo
        if isinstance(bruto.get("Detect.DetectTrack"), dict):
            ALERTAS_INFO[cid]["rastreio"] = _resumo_rastreio(bruto["Detect.DetectTrack"])
    # mudou o tipo no app (corpo humano liga/desliga)? o painel segue a câmera
    if resumo["modo"] in ("humano", "movimento") and modo_alerta(cid) != resumo["modo"]:
        salva_modo_alerta(cid, resumo["modo"])
        print("[alerta:{}] tipo de detecção agora: {} (lido da câmera)".format(cid, resumo["modo"]))
    return plano


def _ronda_alertas_cam(cid, sessao):
    desde, boot = 0, None
    plano, proxima_conf = None, 0.0
    while True:
        try:
            r = sessao.alarmes(desde) or {}
        except camera_xm.ErroXM as erro:          # câmera sem suporte (não insiste)
            with _alertas_trava:
                ALERTAS_INFO.setdefault(cid, {}).update(guard=None, erro=str(erro))
            time.sleep(60)
            continue
        except Exception as erro:                 # sessão fora do ar / câmera deslogada
            with _alertas_trava:
                ALERTAS_INFO.setdefault(cid, {}).update(guard=None, erro=str(erro))
            time.sleep(3)
            continue
        if r.get("conectada") and time.time() >= proxima_conf:
            proxima_conf = time.time() + DETECCAO_A_CADA_S
            try:
                plano = _confere_deteccao(cid, sessao, plano)
                with _alertas_trava:
                    ALERTAS_INFO.setdefault(cid, {})["erro_cfg"] = None
            except Exception as erro:
                with _alertas_trava:
                    ALERTAS_INFO.setdefault(cid, {})["erro_cfg"] = str(erro)
                print("[alerta:{}] não li a config de detecção: {}".format(cid, erro))
        if r.get("boot") != boot:                  # a sessão reiniciou: recomeça a contagem
            boot, desde = r.get("boot"), 0
        for item in r.get("itens") or []:
            if item.get("id", 0) > desde:
                desde = item["id"]
                _registra_alerta_cam(cid, item)
        with _alertas_trava:
            ALERTAS_INFO.setdefault(cid, {}).update(
                guard=r.get("guard"), erro=None if r.get("conectada") else "câmera não está logada na 34567")
        time.sleep(1)


def inicia_alertas_cam():
    for cid in sorted(ALERTAS_CIDS):
        if cid in XMS:
            ALERTAS_INFO[cid] = {"guard": None, "erro": "iniciando"}
            threading.Thread(target=_ronda_alertas_cam, args=(cid, XMS[cid]), daemon=True).start()


def _liga_portoes():
    """IA e Rostos das câmeras com alertas: "só quando a câmera detectar"."""
    for cid in ALERTAS_CIDS:
        portao = (lambda c=cid: camera_em_alerta(c))
        if cid in IAS:
            IAS[cid].portao = portao
        if cid in RECS:
            RECS[cid].portao = portao


@app.route("/api/alertas_camera")
def api_alertas_camera():
    """Alertas da própria câmera (todas). ?cid=cam2 filtra; ?limite=50."""
    cid = request.args.get("cid")
    limite = request.args.get("limite", 60, type=int)
    with _alertas_trava:
        itens = [dict(e) for e in ALERTAS_CAM if not cid or e["cid"] == cid]
        info = {c: dict(v) for c, v in ALERTAS_INFO.items()}
        ultimo = _alertas_seq[0]
    for c in info:
        info[c]["em_alerta"] = camera_em_alerta(c)
        info[c]["modo"] = modo_alerta(c)
    return jsonify({"agora": time.time(), "ultimo": ultimo, "info": info,
                    "itens": itens[-max(1, limite):][::-1]})


def _resumo_rastreio(t):
    """Detect.DetectTrack = "Rastreamento de movimento" do app (lente móvel/PTZ).
    Enable 0/1 · Sensitivity 0 Baixo / 1 Médio / 2 Alto · ReturnTime = "Hora daemon"
    (segundos sem ninguém até a câmera voltar à posição inicial)."""
    return {"ligado": bool(t.get("Enable")), "sensibilidade": t.get("Sensitivity"),
            "volta_s": t.get("ReturnTime")}


@app.route("/api/xm/<cid>/rastreamento", methods=["GET", "POST"])
def api_rastreamento(cid):
    """GET: como está. POST {"ligado": bool, "sensibilidade": 0|1|2, "volta_s": segundos}."""
    dados = request.get_json(silent=True) or {} if request.method == "POST" else {}
    try:
        s = _xm(cid)
        atual = s.ler("Detect.DetectTrack")
        if not isinstance(atual, dict):
            raise camera_xm.ErroXM("esta câmera não tem rastreamento")
        if request.method == "POST":
            novo = dict(atual)
            if isinstance(dados.get("ligado"), bool):
                novo["Enable"] = 1 if dados["ligado"] else 0
            if "sensibilidade" in dados:
                try:
                    v = int(dados["sensibilidade"])
                except (TypeError, ValueError):
                    v = -1
                if v not in (0, 1, 2):
                    return jsonify({"ok": False, "erro": "sensibilidade deve ser 0, 1 ou 2"}), 400
                novo["Sensitivity"] = v
            if "volta_s" in dados:
                try:
                    novo["ReturnTime"] = max(10, min(3600, int(dados["volta_s"])))
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "erro": "volta_s inválido"}), 400
            if novo != atual:
                s.gravar("Detect.DetectTrack", novo)
                print("[rastreio:{}] {} -> {}".format(cid, atual, novo))
            atual = s.ler("Detect.DetectTrack")          # confirma o que ficou
    except (camera_xm.ErroXM, ConnectionError) as erro:
        return jsonify({"ok": False, "erro": str(erro)}), 503
    r = _resumo_rastreio(atual)
    with _alertas_trava:
        ALERTAS_INFO.setdefault(cid, {})["rastreio"] = r
    return jsonify({"ok": True, "rastreio": r})


@app.route("/api/alertas_camera/<cid>/ligado", methods=["POST"])
def api_alertas_ligado(cid):
    """{"ligado": true/false} = o "Alarme inteligente → Ligado" do app."""
    if cid not in ALERTAS_CIDS:
        return jsonify({"ok": False, "erro": "essa câmera não manda alertas"}), 404
    ligado = (request.get_json(silent=True) or {}).get("ligado")
    if not isinstance(ligado, bool):
        return jsonify({"ok": False, "erro": "envie {\"ligado\": true} ou {\"ligado\": false}"}), 400
    try:
        cam = _xm(cid).set_alarme_inteligente(ligado)
    except (camera_xm.ErroXM, ConnectionError) as erro:
        return jsonify({"ok": False, "erro": str(erro)}), 503
    with _alertas_trava:
        ALERTAS_INFO.setdefault(cid, {})["camera"] = cam
    return jsonify({"ok": True, "camera": cam})


@app.route("/api/alertas_camera/<cid>/modo", methods=["GET", "POST"])
def api_alertas_modo(cid):
    """GET: o que está ligado NA CÂMERA. POST {"modo": "humano"|"movimento"|"ambos"}."""
    if cid not in ALERTAS_CIDS:
        return jsonify({"ok": False, "erro": "essa câmera não manda alertas"}), 404
    try:
        s = _xm(cid)
        if request.method == "POST":
            modo = (request.get_json(silent=True) or {}).get("modo")
            if modo not in ("humano", "movimento", "ambos"):
                return jsonify({"ok": False, "erro": "modo deve ser humano, movimento ou ambos"}), 400
            cam = s.set_modo_deteccao(modo)
            salva_modo_alerta(cid, modo)
            with _alertas_trava:
                ALERTAS_INFO.setdefault(cid, {})["camera"] = cam
        else:
            cam = s.modo_deteccao()
            if le_modos_alerta().get(cid) not in ("humano", "movimento"):
                # antigo "os dois" ou nunca escolhido: assume o que está na câmera
                # (com a humana ligada ela só manda alertas de pessoa)
                salva_modo_alerta(cid, "humano" if cam.get("humano") else "movimento")
    except (camera_xm.ErroXM, ConnectionError) as erro:
        return jsonify({"ok": False, "erro": str(erro), "modo": modo_alerta(cid)}), 503
    return jsonify({"ok": True, "modo": modo_alerta(cid), "camera": cam})


# =============================================================
#  Manutenção: status do XM em cache, limpeza, log em arquivo
# =============================================================
_xm_status = {}                 # cid -> último status do XM (cache)
_xm_status_trava = threading.Lock()


def _ronda_status_xm(cid, sessao):
    """Atualiza o status do XM em segundo plano. Se uma câmera travar, só
    esta thread espera — o /status responde na hora com o último valor."""
    while True:
        try:
            s = sessao.status()
        except Exception as erro:
            s = {"estado": "aguardando", "logada": False, "erro": str(erro),
                 "ip": getattr(sessao, "ip", None)}
        with _xm_status_trava:
            _xm_status[cid] = s
        time.sleep(1.5)


def encerrar_gravadores():
    """Fecha os ffmpeg de gravação ao sair (senão ficam órfãos por minutos)."""
    for g in GRAVADORES.values():
        try:
            g.para()
        except Exception:
            pass


atexit.register(encerrar_gravadores)


def _limpa_antigos(base, dias):
    """Apaga arquivos com mais de `dias` em `base` e remove pastas-dia vazias."""
    if dias <= 0 or not os.path.isdir(base):
        return 0
    limite = time.time() - dias * 86400
    apagados = 0
    for raiz, _dirs, arqs in os.walk(base):
        for a in arqs:
            p = os.path.join(raiz, a)
            try:
                if os.path.getmtime(p) < limite:
                    os.remove(p)
                    apagados += 1
            except OSError:
                pass
    for raiz, dirs, arqs in os.walk(base, topdown=False):
        if raiz != base and not os.listdir(raiz):
            try:
                os.rmdir(raiz)
            except OSError:
                pass
    return apagados


def _ronda_limpeza():
    """De tempos em tempos, apaga gravações/fotos/SD/logs antigos (não toca em rostos/)."""
    pastas = [PASTA_GRAV_BASE, PASTA_FOTOS_BASE,
              os.path.join(PASTA_BASE, "sd_baixados"),
              os.path.join(PASTA_BASE, "logs")]
    while True:
        try:
            total = sum(_limpa_antigos(p, GUARDAR_DIAS) for p in pastas)
            if total:
                print("[limpeza] {} arquivo(s) com mais de {} dias apagado(s).".format(total, GUARDAR_DIAS))
        except Exception as erro:
            print("[limpeza] erro: {!r}".format(erro))
        time.sleep(6 * 3600)


class _Tee:
    """Escreve em vários destinos (tela + arquivo) ao mesmo tempo."""
    def __init__(self, *saidas):
        self.saidas = saidas

    def write(self, txt):
        for s in self.saidas:
            try:
                s.write(txt)
                s.flush()
            except Exception:
                pass

    def flush(self):
        for s in self.saidas:
            try:
                s.flush()
            except Exception:
                pass


def _liga_log_arquivo():
    """Além da janela, guarda tudo em logs/central_AAAA-MM-DD.log."""
    try:
        pasta = os.path.join(PASTA_BASE, "logs")
        os.makedirs(pasta, exist_ok=True)
        nome = "central_{}.log".format(datetime.now().strftime("%Y-%m-%d"))
        arq = open(os.path.join(pasta, nome), "a", encoding="utf-8", errors="replace")
        sys.stdout = _Tee(sys.__stdout__, arq)
        sys.stderr = _Tee(sys.__stderr__, arq)
    except Exception as erro:
        print("aviso: não consegui ligar o log em arquivo: {!r}".format(erro))


def _liga_pausa_ociosa():
    """Cada câmera só captura quando tem espectador, IA ou rosto precisando."""
    for cid, cam in CAMERAS.items():
        ia = IAS.get(cid)
        rec = RECS.get(cid)

        def precisa(cam=cam, ia=ia, rec=rec):
            if cam.espectadores > 0:
                return True
            if ia is not None and ia.ativa and ia.liberada():
                return True
            if rec is not None and rec._precisa_video() and rec._portao_aberto():
                return True
            return False

        cam.precisa_frames = precisa


def iniciar_tudo():
    _liga_portoes()
    _liga_pausa_ociosa()
    for cid in ORDEM:
        CAMERAS[cid].iniciar()
    for ia in IAS.values():
        ia.iniciar()
    for s in XMS.values():
        s.iniciar()
    for r in RECS.values():
        r.iniciar()
    # status do XM em cache (uma ronda por câmera, isola travamentos)
    for cid, s in XMS.items():
        _xm_status[cid] = {"estado": "aguardando", "logada": False, "ip": getattr(s, "ip", None)}
        threading.Thread(target=_ronda_status_xm, args=(cid, s), daemon=True).start()
    # alertas da própria câmera (detecção de corpo humano do app)
    inicia_alertas_cam()
    # faxina periódica de arquivos antigos
    threading.Thread(target=_ronda_limpeza, daemon=True).start()
    # PTZ: confirma com cada câmera se ela tem motor (o controle só aparece nas que se mexem)
    for cid, controle in PTZS.items():
        threading.Thread(target=_ronda_ptz, args=(cid, controle), daemon=True, name="ptz-" + cid).start()
    # atualização automática pelo GitHub (não roda no PC com .git)
    threading.Thread(target=atualizador.ronda, args=(_pode_atualizar, _lancador(), _fecha_para_atualizar),
                     daemon=True, name="atualizacao").start()


def _ronda_ptz(cid, controle):
    time.sleep(3)
    espera = 20
    while controle.capaz is None:
        r = controle.verificar()
        if r is not None:
            print("[{}] PTZ: {}".format(cid, "câmera SE MEXE - controle ligado" if r
                                        else "câmera FIXA - controle escondido"))
            return
        time.sleep(espera)
        espera = min(espera * 2, 300)


def encerrar_xm():
    """Logout limpo ao fechar o servidor (Ctrl+C)."""
    for s in XMS.values():
        try:
            s.encerrar()
        except Exception:
            pass


atexit.register(encerrar_xm)


def _ao_sinal(*_):
    raise SystemExit(0)          # garante o logout (atexit) também ao fechar a janela


def preparar_servidor():
    """Monta câmeras, rostos e rondas. Chamar na thread principal (por causa do signal)."""
    _liga_log_arquivo()
    monta_cameras()
    monta_rostos()
    print("=" * 60)
    print(" CENTRAL DE CÂMERAS - {} câmera(s)".format(len(ORDEM)))
    for cid in ORDEM:
        extras = []
        if cid in IAS:
            extras.append("IA")
        if cid in XMS:
            extras.append("alto-falante/luz em {}".format(XMS[cid].ip))
        print("   - {}: {}{}".format(cid, CAMERAS[cid].nome,
                                     "  ({})".format(", ".join(extras)) if extras else ""))
    if XMS and SESSAO_SEPARADA:
        if cliente_xm.sessao_rodando():
            print(" Alto-falante/luz: pela sessão separada (sessao_xm.py) - OK")
        else:
            print(" ATENÇÃO: a sessão das câmeras NÃO está rodando.")
            print("          Abra INICIAR_SESSAO.bat (alto-falante, luz e SD dependem dela).")
    print(" IA, gravação e reconhecimento facial começam DESLIGADOS (ligue pela página).")
    print(" Abra: http://localhost:{}".format(WEB_PORTA))
    print("=" * 60)
    import signal
    signal.signal(signal.SIGTERM, _ao_sinal)
    if hasattr(signal, "SIGBREAK"):          # Windows: Ctrl+Break / fechar console
        signal.signal(signal.SIGBREAK, _ao_sinal)
    iniciar_tudo()


def rodar_web():
    """Sobe a página (bloqueia). A janela própria (janela.py) roda isto numa thread."""
    app.run(host="0.0.0.0", port=WEB_PORTA, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    preparar_servidor()
    rodar_web()
