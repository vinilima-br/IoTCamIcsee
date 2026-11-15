# -*- coding: utf-8 -*-
"""
lentes.py  -  Câmeras de 2 lentes (ex.: iCSee X6S).

O quadro vem com as duas lentes empilhadas (2304x2592 = 2 x 2304x1296):
  "cima"  = Lente 1 (metade de cima do quadro original)
  "baixo" = Lente 2 (metade de baixo)
  "ambas" = quadro inteiro

Aqui fica a escolha de ONDE a detecção (IA de pessoas e reconhecimento
facial) olha em cada câmera. Salva em lentes_deteccao.json.
"""
import json
import os
import threading

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO = os.path.join(PASTA, "lentes_deteccao.json")
OPCOES = ("ambas", "cima", "baixo")
_trava = threading.Lock()


def eh_duas_lentes(frame):
    """Quadro mais alto que largo (2304x2592) = duas lentes empilhadas."""
    altura, largura = frame.shape[:2]
    return largura > 0 and altura / largura > 0.9


def recorta(frame, lente):
    """Retorna (parte_do_quadro, deslocamento_y). Câmera comum ou "ambas": quadro inteiro."""
    if lente not in ("cima", "baixo") or frame is None or not eh_duas_lentes(frame):
        return frame, 0
    meio = frame.shape[0] // 2
    if lente == "cima":
        return frame[:meio], 0
    return frame[meio:], meio


def pessoas_no_quadro_inteiro(pessoas, dy, altura_parte, altura_total):
    """Caixas da IA de pessoas (0 a 1, relativas à parte) -> relativas ao quadro inteiro."""
    if not dy and altura_parte == altura_total:
        return pessoas
    f = altura_parte / float(altura_total)
    o = dy / float(altura_total)
    convertidas = []
    for p in pessoas:
        q = dict(p)
        q["y1"] = p["y1"] * f + o
        q["y2"] = p["y2"] * f + o
        convertidas.append(q)
    return convertidas


def le():
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return {k: v for k, v in dados.items() if v in OPCOES}
    except (OSError, ValueError):
        return {}


def grava(cid, lente):
    if lente not in OPCOES:
        raise ValueError("lente deve ser: " + ", ".join(OPCOES))
    with _trava:
        dados = le()
        dados[cid] = lente
        temp = ARQUIVO + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(dados, f, indent=2)
        os.replace(temp, ARQUIVO)
