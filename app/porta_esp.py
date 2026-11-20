# -*- coding: utf-8 -*-
"""
porta_esp.py  -  ESP32 das portas (firmware "PORTA ESP" do ESP32-C6).

  1. ACHA os ESPs na rede sozinho (UDP 4210, mensagem "PORTAESP?") - sem IP fixo;
  2. PAREIA: cria um token só deste painel e grava no ESP (/parear);
  3. CONFIGURA o ESP pelo painel (/config, testes, reiniciar, esquecer Wi-Fi, fábrica);
  4. AVISA o resultado do reconhecimento facial: permitido -> /liberado, o resto -> /negado.

Os ESPs do painel ficam em dados\\estado\\esp_portas.json (de cada PC; não vai pro GitHub):
    {"portas": [{"id": "A1B2C3", "nome": "Portão", "ip": "192.168.3.50", "token": "...",
                 "cameras": [], "ativo": true}]}
    cameras: [] = todas as câmeras; ["cam8"] = só essas.
Se o IP do ESP mudar (DHCP), ele é achado de novo pelo id.
O ESP_PORTAS antigo do config.py é trazido para o json uma vez (se o json não existir).

Cada aviso do facial vai numa thread própria: o reconhecimento nunca espera o ESP.
"""
import json
import os
import secrets
import select
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import caminhos
import config

PORTA_UDP = 4210
TIMEOUT_AVISO_S = 1.5
TIMEOUT_CMD_S = 4.0
RONDA_S = 15
REACHA_MIN_S = 10
CAMPOS_CONFIG = ("nome", "brilho", "ms_lib", "ms_neg", "vida", "rele_on", "rele_pino",
                 "rele_alto", "rele_ms", "rele_int")
COMANDOS = ("liberado", "negado", "reiniciar", "esquecer_wifi", "fabrica")

ARQUIVO = caminhos.estado("esp_portas.json")

# sem proxy: o ESP está na rede local (o Windows pode ter proxy configurado)
_abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_trava = threading.RLock()
_dados = None
_vivo = {}        # chave -> {"online": bool, "status": {...}, "visto": ts, "falhas": n}
_ultimo = {}      # chave -> último aviso do facial
_reachado = {}    # id -> quando tentou achar de novo pela rede
_ronda = None


class ErroESP(Exception):
    pass


# ------------------------------------------------------------------ arquivo
def _grava():
    temp = ARQUIVO + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(_dados, f, indent=2, ensure_ascii=False)
        os.replace(temp, ARQUIVO)
    except OSError as e:
        print("[esp] não gravei o esp_portas.json: {}".format(e))


def _carrega():
    global _dados
    if _dados is not None:
        return _dados
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or not isinstance(d.get("portas"), list):
            raise ValueError("formato inesperado")
        _dados = d
    except FileNotFoundError:
        _dados = {"portas": []}
        for p in getattr(config, "ESP_PORTAS", None) or []:      # formato antigo (config.py)
            if isinstance(p, dict) and p.get("ip"):
                _dados["portas"].append({"id": "", "nome": p.get("nome") or p["ip"], "ip": p["ip"],
                                         "token": p.get("token", ""),
                                         "cameras": list(p.get("cameras") or []), "ativo": True})
        if _dados["portas"]:
            print("[esp] trouxe {} ESP(s) do config.py para o esp_portas.json".format(len(_dados["portas"])))
        _grava()
    except (OSError, ValueError) as e:
        print("[esp] esp_portas.json com problema ({}); guardei como .ruim e comecei vazio".format(e))
        try:
            os.replace(ARQUIVO, ARQUIVO + ".ruim")
        except OSError:
            pass
        _dados = {"portas": []}
    return _dados


def _chave(p):
    return p.get("id") or p.get("ip") or "?"


def _acha(chave):
    with _trava:
        for p in _carrega()["portas"]:
            if chave and chave in (p.get("id"), p.get("ip")):
                return p
    raise ErroESP("esse ESP não está no painel")


def portas():
    with _trava:
        return [dict(p) for p in _carrega()["portas"]]


# ------------------------------------------------------------------ HTTP
def _get(ip, rota, params, timeout):
    url = "http://{}/{}".format(ip, rota)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with _abridor.open(url, timeout=timeout) as r:
        corpo = r.read()
    return json.loads(corpo.decode("utf-8", "replace") or "{}")


def _pedido(p, rota, params=None, timeout=TIMEOUT_CMD_S, reachar=True):
    q = dict(params or {})
    if p.get("token"):
        q["t"] = p["token"]
    try:
        return _get(p["ip"], rota, q, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise ErroESP("o ESP recusou o token (foi pareado com outro painel ou restaurado?)")
        raise ErroESP("o ESP respondeu HTTP {}".format(e.code))
    except (OSError, ValueError) as e:
        if reachar and p.get("id") and _reacha(p):
            return _pedido(p, rota, params, timeout, reachar=False)
        raise ErroESP("não respondeu em {} ({})".format(p.get("ip"), e))


# ------------------------------------------------------------------ achar na rede
def _ips_locais():
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
    return sorted(ip for ip in achados if not ip.startswith(("127.", "169.254.", "0.")))


def descobrir(espera=1.5):
    """Grita "PORTAESP?" em todas as redes deste PC e junta quem responder."""
    locais = _ips_locais()
    socks = []
    for ip in locais:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind((ip, 0))
            s.setblocking(False)
        except OSError:
            continue
        rede = ".".join(ip.split(".")[:3] + ["255"])
        for destino in ("255.255.255.255", rede):
            try:
                s.sendto(b"PORTAESP?", (destino, PORTA_UDP))
            except OSError:
                pass
        socks.append(s)
    achados = {}
    fim = time.time() + espera
    try:
        while socks and time.time() < fim:
            prontos, _, _ = select.select(socks, [], [], max(0.05, fim - time.time()))
            for s in prontos:
                try:
                    dados, origem = s.recvfrom(2048)
                    d = json.loads(dados.decode("utf-8", "replace"))
                except (OSError, ValueError):
                    continue
                if isinstance(d, dict) and d.get("id"):
                    d["ip"] = origem[0]              # o IP de onde veio a resposta
                    achados[d["id"]] = d
    finally:
        for s in socks:
            s.close()
    with _trava:
        meus = {p.get("id") for p in _carrega()["portas"] if p.get("id")}
    lista = sorted(achados.values(), key=lambda d: tuple(int(x) for x in d["ip"].split(".")))
    for d in lista:
        d["no_painel"] = d["id"] in meus
    return {"ok": True, "achados": lista, "redes": [".".join(ip.split(".")[:3]) + ".x" for ip in locais]}


def _reacha(p):
    """O ESP não respondeu no IP guardado: procura pelo id (o IP pode ter mudado)."""
    ide = p.get("id")
    agora = time.time()
    if not ide or agora - _reachado.get(ide, 0) < REACHA_MIN_S:
        return False
    _reachado[ide] = agora
    for d in descobrir(1.2)["achados"]:
        if d["id"] == ide and d["ip"] != p.get("ip"):
            with _trava:
                print("[esp:{}] mudou de IP: {} -> {}".format(p.get("nome") or ide, p.get("ip"), d["ip"]))
                p["ip"] = d["ip"]
                _grava()
            return True
    return False


# ------------------------------------------------------------------ painel
def parear(ide, token_atual=""):
    """Põe um ESP achado na rede no painel, com um token novo só deste painel."""
    if not ide:
        raise ErroESP("faltou o id do ESP")
    alvo = next((d for d in descobrir()["achados"] if d["id"] == ide), None)
    if alvo is None:
        raise ErroESP("não achei esse ESP na rede agora (está ligado e no Wi-Fi?)")
    with _trava:
        existente = next((p for p in _carrega()["portas"]
                          if p.get("id") == ide or (not p.get("id") and p.get("ip") == alvo["ip"])), None)
    if not token_atual and existente is not None:
        token_atual = existente.get("token", "")
    if alvo.get("pareado") and not token_atual:
        raise ErroESP("esse ESP já tem token (de outro painel ou de antes). Digite o token dele, "
                      "ou segure o BOOT 5 s, entre no portal e apague o token")
    novo = secrets.token_hex(8)
    q = {"novo": novo}
    if token_atual:
        q["t"] = token_atual
    try:
        resp = _get(alvo["ip"], "parear", q, TIMEOUT_CMD_S)
    except urllib.error.HTTPError as e:
        raise ErroESP("token errado" if e.code == 403 else "o ESP respondeu HTTP {}".format(e.code))
    except (OSError, ValueError) as e:
        raise ErroESP("o ESP não respondeu ({})".format(e))
    if not resp.get("ok"):
        raise ErroESP(resp.get("erro") or "o ESP recusou")
    with _trava:
        if existente is not None:
            existente.update(id=ide, ip=alvo["ip"], token=novo)
        else:
            _carrega()["portas"].append({"id": ide, "nome": alvo.get("nome") or ide, "ip": alvo["ip"],
                                         "token": novo, "cameras": [], "ativo": True})
        _grava()
        _vivo.pop(ide, None)
        _vivo.pop(alvo["ip"], None)
    print("[esp:{}] pareado ({})".format(alvo.get("nome") or ide, alvo["ip"]))
    return {"ok": True, "id": ide, "nome": alvo.get("nome") or ide, "ip": alvo["ip"]}


def lista():
    with _trava:
        saida = []
        for p in _carrega()["portas"]:
            v = _vivo.get(_chave(p), {})
            saida.append({"id": p.get("id") or "", "nome": p.get("nome") or p.get("ip"), "ip": p.get("ip"),
                          "cameras": list(p.get("cameras") or []), "ativo": p.get("ativo", True),
                          "online": v.get("online"), "status": v.get("status") or {},
                          "visto": v.get("visto"), "ultimo_aviso": _ultimo.get(_chave(p))})
        return saida


def config_ler(chave):
    return _pedido(_acha(chave), "config")


def config_gravar(chave, campos, cameras=None, ativo=None):
    p = _acha(chave)
    params = {}
    for k in CAMPOS_CONFIG:
        if k in (campos or {}):
            v = campos[k]
            if isinstance(v, bool):
                v = "1" if v else "0"
            params[k] = str(v).strip()
    resp = _pedido(p, "config", params)
    with _trava:
        if cameras is not None:
            p["cameras"] = [str(c) for c in cameras]
        if ativo is not None:
            p["ativo"] = bool(ativo)
        if resp.get("nome"):
            p["nome"] = resp["nome"]
        _grava()
    return {"ok": True, "config": resp}


def remover(chave):
    with _trava:
        d = _carrega()
        antes = len(d["portas"])
        d["portas"] = [p for p in d["portas"] if chave not in (p.get("id"), p.get("ip"))]
        if len(d["portas"]) == antes:
            raise ErroESP("esse ESP não está no painel")
        _grava()
        _vivo.pop(chave, None)
    return {"ok": True}


def comando(chave, cmd):
    if cmd not in COMANDOS:
        raise ErroESP("comando inválido")
    p = _acha(chave)
    resp = _pedido(p, cmd)
    removido = False
    if cmd == "fabrica":                 # o ESP apagou o token: não serve mais para este painel
        remover(chave)
        removido = True
    return {"ok": True, "resposta": resp, "removido": removido}


# ------------------------------------------------------------------ ronda (online/offline)
def _ronda_loop():
    while True:
        for p in [p for p in portas()]:
            k0 = _chave(p)
            with _trava:
                falhas = _vivo.get(k0, {}).get("falhas", 0)
            try:
                real = _acha(k0)
            except ErroESP:
                continue                              # tirado do painel no meio da ronda
            try:
                st = _pedido(real, "status", timeout=2.5, reachar=falhas >= 1)
            except ErroESP:
                st = None
            with _trava:
                if st and st.get("id") and not real.get("id"):     # vindo do config.py: aprende o id
                    real["id"] = st["id"]
                    _grava()
                    _vivo.pop(k0, None)
                v = _vivo.setdefault(_chave(real), {"falhas": 0})
                if st:
                    v.update(online=True, status=st, visto=time.time(), falhas=0)
                else:
                    if v.get("online") is not False:
                        print("[esp:{}] offline ({})".format(real.get("nome") or k0, real.get("ip")))
                    v["online"] = False
                    v["falhas"] = v.get("falhas", 0) + 1
        time.sleep(RONDA_S)


def iniciar():
    global _ronda
    with _trava:
        _carrega()
        if _ronda is None:
            _ronda = threading.Thread(target=_ronda_loop, name="esp-ronda", daemon=True)
            _ronda.start()


# ------------------------------------------------------------------ aviso do facial
def _envia(p, rota, cid, quem):
    nome = p.get("nome") or p.get("ip")
    t0 = time.perf_counter()
    reg = {"hora": time.strftime("%Y-%m-%d %H:%M:%S"), "rota": rota, "camera": cid, "pessoa": quem,
           "ok": False, "ms_resposta": None, "erro": None}
    try:
        _pedido(p, rota, timeout=TIMEOUT_AVISO_S)
        reg["ok"] = True
        reg["ms_resposta"] = round((time.perf_counter() - t0) * 1000)
        print("[esp:{}] {} ({} / {}) -> ok em {} ms".format(nome, rota.upper(), cid, quem, reg["ms_resposta"]))
    except ErroESP as e:
        reg["erro"] = str(e)
        print("[esp:{}] {} -> {}".format(nome, rota.upper(), e))
    with _trava:
        _ultimo[_chave(p)] = reg


def avisa(cid, status, quem=None):
    """status do facial: "permitido" -> /liberado ; qualquer outro -> /negado."""
    rota = "liberado" if status == "permitido" else "negado"
    for p in portas():
        if not p.get("ativo", True):
            continue
        cams = p.get("cameras") or []
        if cams and cid not in cams:
            continue
        try:
            real = _acha(_chave(p))
        except ErroESP:
            continue
        threading.Thread(target=_envia, args=(real, rota, cid, quem or "desconhecido"), daemon=True).start()


def estado():
    with _trava:
        return dict(_ultimo)
