# -*- coding: utf-8 -*-
"""
cliente_xm.py  -  Usado pelo servidor.py no lugar da sessao direta.

SessaoRemota tem os mesmos metodos e atributos da camera_xm.SessaoCamera
que o servidor e o sd_xm.py usam, mas NAO loga na camera: repassa tudo
para o sessao_xm.py (porta 5051 do proprio PC), que e quem mantem a
sessao 34567 aberta. Assim reiniciar o servidor nao reloga nas cameras.

Se o sessao_xm.py nao estiver rodando, a pagina mostra o aviso no painel
"Alto-falante e luz" e os comandos respondem "sessao nao esta rodando".
"""
import base64
import json
import threading
import time
import urllib.error
import urllib.request

import camera_xm

URL = "http://127.0.0.1:%d" % camera_xm.PORTA_SESSAO
AVISO_FORA = "a sessão das câmeras não está rodando (abra INICIAR_SESSAO.bat)"

_cache_estado = {"quando": 0.0, "dados": None}
_trava_cache = threading.Lock()


def _http(metodo, caminho, corpo=None, timeout=10.0):
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(URL + caminho, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def estado(max_idade=0.4):
    """Estado de todas as cameras na sessao (com cache curto). None = sessao fora."""
    with _trava_cache:
        if time.time() - _cache_estado["quando"] < max_idade:
            return _cache_estado["dados"]
    dados = _http("GET", "/estado", timeout=2.0)
    with _trava_cache:
        _cache_estado.update(quando=time.time(), dados=dados)
    return dados


def sessao_rodando():
    return estado() is not None


def reprovisionar(cid, modo, senha_fixa="", usuario="", senha=""):
    """Menu ⚙ Config: a sessao troca a conta da 34567 dessa camera (ver sessao_xm.reprovisionar)."""
    r = _http("POST", "/reprovisionar", {"cid": cid, "modo": modo, "senha_fixa": senha_fixa,
                                         "usuario": usuario, "senha": senha}, timeout=90.0)
    if r is None:
        return {"ok": False, "erro": AVISO_FORA, "passos": []}
    if r.get("erro") == "rota desconhecida":
        return {"ok": False, "passos": [], "erro": "a janela da sessão (INICIAR_SESSAO.bat) está com a "
                                                    "versão antiga: feche-a com Ctrl+C e abra de novo"}
    with _trava_cache:
        _cache_estado["quando"] = 0.0
    return r


class SessaoRemota:
    def __init__(self, nome, ip, usuario="admin", senha="", log=print):
        self.nome, self.ip, self.usuario, self.senha = nome, ip, usuario, senha
        self._log = log

    # ---------------- atributos (lidos da sessao) ----------------
    def _attr(self, chave, padrao):
        e = estado()
        if not e:
            return padrao
        return (e.get("cams", {}).get(self.nome) or {}).get(chave, padrao)

    @property
    def conectada(self):
        return bool(self._attr("conectada", False))

    @property
    def falando(self):
        return self._attr("falando", None)

    @property
    def alerta_disponivel(self):
        return bool(self._attr("alerta_disponivel", False))

    @property
    def alerta_ligado(self):
        return bool(self._attr("alerta_ligado", False))

    @property
    def session(self):
        return int(self._attr("session", 0) or 0)

    # ---------------- chamada remota ----------------
    def _rpc(self, metodo, *args, timeout=15.0, **kwargs):
        r = _http("POST", "/rpc", {"cid": self.nome, "metodo": metodo, "args": list(args), "kwargs": kwargs},
                  timeout=timeout)
        if r is None:
            raise ConnectionError(AVISO_FORA)
        if r.get("ok"):
            with _trava_cache:
                _cache_estado["quando"] = 0.0          # algo mudou: relê o estado na próxima
            return r.get("r")
        tipo, erro = r.get("tipo"), r.get("erro") or "erro desconhecido"
        if tipo == "ConnectionError":
            raise ConnectionError(erro)
        if erro.startswith("método não permitido"):
            # o arquivo sessao_xm.py foi atualizado, mas a janela aberta é a antiga
            raise camera_xm.ErroXM("a janela da sessão (INICIAR_SESSAO.bat) está com a versão "
                                   "antiga: feche-a com Ctrl+C e abra de novo")
        raise camera_xm.ErroXM(erro)

    def status(self):
        try:
            return self._rpc("status", timeout=4.0)
        except (ConnectionError, camera_xm.ErroXM) as e:
            return {"estado": "aguardando", "logada": False, "ip": self.ip, "desde": None,
                    "erro": str(e), "proxima_tentativa": None, "falando": None, "volume": None,
                    "luz": None, "alarme": None, "vozes": [], "led": None, "modo_fala": None,
                    "ultima_fala": None, "alerta": None}

    def falar(self, alaw, nome_som="audio", modo=None):
        segundos = len(alaw) / 8000.0
        kwargs = {"modo": modo} if modo else {}
        return self._rpc("falar", base64.b64encode(alaw).decode("ascii"), nome_som,
                         timeout=segundos + 20, **kwargs)

    def comando(self, msgid, obj, timeout=4.0):
        return self._rpc("comando", msgid, obj, timeout, timeout=timeout + 5)

    def parar_fala(self):
        try:
            self._rpc("parar_fala", timeout=4.0)
        except (ConnectionError, camera_xm.ErroXM):
            pass

    def ler(self, nome):
        return self._rpc("ler", nome)

    def gravar(self, nome, dados):
        return self._rpc("gravar", nome, dados)

    def descobrir(self):
        return self._rpc("descobrir", timeout=30.0)

    def tentar_de_novo(self):
        return self._rpc("tentar_de_novo", timeout=4.0)

    def set_volume(self, v):
        return self._rpc("set_volume", v)

    def set_luz(self, modo=None, brilho=None):
        return self._rpc("set_luz", modo=modo, brilho=brilho)

    def set_alarme(self, ligado, voz=None):
        return self._rpc("set_alarme", ligado, voz)

    def set_led(self, ligado):
        return self._rpc("set_led", ligado)

    def set_alerta(self, ligar, segundos=0):
        return self._rpc("set_alerta", ligar, segundos)

    def alarmes(self, desde=0):
        """Alertas da propria camera (deteccao de corpo humano do app) com id > desde."""
        return self._rpc("alarmes", desde, timeout=4.0)

    def modo_deteccao(self):
        return self._rpc("modo_deteccao", timeout=10.0)

    def set_modo_deteccao(self, modo):
        return self._rpc("set_modo_deteccao", modo, timeout=15.0)

    def deteccao_bruta(self):
        return self._rpc("deteccao_bruta", timeout=10.0)

    def set_alarme_inteligente(self, ligado):
        return self._rpc("set_alarme_inteligente", ligado, timeout=15.0)

    # ---------------- ciclo de vida (a sessao e de outro processo) ----------------
    def iniciar(self):
        if not sessao_rodando():
            self._log("[xm:%s] ATENÇÃO: %s" % (self.nome, AVISO_FORA))

    def encerrar(self):
        pass        # de propósito: fechar o servidor NÃO desloga das câmeras
