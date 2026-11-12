# -*- coding: utf-8 -*-
"""
sessao_xm.py  -  Sessao SEPARADA e permanente com as cameras iCSee (porta 34567).

Por que existe:
  Cada vez que o servidor era reiniciado ele fazia logout + login nas
  cameras. Com muitos testes seguidos a camera entendia como ataque e
  bloqueava o PC (erro 205). Agora:

    sessao_xm.py  -> loga UMA vez em cada camera e fica rodando (deixe aberto)
    servidor.py   -> pode ser reiniciado quantas vezes quiser: ele so
                     manda os comandos para ca, pelo proprio PC (porta 5051)

  Enquanto esta janela estiver aberta, NENHUM outro programa consegue
  logar na 34567 (o camera_xm.py barra antes de mandar a senha).
  Para rodar os ferramentas\\diag_*.py, feche esta janela antes.

Uso:
   python sessao_xm.py            (ou INICIAR_SESSAO.bat)
   python sessao_xm.py --checar   (codigo 0 se ja esta rodando, 1 se nao)
Para fechar: Ctrl+C nesta janela (faz logout limpo e apaga a luz de alerta).
"""
import base64
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASTA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA)

import camera_xm  # noqa: E402
import config  # noqa: E402
try:
    import elsys_xm  # noqa: E402  (cameras Elsys com login RSA)
except Exception as _e:
    elsys_xm = None
    print("aviso: elsys_xm indisponivel (%r); Elsys nao terao audio/luz" % _e)

camera_xm.PROCESSO_DA_SESSAO = True      # so este processo pode logar na 34567
camera_xm.IP_LOCAL = getattr(config, "XM_IP_LOCAL", "") or ""   # opcional: sair sempre por este IP
PORTA = camera_xm.PORTA_SESSAO

SESSOES = {}       # cid -> camera_xm.SessaoCamera

METODOS = {"status", "falar", "parar_fala", "set_volume", "set_luz", "set_alarme", "set_led",
           "set_alerta", "descobrir", "tentar_de_novo", "comando", "ler", "gravar",
           "alarmes", "modo_deteccao", "set_modo_deteccao", "deteccao_bruta",
           "set_alarme_inteligente"}


def log(msg):
    print("%s %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


# ------------------------------------------------------------------
#  Cameras (lê a MESMA lista do servidor.py: config.cameras())
#  Só entram aqui as que falam pela 34567 (xm=True):
#    iCSee  -> SessaoCamera, com a conta REAL da 34567
#    Elsys  -> ElsysSessao (login RSA "DVRIP-FutureHome")
# ------------------------------------------------------------------
def monta_sessoes():
    for c in config.cameras():
        if not c["xm"]:
            continue
        cid, ip = c["cid"], c["ip"]
        if c["tipo"] == "elsys":
            if elsys_xm is None:
                continue
            try:
                SESSOES[cid] = elsys_xm.ElsysSessao(cid, ip, log=log)
            except Exception as ex:
                log("[%s] Elsys nao montou: %r" % (cid, ex))
        else:  # icsee: conta REAL da 34567 (ver ferramentas\recupera_conta.py)
            SESSOES[cid] = camera_xm.SessaoCamera(
                cid, ip, c["admin_usuario"], c["admin_senha"], log=log)


def estado_resumido():
    cams = {}
    for cid, s in SESSOES.items():
        cams[cid] = {"ip": s.ip, "conectada": s.conectada, "falando": s.falando,
                     "alerta_disponivel": s.alerta_disponivel, "alerta_ligado": s.alerta_ligado,
                     "session": s.session}
    return {"ok": True, "pid": os.getpid(), "cams": cams}


# ------------------------------------------------------------------
#  HTTP (so 127.0.0.1)
# ------------------------------------------------------------------
class Pedido(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass                                       # sem poluir a janela

    def _responde(self, codigo, obj):
        corpo = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if self.path.startswith("/estado"):
            self._responde(200, estado_resumido())
        else:
            self._responde(404, {"ok": False, "erro": "rota desconhecida"})

    def do_POST(self):
        if self.path != "/rpc":
            self._responde(404, {"ok": False, "erro": "rota desconhecida"})
            return
        try:
            tam = int(self.headers.get("Content-Length") or 0)
            pedido = json.loads(self.rfile.read(tam).decode("utf-8") or "{}")
        except (ValueError, OSError):
            self._responde(400, {"ok": False, "tipo": "Erro", "erro": "pedido inválido"})
            return
        cid = pedido.get("cid")
        metodo = pedido.get("metodo")
        args = list(pedido.get("args") or [])
        kwargs = dict(pedido.get("kwargs") or {})
        s = SESSOES.get(cid)
        if s is None:
            self._responde(200, {"ok": False, "tipo": "ErroXM",
                                 "erro": "essa câmera não tem controle de alto-falante/luz"})
            return
        if metodo not in METODOS:
            self._responde(200, {"ok": False, "tipo": "Erro", "erro": "método não permitido: %s" % metodo})
            return
        if not hasattr(s, metodo):          # ex.: Elsys ainda sem alertas da camera
            self._responde(200, {"ok": False, "tipo": "ErroXM",
                                 "erro": "esta câmera não tem '%s'" % metodo})
            return
        if metodo == "falar" and args:
            args[0] = base64.b64decode(args[0])
        try:
            resultado = getattr(s, metodo)(*args, **kwargs)
            self._responde(200, {"ok": True, "r": resultado})
        except camera_xm.ErroXM as e:
            self._responde(200, {"ok": False, "tipo": "ErroXM", "erro": str(e)})
        except ConnectionError as e:
            self._responde(200, {"ok": False, "tipo": "ConnectionError", "erro": str(e)})
        except Exception as e:  # noqa: BLE001
            log("[%s] erro em %s: %r" % (cid, metodo, e))
            self._responde(200, {"ok": False, "tipo": "Erro", "erro": "%s: %s" % (type(e).__name__, e)})


# ------------------------------------------------------------------
def encerrar():
    for s in SESSOES.values():
        try:
            s.encerrar()                 # apaga a luz de alerta e faz logout
        except Exception:
            pass


def _ao_sinal(*_):
    raise SystemExit(0)


def main():
    if "--checar" in sys.argv[1:]:
        sys.exit(0 if camera_xm.sessao_separada_rodando() else 1)

    if camera_xm.sessao_separada_rodando():
        print("A sessao das cameras JA esta rodando (outra janela). Nada a fazer.")
        time.sleep(3)
        return

    try:
        http = ThreadingHTTPServer(("127.0.0.1", PORTA), Pedido)
    except OSError as e:
        print("Nao consegui abrir a porta %d: %s" % (PORTA, e))
        time.sleep(5)
        return
    http.daemon_threads = True

    monta_sessoes()
    print("=" * 62)
    print(" SESSAO DAS CAMERAS (porta 34567) - deixe esta janela ABERTA")
    for cid, s in SESSOES.items():
        print("   - %s: %s" % (cid, s.ip))
    if not SESSOES:
        print("   (nenhuma camera iCSee no config.py)")
    if camera_xm.IP_LOCAL:
        print(" Saindo SEMPRE pelo IP deste PC: %s (XM_IP_LOCAL)" % camera_xm.IP_LOCAL)
    print(" O servidor (INICIAR.bat) pode ser reiniciado a vontade.")
    print(" Para fechar: Ctrl+C (logout limpo).")
    print("=" * 62, flush=True)

    signal.signal(signal.SIGTERM, _ao_sinal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _ao_sinal)

    for s in SESSOES.values():
        s.iniciar()
    threading.Thread(target=http.serve_forever, daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        log("fechando: logout nas cameras...")
        http.shutdown()
        encerrar()
        log("pronto.")


if __name__ == "__main__":
    main()
