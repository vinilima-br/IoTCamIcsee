"""Gestão de pessoas e acessos rodando DENTRO do painel de câmeras (servidor.py).

O servidor.py chama iniciar(servidor) depois de montar as câmeras. A gestão:
  - usa as câmeras, sessões e o reconhecimento facial que o painel já abriu
    (não abre nada de novo, então não briga pela câmera);
  - sobe a API + a tela numa porta própria (GESTAO_PORTA no config.py, padrão 8000);
  - usa o MESMO login do painel: no próprio PC entra direto; de outro aparelho
    precisa ter entrado com a senha do painel.
"""
import logging
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie

logger = logging.getLogger(__name__)

_DESTE_PC = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
_NOMES_DESTE_PC = ("127.0.0.1", "localhost", "::1")
_estado = {"server": None, "thread": None}


def _cabecalhos(scope):
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def _nome_do_host(host):
    host = (host or "").lower()
    return host[1:host.find("]")] if host.startswith("[") else host.split(":")[0]


def checador_de_login(servidor):
    """Mesma regra do _porteiro() do painel, para pedidos HTTP e WebSocket (ASGI)."""
    acesso = servidor.acesso
    flask_app = servidor.app
    serializador = flask_app.session_interface.get_signing_serializer(flask_app)
    nome_cookie = flask_app.config.get("SESSION_COOKIE_NAME", "session")
    validade = int(flask_app.permanent_session_lifetime.total_seconds())

    def pode(scope):
        cab = _cabecalhos(scope)
        host = cab.get("host", "")
        # 1) Pedido que muda algo vindo de outra página aberta no navegador: recusa.
        muda = scope["type"] == "websocket" or scope.get("method", "GET") not in ("GET", "HEAD", "OPTIONS")
        origem = cab.get("origin")
        if muda and origem is not None:
            try:
                if urllib.parse.urlsplit(origem).netloc.lower() != host.lower():
                    return False
            except ValueError:
                return False
        # 2) Próprio PC: entra direto
        cliente = (scope.get("client") or ("", 0))[0]
        if cliente in _DESTE_PC and _nome_do_host(host) in _NOMES_DESTE_PC:
            return True
        # 3) Outro aparelho: só com o login do painel
        if serializador is None or not acesso.tem_senha():
            return False
        biscoito = SimpleCookie()
        try:
            biscoito.load(cab.get("cookie", ""))
        except Exception:
            return False
        valor = biscoito.get(nome_cookie)
        if valor is None:
            return False
        try:
            dados = serializador.loads(valor.value, max_age=validade)
        except Exception:
            return False
        return isinstance(dados, dict) and dados.get("v") == acesso.versao()

    return pode


def iniciar(servidor, porta=8000, host="0.0.0.0", espera_s=15.0):
    """Sobe a gestão numa thread. Levanta RuntimeError se não conseguir abrir a porta."""
    if _estado["server"] is not None:
        return
    import uvicorn

    from .camera_bridge import camera_bridge
    from .main import app

    camera_bridge.attach(servidor, auth=checador_de_login(servidor))
    # log_config=None: não reconfigura o log do processo. O painel troca a saída do console
    # pelo _Tee (tela + logs/central_*.log), que o formatador colorido do uvicorn não aceita.
    config = uvicorn.Config(app, host=host, port=int(porta), log_level="warning",
                            access_log=False, log_config=None)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="gestao-pessoas")
    thread.start()
    limite = time.monotonic() + espera_s
    while time.monotonic() < limite and thread.is_alive() and not server.started:
        time.sleep(0.1)
    if not server.started:
        server.should_exit = True
        raise RuntimeError("a gestão não abriu a porta {} (já tem outro programa nela? "
                           "a Portaria isolada está aberta?)".format(porta))
    _estado.update(server=server, thread=thread)
    logger.info("Gestão de pessoas embutida no painel, porta %s.", porta)


def parar():
    server = _estado.get("server")
    if server is not None:
        server.should_exit = True
        _estado["server"] = None
