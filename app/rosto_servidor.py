# -*- coding: utf-8 -*-
"""
rosto_servidor.py  -  Reconhecimento facial DENTRO do servidor (aba "Rostos").

- Um reconhecedor por câmera, que SEMPRE começa DESLIGADO (liga pela página).
- Enquanto ligado (ou cadastrando), a câmera passa para o stream Alta
  (rostos maiores = reconhece de mais longe) e volta ao que era ao desligar.
- Decisão firme (rostos_ia.Validador): PERMITIDO / NEGADO (qualquer rosto
  não cadastrado é negado).
- Ações na câmera (se ela tiver alto-falante/luz e a chave estiver ligada):
    PERMITIDO -> fala "Acesso liberado, <nome>" (e apaga a luz, se acesa)
    NEGADO    -> acende a luz de alerta (vermelho/azul)
  Tudo pela sessão da porta 34567 que o servidor já usa (sem login novo).
- Histórico: rostos\\eventos\\<cam>\\AAAA-MM-DD\\*.jpg + rostos\\historico.csv
- Cadastro pela página: junta 20 amostras do rosto em ~10 s.

Ajustes opcionais no config.py:
    ROSTO_FRASE_OK = "Acesso liberado, {nome}"
    ROSTO_FRASE_NEGADO = ""          (vazio = só a luz)
    ROSTO_ALERTA_S = 10
    ROSTO_MAX_POR_SEGUNDO = 4
    ROSTO_USAR_ALTA = True
"""
import csv
import json
import os
import queue
import re
import shutil
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime

import cv2
import numpy as np

import config
import lentes
import rostos_ia as ia

FRASE_OK = getattr(config, "ROSTO_FRASE_OK", "Acesso liberado, {nome}")
FRASE_NEGADO = getattr(config, "ROSTO_FRASE_NEGADO", "")
ALERTA_S = float(getattr(config, "ROSTO_ALERTA_S", 10))
MAX_POR_SEGUNDO = float(getattr(config, "ROSTO_MAX_POR_SEGUNDO", 4))
USAR_ALTA = bool(getattr(config, "ROSTO_USAR_ALTA", True))
TAMANHO_MIN_PX = 80          # menor que isso: longe demais / falso rosto
TAMANHO_CADASTRO_PX = 100
CONFIANCA_MIN = 0.90
AMOSTRAS_CADASTRO = 20
INTERVALO_CADASTRO_S = 0.5
LIMITE_CADASTRO_S = 60
# cadastro guiado: de frente, depois vira para um lado, depois para o outro
# (o "lado" vale qualquer um no começo - assim não importa se a imagem está espelhada/girada)
ETAPAS_CADASTRO = (("frente", 8), ("lado1", 6), ("lado2", 6))
YAW_FRENTE = 0.14            # nariz quase no meio dos olhos
YAW_LADO = 0.20              # nariz deslocado (rosto virado)
PACIENCIA_ETAPA_S = 12       # não conseguiu virar? depois disso aceita do jeito que der

PASTA_EVENTOS = os.path.join(ia.PASTA_ROSTOS, "eventos")
PASTA_REMOVIDOS = os.path.join(ia.PASTA_ROSTOS, "removidos")
ARQ_HISTORICO = os.path.join(ia.PASTA_ROSTOS, "historico.csv")
ARQ_CFG = os.path.join(ia.PASTA_ROSTOS, "config_validacao.json")

# Configuração das AÇÕES nas validações (vale para todas as câmeras).
# Editável pela página; guardada em rostos/config_validacao.json.
#   LIBERADO: ok_falar (frase_ok) e/ou ok_piscar (holofote pisca ok_piscadas
#             vezes, ok_piscar_s acesa + ok_piscar_s apagada)
#   NEGADO:   neg_falar (frase_negado) e/ou neg_luz com acao_negado:
#             "alerta" (LED vermelho/azul) | "holofote" (luz branca), por "segundos"
_CFG_PADRAO = {"frase_ok": FRASE_OK, "frase_negado": FRASE_NEGADO,
               "voz": "", "acao_negado": "alerta", "segundos": ALERTA_S,
               "ok_falar": True, "ok_piscar": False, "ok_piscadas": 3, "ok_piscar_s": 1.0,
               "neg_falar": True, "neg_luz": True,
               "revalidar_s": 5}           # mesma pessoa parada: valida de novo a cada X s (0 = só 1 vez)
PISCAR_MAX = 20
PISCAR_S_MIN, PISCAR_S_MAX = 0.25, 10.0   # 0,25 s ~ o tempo de 1 comando na câmera


def _normaliza(c):
    """Converte o formato antigo e mantém os números dentro dos limites."""
    if c.get("acao_negado") == "nenhum":        # antigo "Só a voz (sem luz)"
        c["acao_negado"] = "alerta"
        c["neg_luz"] = False
    if c.get("acao_negado") not in ("alerta", "holofote"):
        c["acao_negado"] = "alerta"
    for k in ("ok_falar", "ok_piscar", "neg_falar", "neg_luz"):
        c[k] = bool(c.get(k))
    try:
        c["ok_piscadas"] = max(1, min(PISCAR_MAX, int(c.get("ok_piscadas") or 3)))
    except (TypeError, ValueError):
        c["ok_piscadas"] = 3
    try:
        c["ok_piscar_s"] = max(PISCAR_S_MIN, min(PISCAR_S_MAX, float(c.get("ok_piscar_s") or 1.0)))
    except (TypeError, ValueError):
        c["ok_piscar_s"] = 1.0
    try:
        c["segundos"] = max(1.0, min(600.0, float(c.get("segundos") or ALERTA_S)))
    except (TypeError, ValueError):
        c["segundos"] = ALERTA_S
    try:
        v = float(c.get("revalidar_s") if c.get("revalidar_s") is not None else 5)
        c["revalidar_s"] = 0 if v <= 0 else max(2.0, min(300.0, v))
    except (TypeError, ValueError):
        c["revalidar_s"] = 5
    return c
_cfg = dict(_CFG_PADRAO)
_cfg_trava = threading.Lock()


def _carrega_cfg():
    try:
        with open(ARQ_CFG, "r", encoding="utf-8") as f:
            salvo = json.load(f)
        if isinstance(salvo, dict):
            _cfg.update({k: salvo[k] for k in _CFG_PADRAO if k in salvo})
    except Exception:
        pass
    _normaliza(_cfg)


def cfg():
    with _cfg_trava:
        return dict(_cfg)


def set_cfg(novo):
    """Aplica e salva só as chaves conhecidas. Devolve a config atual."""
    with _cfg_trava:
        if "acao_negado" in novo and novo["acao_negado"] not in ("alerta", "holofote", "nenhum"):
            raise ValueError("ação do negado inválida")
        for k in _CFG_PADRAO:
            if k in novo and novo[k] is not None:
                _cfg[k] = novo[k]
        _normaliza(_cfg)
        try:
            os.makedirs(ia.PASTA_ROSTOS, exist_ok=True)
            with open(ARQ_CFG, "w", encoding="utf-8") as f:
                json.dump(_cfg, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print("[rosto] não salvei a config: {}".format(e))
        return dict(_cfg)


_carrega_cfg()

# ---- Histórico em memória (lido do historico.csv na partida) ----
# Assim "Últimos acessos", o resumo de hoje e o "visto por último" de cada
# pessoa continuam valendo depois de fechar e abrir a Central.
_hist_trava = threading.Lock()
_HOJE = {}       # cid  -> {"dia": "AAAA-MM-DD", "liberados": n, "negados": n}
_VISTO = {}      # nome -> "AAAA-MM-DD HH:MM:SS" do último acesso (em qualquer câmera)
_ANTIGOS = {}    # cid  -> últimos eventos do arquivo (o mais novo primeiro)


def _conta(cid, hora, status, nome):
    """Soma um acesso no resumo do dia e marca quando a pessoa foi vista."""
    dia = (hora or "")[:10]
    with _hist_trava:
        h = _HOJE.get(cid)
        if h is None or dia > h["dia"]:
            h = _HOJE[cid] = {"dia": dia, "liberados": 0, "negados": 0}
        if dia == h["dia"]:
            h["liberados" if status == "permitido" else "negados"] += 1
        if nome and hora > _VISTO.get(nome, ""):
            _VISTO[nome] = hora


def resumo_hoje(cid):
    hoje = time.strftime("%Y-%m-%d")
    with _hist_trava:
        h = _HOJE.get(cid)
        if h is None or h["dia"] != hoje:
            return {"liberados": 0, "negados": 0}
        return {"liberados": h["liberados"], "negados": h["negados"]}


def _le_historico(limite=40):
    try:
        with open(ARQ_HISTORICO, "r", newline="", encoding="utf-8-sig") as f:
            linhas = list(csv.reader(f, delimiter=";"))[1:]
    except (OSError, csv.Error, UnicodeError):
        return
    for l in linhas:
        try:
            if len(l) < 5 or len(l[0]) < 19:
                continue
            hora, cid, quem = l[0], l[1], l[3]
            status = "permitido" if l[2].strip().lower() == "permitido" else "negado"
            nome = None if quem in ("", "desconhecido") else quem
            try:
                sim = float(l[4].replace(",", "."))
            except ValueError:
                sim = 0.0
            _conta(cid, hora, status, nome)
            foto = l[5] if len(l) > 5 and l[5] else None
            _ANTIGOS.setdefault(cid, deque(maxlen=limite)).appendleft(
                {"hora": hora, "status": status, "nome": nome, "motivo": "", "sim": round(sim, 2),
                 "foto": foto, "acao": None, "repeticao": False, "falar": False, "mini": None})
        except Exception:  # noqa: BLE001 - linha estragada (ex.: editada à mão): pula
            continue


def _confere_fotos_antigas():
    """Dos acessos lidos do arquivo: acha a miniatura e tira o link de foto que já foi apagada."""
    prefixo = "/rostos/eventos/"
    for eventos in _ANTIGOS.values():
        for ev in eventos:
            foto = ev.get("foto")
            if not foto or not foto.startswith(prefixo):
                ev["foto"] = None
                continue
            caminho = os.path.join(PASTA_EVENTOS, *foto[len(prefixo):].split("/"))
            if not os.path.isfile(caminho):
                ev["foto"] = None
            elif os.path.isfile(caminho[:-4] + "_r.jpg"):
                ev["mini"] = foto[:-4] + "_r.jpg"


_le_historico()
_confere_fotos_antigas()

CORES = {"permitido": (0, 200, 0), "negado": (0, 0, 255), "desconhecido": (0, 0, 255),
         "incerto": (0, 200, 255)}


def nome_som(texto):
    """'Acesso liberado, Vinícius' -> 'rosto_Acesso_liberado_Vinicius.wav' (mesmo padrão do biblioteca_sons)."""
    base = unicodedata.normalize("NFKD", "rosto_" + texto).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")[:60]
    return base + ".wav"


def salva_jpg(caminho, imagem, qualidade=85):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    ok, dados = cv2.imencode(".jpg", imagem, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
    if ok:
        dados.tofile(caminho)          # aceita acentos no caminho (Windows)
    return ok


# =============================================================
#  Motor compartilhado (modelos + cadastro), carregado uma vez
# =============================================================
class Motor:
    def __init__(self):
        self.rostos = None
        self.banco = None
        self.erro = None
        self.trava_banco = threading.Lock()
        try:
            self.rostos = ia.Rostos()
            self.banco = ia.BancoRostos(self.rostos).carrega()
            print("[rosto] Modelos carregados. Cadastro: {} pessoa(s).".format(len(self.banco.pessoas)))
        except SystemExit:
            self.erro = "não consegui carregar os modelos de rosto (veja a janela do servidor)"
        except Exception as e:  # noqa: BLE001
            self.erro = "modelos de rosto: {}".format(e)
        if self.erro:
            print("[rosto] Reconhecimento indisponível: " + self.erro)

    @property
    def disponivel(self):
        return self.rostos is not None

    def recarrega(self):
        with self.trava_banco:
            self.banco.carrega()

    def pessoas(self):
        lista = []
        for nome, p in sorted(self.banco.pessoas.items(), key=lambda t: t[0].lower()):
            lista.append({"nome": nome, "fotos": len(p["fotos"]), "permitido": p["permitido"],
                          "visto": _VISTO.get(nome),
                          "miniatura": "/rostos/foto/{}/{}".format(nome, os.path.basename(p["fotos"][0]))
                          if p["fotos"] else None})
        return lista

    def muda_permissao(self, nome, permitido):
        if nome not in self.banco.pessoas:
            raise KeyError(nome)
        dados = ia.BancoRostos.le_permissoes()
        dados[nome] = {"permitido": bool(permitido)}
        ia.BancoRostos.grava_permissoes(dados)
        self.recarrega()

    def remove(self, nome):
        pasta = os.path.join(ia.PASTA_PESSOAS, nome)
        if nome not in self.banco.pessoas or not os.path.isdir(pasta):
            raise KeyError(nome)
        os.makedirs(PASTA_REMOVIDOS, exist_ok=True)
        destino = os.path.join(PASTA_REMOVIDOS, "{}_{}".format(nome, time.strftime("%Y%m%d_%H%M%S")))
        shutil.move(pasta, destino)            # não apaga: dá para devolver depois
        dados = ia.BancoRostos.le_permissoes()
        dados.pop(nome, None)
        ia.BancoRostos.grava_permissoes(dados)
        self.recarrega()
        return destino

    def conclui_cadastro(self, nome, recortes, negado):
        """Filtra as amostras, compara com quem já existe e salva. Retorna o resumo."""
        bons, ruins, media = ia.filtra_amostras(self.rostos, recortes)
        if len(bons) < 3:
            raise ValueError("poucas amostras boas ({} de {}); chegue mais perto e tente de novo"
                             .format(len(bons), len(recortes)))
        codigos = np.vstack([self.rostos.codigo_do_recorte(r) for r in bons])
        parecido, maior = None, 0.0
        for outro, p in self.banco.pessoas.items():
            if outro == nome:
                continue
            s = float(np.max(codigos @ p["codigos"].T))
            if s > maior:
                parecido, maior = outro, s
        with self.trava_banco:
            ja_existia = nome in self.banco.pessoas
            self.banco.adiciona(nome, bons, False if negado else None)
            self.banco.carrega()
        return {"nome": nome, "aproveitadas": len(bons), "descartadas": len(ruins),
                "semelhanca_media": round(media, 2), "somou": ja_existia,
                "mais_parecido": parecido, "semelhanca_outro": round(maior, 2),
                "alerta_parecido": bool(parecido and maior >= ia.LIMIAR_MESMA_PESSOA),
                "permitido": self.banco.pessoas.get(nome, {}).get("permitido", not negado)}


# =============================================================
#  Um reconhecedor por câmera
# =============================================================
class Reconhecedor:
    def __init__(self, camera, motor, falar=None, alerta=None, holofote=None):
        """Ações na câmera (None = sem alto-falante/luz):
        falar(texto, voz), alerta(ligar, segundos) = LED vermelho/azul,
        holofote(ligar) = luz branca."""
        self.camera = camera
        self.cid = camera.cid
        self.motor = motor
        self._falar = falar
        self._alerta = alerta
        self._holofote = holofote
        self.ativo = False
        self.so_com_alerta = False   # True = so analisa quando a PROPRIA camera detectar
        self.portao = None           # funcao () -> bool (a camera esta em alerta agora?)
        self.acoes = True
        self.lente = lentes.le().get(camera.cid, "ambas")   # câmera de 2 lentes: onde procurar rostos
        self.trava = threading.Lock()
        self.validador = ia.Validador()

        self.atuais = []            # [(caixa, resultado)] da última análise
        self.analisado_em = 0.0
        self.ms = 0.0
        self.por_s = 0.0
        self.largura = 0
        self.eventos = deque(_ANTIGOS.get(self.cid, ()), maxlen=40)   # começa com o que está no histórico
        self.ultimo_evento = None
        self.luz_ate = 0.0
        self.ultima_acao = None     # texto do resultado da última ação (para a página)

        self.cadastro = None        # dict com o andamento do cadastro
        self.em_espera = None       # função () -> bool: OUTRA câmera está cadastrando (pausa esta)
        self._stream_antes = None
        self._fila = queue.Queue()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self._piscando = threading.Lock()
        threading.Thread(target=self._trabalha_acoes, daemon=True).start()

    @property
    def tem_acoes(self):
        return self._falar is not None and (self._alerta is not None or self._holofote is not None)

    def _apaga_luzes(self):
        """Apaga o que estiver aceso de uma validação anterior."""
        if self.luz_ate and self._alerta is not None:
            try:
                self._alerta(False, 0)
            except Exception:
                pass
        if self.luz_ate and self._holofote is not None:
            try:
                self._holofote(None)          # volta ao modo de luz que estava antes
            except Exception:
                pass
        self.luz_ate = 0.0

    def iniciar(self):
        if self.motor.disponivel:
            self.thread.start()

    # ---------------- liga/desliga ----------------
    def _precisa_video(self):
        return self.ativo or (self.cadastro is not None and self.cadastro["estado"] == "capturando")

    def _portao_aberto(self):
        """Com "so quando a camera detectar": so libera durante o alerta da camera.
        O cadastro nunca espera o alerta."""
        if self.cadastro is not None and self.cadastro["estado"] == "capturando":
            return True
        if not self.so_com_alerta or self.portao is None:
            return True
        try:
            return bool(self.portao())
        except Exception:
            return True

    def set_so_com_alerta(self, ligado):
        self.so_com_alerta = bool(ligado)
        print("[rosto:{}] So quando a camera detectar: {}".format(self.cid, "SIM" if ligado else "nao"))
        return True

    def _ajusta_stream(self):
        if not USAR_ALTA:
            return
        if self._precisa_video():
            if self._stream_antes is None:
                self._stream_antes = self.camera.stream
                if self.camera.stream != 0:
                    self.camera.trocar_stream(0)
        elif self._stream_antes is not None:
            if self._stream_antes != 0:
                self.camera.trocar_stream(self._stream_antes)
            self._stream_antes = None

    def ligar(self, ativo):
        if not self.motor.disponivel:
            return False
        with self.trava:
            self.ativo = bool(ativo)
            self.validador = ia.Validador()
            self.atuais = []
        self._ajusta_stream()
        print("[rosto:{}] Reconhecimento {}".format(self.cid, "LIGADO" if ativo else "desligado"))
        return True

    def set_lente(self, lente):
        with self.trava:
            if self.cadastro and self.cadastro["estado"] == "capturando" and lente != self.lente:
                self.cadastro.update(estado="cancelado", msg="a lente mudou no meio do cadastro - comece de novo",
                                     _recortes=[])
            self.lente = lente
            self.validador = ia.Validador()      # recomeça a contagem na lente nova
            self.atuais = []

    def set_acoes(self, ligado):
        self.acoes = bool(ligado)
        return True

    # ---------------- cadastro ----------------
    def cadastrar(self, nome, negado=False):
        nome = ia.nome_seguro(nome or "")
        if not nome:
            raise ValueError("digite o nome da pessoa")
        if len(nome) > 40:
            raise ValueError("nome muito longo (máx. 40 letras)")
        quadro = getattr(self.camera, "frame", None)
        if quadro is not None and lentes.eh_duas_lentes(quadro) and self.lente not in ("cima", "baixo"):
            raise ValueError("esta câmera tem 2 lentes: escolha Lente 1 ou Lente 2 em \"Detectar em\" "
                             "antes de cadastrar (com as 2 lentes juntas a foto sai ruim)")
        with self.trava:
            if self.cadastro and self.cadastro["estado"] == "capturando":
                raise ValueError("já está cadastrando nesta câmera")
            self.cadastro = {"estado": "capturando", "nome": nome, "negado": bool(negado),
                             "amostras": 0, "total": sum(n for _, n in ETAPAS_CADASTRO), "inicio": time.time(),
                             "etapa": 0, "lado1": None, "dica": "Olhe direto para a câmera",
                             "etapas": [{"id": e, "feitas": 0, "total": n, "desde": time.time()}
                                        for e, n in ETAPAS_CADASTRO],
                             "checks": {}, "rosto": None, "px": 0, "min_px": TAMANHO_CADASTRO_PX,
                             "yaw": None, "restante_s": LIMITE_CADASTRO_S, "lente": self.lente,
                             "msg": "olhe para a câmera e vire o rosto devagar", "resultado": None,
                             "_recortes": [], "_ultima": 0.0}
        self._ajusta_stream()
        print("[rosto:{}] Cadastrando '{}'...".format(self.cid, nome))
        return True

    def cancelar_cadastro(self):
        with self.trava:
            if self.cadastro and self.cadastro["estado"] == "capturando":
                self.cadastro.update(estado="cancelado", msg="cancelado - nada foi salvo", _recortes=[])
        self._ajusta_stream()

    @staticmethod
    def _yaw(r):
        """Quanto o rosto está virado: 0 = de frente; < 0 / > 0 = um lado / o outro."""
        pts = r.get("pontos")
        if not pts:
            return None
        (ex1, _), (ex2, _), (nx, _) = pts[0], pts[1], pts[2]
        dist = abs(ex2 - ex1)
        if dist < 4:
            return None
        return (nx - (ex1 + ex2) / 2.0) / dist

    @staticmethod
    def _qualidade(recorte):
        try:
            cinza = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
            return float(cinza.mean()), float(cv2.Laplacian(cinza, cv2.CV_64F).var())
        except Exception:  # noqa: BLE001
            return 128.0, 100.0

    def _cadastro_passo(self, validos, dims=None):
        """dims = (altura e largura do quadro inteiro, deslocamento e altura da parte analisada)."""
        cad = self.cadastro
        agora = time.time()
        if agora - cad["inicio"] > LIMITE_CADASTRO_S:
            cad.update(estado="erro", msg="o tempo acabou ({} s) sem fotos suficientes: chegue mais perto, "
                                          "com o rosto bem iluminado".format(LIMITE_CADASTRO_S), _recortes=[])
            return True
        etapas = cad["etapas"]
        etapa = etapas[cad["etapa"]]
        cad["restante_s"] = int(LIMITE_CADASTRO_S - (agora - cad["inicio"]))
        checks = {"rosto": False, "tamanho": False, "centro": False, "luz": False, "nitidez": False, "pose": False}
        cad["checks"], cad["rosto"], cad["px"], cad["yaw"] = checks, None, 0, None
        if not validos:
            cad["dica"] = cad["msg"] = "Não estou vendo um rosto - olhe para a câmera"
            return False
        r = validos[0]
        x, y, w, h = r["caixa"]
        checks["rosto"] = True
        cad["px"] = w
        checks["tamanho"] = w >= TAMANHO_CADASTRO_PX
        if dims:
            alt, larg, dy, alt_parte = dims
            cad["rosto"] = {"x": x / larg, "y": y / alt, "w": w / larg, "h": h / alt}
            cx, cy = (x + w / 2.0) / larg, (y - dy + h / 2.0) / max(alt_parte, 1)
            checks["centro"] = 0.22 <= cx <= 0.78 and 0.18 <= cy <= 0.82
        else:
            checks["centro"] = True
        brilho, nitidez = self._qualidade(r["recorte"])
        checks["luz"] = 55 <= brilho <= 215
        checks["nitidez"] = nitidez >= 25
        yaw = self._yaw(r)
        cad["yaw"] = None if yaw is None else round(yaw, 2)

        # a pose pedida nesta etapa
        relaxado = agora - etapa["desde"] > PACIENCIA_ETAPA_S and etapa["id"] != "frente"
        if yaw is None:
            pose_ok = True
        elif etapa["id"] == "frente":
            pose_ok = abs(yaw) <= YAW_FRENTE
        elif etapa["id"] == "lado1":
            pose_ok = abs(yaw) >= YAW_LADO
        else:                                   # lado2: o contrário do lado1
            lado1 = cad.get("lado1") or 1
            pose_ok = yaw * lado1 <= -YAW_LADO
        checks["pose"] = pose_ok or relaxado

        if not checks["tamanho"]:
            cad["dica"] = "Chegue mais perto ({} px, precisa de {})".format(w, TAMANHO_CADASTRO_PX)
        elif not checks["centro"]:
            cad["dica"] = "Centralize o rosto no oval"
        elif not checks["pose"]:
            cad["dica"] = {"frente": "Olhe direto para a câmera",
                           "lado1": "Vire o rosto devagar para um lado",
                           "lado2": "Agora vire devagar para o OUTRO lado"}[etapa["id"]]
        elif not checks["luz"]:
            cad["dica"] = "Pouca luz no rosto" if brilho < 55 else "Luz forte demais no rosto"
        else:
            cad["dica"] = {"frente": "Isso! Fique de frente...", "lado1": "Ótimo, segure um pouco...",
                           "lado2": "Quase lá, segure..."}[etapa["id"]]
        cad["msg"] = cad["dica"]

        aceita = checks["tamanho"] and checks["centro"] and checks["pose"] and brilho >= 35
        if aceita and agora - cad["_ultima"] >= INTERVALO_CADASTRO_S:
            if etapa["id"] == "lado1" and yaw is not None and abs(yaw) >= YAW_LADO and not cad.get("lado1"):
                cad["lado1"] = 1 if yaw > 0 else -1
            cad["_recortes"].append(r["recorte"].copy())
            cad["_ultima"] = agora
            etapa["feitas"] += 1
            cad["amostras"] = len(cad["_recortes"])
            if etapa["feitas"] >= etapa["total"] and cad["etapa"] < len(etapas) - 1:
                cad["etapa"] += 1
                etapas[cad["etapa"]]["desde"] = agora
        cad["lado_tela"] = cad.get("lado1")       # para a seta na página
        return cad["amostras"] >= cad["total"]

    def _cadastro_fim(self):
        cad = self.cadastro
        if cad["estado"] == "capturando":
            cad.update(estado="salvando", msg="conferindo as amostras...")
            try:
                r = self.motor.conclui_cadastro(cad["nome"], cad["_recortes"], cad["negado"])
                cad.update(estado="ok", resultado=r, msg="cadastrado")
                print("[rosto:{}] Cadastrado '{}': {} amostras, semelhança {:.2f}".format(
                    self.cid, cad["nome"], r["aproveitadas"], r["semelhanca_media"]))
            except Exception as e:  # noqa: BLE001
                cad.update(estado="erro", msg=str(e))
        cad["_recortes"] = []
        self._ajusta_stream()

    # ---------------- laço principal ----------------
    def _loop(self):
        ultimo_id = 0
        intervalo = 1.0 / max(MAX_POR_SEGUNDO, 0.5)
        contagem, janela = 0, time.time()
        while True:
            if (not self._precisa_video() or not self._portao_aberto()
                    or (self.em_espera is not None and self.em_espera())):
                if self.atuais:
                    with self.trava:
                        self.atuais = []
                time.sleep(0.3)
                continue
            ultimo_id, frame = self.camera.proximo_frame(ultimo_id)
            if frame is None:
                with self.trava:
                    self.atuais = []
                continue
            inicio = time.time()
            parte, dy = lentes.recorta(frame, self.lente)
            try:
                achados, _, _ = self.motor.rostos.analisa(parte)
            except cv2.error as e:
                print("[rosto:{}] erro na análise: {}".format(self.cid, e))
                time.sleep(1)
                continue
            if dy:
                for r in achados:                 # volta para a posição no quadro inteiro
                    x, y, w, h = r["caixa"]
                    r["caixa"] = (x, y + dy, w, h)
            validos = [r for r in achados if r["caixa"][2] >= TAMANHO_MIN_PX and r["conf"] >= CONFIANCA_MIN]

            if self.cadastro is not None and self.cadastro["estado"] == "capturando":
                with self.trava:
                    terminou = self._cadastro_passo(
                        validos, (frame.shape[0], frame.shape[1], dy, parte.shape[0]))
                    self.atuais = [(r["caixa"], {"status": "incerto", "nome": "cadastro", "sim": 0.0})
                                   for r in validos[:1]]
                    self.analisado_em = time.time()
                if terminou:
                    self._cadastro_fim()
            elif self.ativo:
                resultados = [ia.classifica(self.motor.banco, r["codigo"]) for r in validos]
                self.validador.revalidar_s = float(cfg().get("revalidar_s") or 0)
                evento = self.validador.atualiza(resultados)
                with self.trava:
                    self.atuais = [(r["caixa"], res) for r, res in zip(validos, resultados)]
                    self.analisado_em = time.time()
                if evento:
                    self._registra(evento, frame)

            fim = time.time()
            self.ms = (fim - inicio) * 1000
            self.largura = frame.shape[1]
            contagem += 1
            if fim - janela >= 2.0:
                self.por_s = contagem / (fim - janela)
                contagem, janela = 0, fim
            espera = intervalo - (time.time() - inicio)
            if espera > 0:
                time.sleep(espera)

    # ---------------- eventos e ações ----------------
    def _registra(self, evento, frame):
        agora = datetime.now()
        quem = evento["nome"] or "desconhecido"
        marcado = self.sobreposicao(frame, forcar=True)
        rel = "{}/{}_{}_{}.jpg".format(agora.strftime("%Y-%m-%d"), agora.strftime("%H-%M-%S"),
                                        evento["status"], ia.nome_seguro(quem))
        foto = mini = None
        if salva_jpg(os.path.join(PASTA_EVENTOS, self.cid, rel), marcado):
            foto = "/rostos/eventos/{}/{}".format(self.cid, rel)
            mini = self._salva_miniatura(frame, rel)
        # som: só no 1º resultado da pessoa e quando o resultado MUDA (ex.: negado -> permitido).
        # Repetiu o mesmo resultado com ela parada na frente: só o aviso visual (luz), sem falar.
        pres = evento.get("presenca", 0)
        if pres != getattr(self, "_pres_atual", None):
            self._pres_atual, self._falado = pres, None
        chave = (evento["status"], evento["nome"])
        falar = chave != self._falado
        if falar:
            self._falado = chave
        ev = {"hora": agora.strftime("%Y-%m-%d %H:%M:%S"), "status": evento["status"], "nome": evento["nome"],
              "motivo": evento["motivo"], "sim": round(evento["sim"], 2), "foto": foto, "acao": None,
              "repeticao": bool(evento.get("repeticao")), "falar": falar, "mini": mini}
        with self.trava:
            self.eventos.appendleft(ev)
            self.ultimo_evento = ev
        _conta(self.cid, ev["hora"], ev["status"], ev["nome"])
        try:
            novo = not os.path.isfile(ARQ_HISTORICO)
            os.makedirs(ia.PASTA_ROSTOS, exist_ok=True)
            with open(ARQ_HISTORICO, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                if novo:
                    w.writerow(["data_hora", "camera", "resultado", "pessoa", "semelhanca", "foto"])
                w.writerow([ev["hora"], self.cid, ev["status"].upper(), quem, ev["sim"], foto or ""])
        except OSError as e:
            print("[rosto:{}] não gravei o histórico: {}".format(self.cid, e))
        print("[rosto:{}] {} {} ({:.2f})".format(self.cid, ev["status"].upper(), quem, ev["sim"]))
        if self.acoes and self.tem_acoes:
            self._fila.put(ev)

    def _salva_miniatura(self, frame, rel):
        """Recorte pequeno do rosto (para a lista de acessos da página abrir leve)."""
        try:
            with self.trava:
                caixas = [c for c, _ in self.atuais]
            if not caixas:
                return None
            x, y, w, h = max(caixas, key=lambda c: c[2])
            m = int(max(w, h) * 0.35)
            recorte = frame[max(0, y - m):y + h + m, max(0, x - m):x + w + m]
            if recorte.size == 0:
                return None
            lado = 128
            recorte = cv2.resize(recorte, (lado, max(1, int(lado * recorte.shape[0] / recorte.shape[1]))),
                                 interpolation=cv2.INTER_AREA)
            rel_mini = rel[:-4] + "_r.jpg"
            if salva_jpg(os.path.join(PASTA_EVENTOS, self.cid, rel_mini), recorte, 82):
                return "/rostos/eventos/{}/{}".format(self.cid, rel_mini)
        except Exception as e:  # noqa: BLE001
            print("[rosto:{}] miniatura não salva: {}".format(self.cid, e))
        return None

    def _trabalha_acoes(self):
        while True:
            ev = self._fila.get()
            feito = []
            c = cfg()
            voz = c.get("voz") or None
            segundos = float(c.get("segundos") or ALERTA_S)
            falar = ev.get("falar", True)
            try:
                if ev["status"] == "permitido":
                    if time.time() < self.luz_ate:
                        self._apaga_luzes()
                        feito.append("luz apagada")
                    if not falar:                     # mesmo liberado de novo: não repete nada
                        ev["acao"] = "liberado de novo (sem repetir aviso)"
                        self.ultima_acao = ev["acao"]
                        continue
                    if c.get("ok_piscar") and self._holofote is not None:
                        n, t = int(c["ok_piscadas"]), float(c["ok_piscar_s"])
                        if self._piscando.acquire(blocking=False):      # 1 pisca-pisca por vez
                            threading.Thread(target=self._pisca, args=(n, t), daemon=True).start()
                            feito.append("holofote piscando {}x ({:.1f} s)".format(n, t))
                    frase = (c.get("frase_ok") or "").strip()
                    if c.get("ok_falar") and frase and self._falar is not None:
                        texto = frase.format(nome=ev["nome"])
                        self._falar(texto, voz)
                        feito.append('falou "{}"'.format(texto))
                else:
                    acao = c.get("acao_negado", "alerta") if c.get("neg_luz") else "nenhum"
                    if acao == "alerta" and self._alerta is not None:
                        self._alerta(True, segundos)
                        self.luz_ate = time.time() + segundos
                        feito.append("alerta (vermelho/azul) {:.0f} s".format(segundos))
                    elif acao == "holofote" and self._holofote is not None:
                        self._holofote(True)
                        self.luz_ate = time.time() + segundos
                        feito.append("holofote (luz branca) {:.0f} s".format(segundos))
                        threading.Timer(segundos, self._apaga_luzes).start()
                    frase = (c.get("frase_negado") or "").strip()
                    if not falar:
                        feito.append("sem som (negado de novo: só o aviso visual)")
                    elif c.get("neg_falar") and frase and self._falar is not None:
                        self._falar(frase, voz)
                        feito.append('falou "{}"'.format(frase))
                ev["acao"] = ", ".join(feito) or "-"
            except Exception as e:  # noqa: BLE001
                ev["acao"] = "falhou: {}".format(e)
                print("[rosto:{}] ação falhou: {}".format(self.cid, e))
            self.ultima_acao = ev["acao"]

    def _pisca(self, vezes, segundos):
        """Pisca o holofote (luz branca) e no fim volta ao modo que estava."""
        try:
            # cada comando leva ~0,2-0,3 s: desconta esse tempo para manter o ritmo
            for i in range(vezes):
                t0 = time.time()
                self._holofote(True)
                time.sleep(max(0.0, segundos - (time.time() - t0)))
                t0 = time.time()
                self._holofote(False)
                if i < vezes - 1:
                    time.sleep(max(0.0, segundos - (time.time() - t0)))
        except Exception as e:  # noqa: BLE001
            print("[rosto:{}] pisca-pisca falhou: {}".format(self.cid, e))
        finally:
            try:
                self._holofote(None)
            except Exception:
                pass
            self._piscando.release()

    # ---------------- desenho no vídeo ----------------
    def sobreposicao(self, frame, forcar=False):
        with self.trava:
            if not forcar and (not self._precisa_video() or not self.atuais
                               or time.time() - self.analisado_em > 1.5):
                return frame
            atuais = list(self.atuais)
        if not atuais:
            return frame.copy() if forcar else frame
        img = frame.copy()
        esp = max(2, img.shape[1] // 450)
        fonte = max(0.7, img.shape[1] / 1400)
        for (x, y, w, h), res in atuais:
            cor = CORES.get(res["status"], (200, 200, 200))
            if res["nome"] == "cadastro":
                continue                         # no cadastro a janela da página desenha o guia
            elif res["status"] == "permitido":
                texto = "{} {:.0f}%".format(res["nome"], res["sim"] * 100)
            elif res["status"] == "negado":
                texto = "{} NEGADO".format(res["nome"])
            elif res["status"] == "desconhecido":
                texto = "desconhecido"
            else:
                texto = "?"
            texto = ia.texto_simples(texto)
            cv2.rectangle(img, (x, y), (x + w, y + h), cor, esp)
            yt = max(int(30 * fonte), y - 10)
            cv2.putText(img, texto, (x, yt), cv2.FONT_HERSHEY_SIMPLEX, fonte, (0, 0, 0), esp + 3, cv2.LINE_AA)
            cv2.putText(img, texto, (x, yt), cv2.FONT_HERSHEY_SIMPLEX, fonte, cor, esp, cv2.LINE_AA)
        return img

    # ---------------- para a página ----------------
    def status(self):
        with self.trava:
            agora_ok = time.time() - self.analisado_em < 2.0
            rostos = [{"status": res["status"], "nome": res["nome"], "sim": round(res["sim"], 2)}
                      for _, res in self.atuais] if agora_ok else []
            cad = None
            if self.cadastro:
                cad = {k: v for k, v in self.cadastro.items() if not k.startswith("_")}
            return {
                "disponivel": self.motor.disponivel,
                "erro": self.motor.erro,
                "ativo": self.ativo,
                "so_com_alerta": self.so_com_alerta,
                "aguardando_alerta": bool(self.ativo and not self._portao_aberto()),
                "acoes": self.acoes,
                "tem_acoes": self.tem_acoes,
                "ms": round(self.ms),
                "por_s": round(self.por_s, 1) if (self._precisa_video() and self._portao_aberto()) else 0,
                "largura": self.largura,
                "rostos": rostos,
                "ultimo_evento": self.ultimo_evento,
                "ultima_acao": self.ultima_acao,
                "cadastro": cad,
                "pessoas": len(self.motor.banco.pessoas) if self.motor.disponivel else 0,
                "hoje": resumo_hoje(self.cid),
                "lente": self.lente,
                "tem_alerta": self._alerta is not None,
                "tem_holofote": self._holofote is not None,
                "cfg": cfg(),
            }

    def status_cadastro(self):
        """Só o andamento do cadastro (a janela da página pergunta várias vezes por segundo)."""
        with self.trava:
            if not self.cadastro:
                return {"cadastro": None, "lente": self.lente}
            cad = {k: v for k, v in self.cadastro.items() if not k.startswith("_")}
            cad["etapas"] = [{k: v for k, v in e.items() if k != "desde"} for e in cad.get("etapas", [])]
            return {"cadastro": cad, "lente": self.lente}

    def lista_eventos(self, limite=30):
        with self.trava:
            return [dict(e) for e in list(self.eventos)[:limite]]
