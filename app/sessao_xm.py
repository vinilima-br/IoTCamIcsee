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
   python app\\sessao_xm.py            (ou app\\INICIAR_SESSAO.bat)
   python app\\sessao_xm.py --checar   (codigo 0 se ja esta rodando, 1 se nao)
Para fechar: Ctrl+C nesta janela (faz logout limpo e apaga a luz de alerta).
"""
import base64
import importlib
import io
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # app/
if PASTA not in sys.path:
    sys.path.append(PASTA)                 # config.py fica na pasta do projeto

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
def monta_sessoes(pular=()):
    for c in config.cameras():
        if not c["xm"]:
            continue
        cid, ip = c["cid"], c["ip"]
        if cid in pular:
            continue
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


# ------------------------------------------------------------------
#  Trocar a conta da 34567 SEM fechar nada (menu ⚙ Config do painel)
#    modo "recuperar": camera recem-resetada -> descobre a conta real e FIXA a senha
#    modo "conta":     voce ja sabe usuario/senha -> so confere e troca
#  Sempre: grava no config.py (com backup), libera a trava e reconecta.
# ------------------------------------------------------------------
_trava_prov = threading.Lock()


def gera_senha_fixa(tamanho=12):
    """Senha forte para fixar na câmera (sem letras que confundem: 0/O, 1/l/I)."""
    import secrets
    letras = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(letras) for _ in range(tamanho))
SENHA_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#_.-!*")


class _SoEstaThread(io.TextIOBase):
    """Copia para 'linhas' o que ESTA thread imprime (o resto segue so na janela)."""
    def __init__(self, original, linhas):
        self.original, self.linhas, self.ident = original, linhas, threading.get_ident()

    def write(self, txt):
        if threading.get_ident() == self.ident:
            for linha in txt.splitlines():
                if linha.strip():
                    self.linhas.append(linha.strip())
        return self.original.write(txt)

    def flush(self):
        self.original.flush()


def _ferramentas():
    pasta = os.path.join(PASTA, "ferramentas")
    if pasta not in sys.path:
        sys.path.insert(0, pasta)
    import provisionar                     # noqa: E402  (recupera_e_fixa / confere_conta / config)
    return provisionar


def _nova_sessao(cid, ip, usuario, senha):
    s = camera_xm.SessaoCamera(cid, ip, usuario, senha, log=log)
    SESSOES[cid] = s
    s.iniciar()
    return s


def reprovisionar(cid, modo, senha_fixa="", usuario="", senha=""):
    passos = []                            # o que ESTA operacao imprimiu (vai pra pagina)

    def passo(msg):
        log("[%s] config: %s" % (cid, msg))

    cam = next((c for c in config.cameras() if c["cid"] == cid), None)
    if cam is None:
        return {"ok": False, "erro": "câmera %s não está no config.py" % cid, "passos": passos}
    if cam["tipo"] != "icsee":
        return {"ok": False, "erro": "só câmeras iCSee (a Elsys usa outro login)", "passos": passos}
    ip = cam["ip"]
    antiga = SESSOES.get(cid)

    if modo == "recuperar":
        senha_fixa = (senha_fixa or "").strip() or cam["admin_senha"]
        if not senha_fixa:              # nenhuma antes: o sistema cria uma forte
            senha_fixa = gera_senha_fixa()
    elif modo == "conta":
        usuario, senha_fixa = (usuario or "").strip(), (senha or "").strip()
        if not usuario or not senha_fixa:
            return {"ok": False, "erro": "preencha usuário e senha", "passos": passos}
    else:
        return {"ok": False, "erro": "modo desconhecido", "passos": passos}
    if len(senha_fixa) < 6 or not set(senha_fixa) <= SENHA_OK:
        return {"ok": False, "erro": "senha: mínimo 6 caracteres, só letras, números e @#_.-!*",
                "passos": passos}
    if modo == "recuperar" and antiga is not None and antiga.conectada:
        return {"ok": False, "passos": passos,
                "erro": "a câmera está CONECTADA com a conta atual - não precisa descobrir "
                        "(e isso trocaria a senha dela). Use só depois de um reset."}
    if not _trava_prov.acquire(blocking=False):
        return {"ok": False, "erro": "já tem uma troca de conta em andamento", "passos": passos}

    linhas = passos
    saida_original = sys.stdout
    sys.stdout = _SoEstaThread(saida_original, linhas)
    try:
        prov = _ferramentas()
        if modo == "conta":
            passo("conferindo a conta %s em %s (não muda nada na câmera)..." % (usuario, ip))
            ok = prov.confere_conta(ip, usuario, senha_fixa)
            conta = (usuario, senha_fixa) if ok else None
            if antiga is not None and conta:
                passo("parando a conexão antiga...")
                antiga.encerrar()
        else:
            if antiga is not None:
                passo("parando a conexão antiga (para não tentar logar com a senha velha)...")
                antiga.encerrar()
            time.sleep(1)
            passo("descobrindo a conta real em %s e fixando a senha (admin/branco do reset)..." % ip)
            conta = prov.recupera_e_fixa(ip, senha_fixa)

        if not conta:
            if antiga is not None and modo == "recuperar":
                passo("não deu: volto a tentar com a conta antiga.")
                _nova_sessao(cid, ip, antiga.usuario, antiga.senha)
            return {"ok": False, "erro": "não consegui (veja os passos)", "passos": linhas}

        user_final, senha_final = conta
        backup = prov.atualiza_conta_no_config(cid, ip, user_final, senha_final)
        importlib.reload(config)
        passo("config.py atualizado (backup: %s)" % os.path.basename(backup))
        # os logins acabaram de acontecer: respeita o intervalo minimo (20 s) e tira a trava velha
        camera_xm.grava_estado(ip, ultima_tentativa=camera_xm.agora(), ultimo_ret=100)
        _nova_sessao(cid, ip, user_final, senha_final)
        passo("reconectando com a conta %s (em ~20 s)." % user_final)
        return {"ok": True, "usuario": user_final, "senha": senha_final,
                "backup": os.path.basename(backup), "passos": linhas}
    except Exception as e:  # noqa: BLE001
        log("[%s] erro na troca de conta: %r" % (cid, e))
        if antiga is not None and SESSOES.get(cid) is antiga and antiga._parar.is_set():
            _nova_sessao(cid, ip, antiga.usuario, antiga.senha)     # nao deixa a camera sem sessao
        return {"ok": False, "erro": "%s: %s" % (type(e).__name__, e), "passos": linhas}
    finally:
        sys.stdout = saida_original
        _trava_prov.release()


def recarregar():
    """Le o config.py de novo (menu ➕ Câmeras): abre sessao das cameras novas e fecha
    a das que sairam / mudaram de IP / ficaram sem som. As outras seguem intactas."""
    importlib.reload(config)
    atuais = {c["cid"]: c for c in config.cameras()}
    fechadas, abertas = [], []
    for cid in list(SESSOES):
        c = atuais.get(cid)
        if c is None or not c["xm"] or c["ip"] != SESSOES[cid].ip:
            try:
                SESSOES.pop(cid).encerrar()
            except Exception as e:  # noqa: BLE001
                log("[%s] erro ao fechar: %r" % (cid, e))
            fechadas.append(cid)
    antes = set(SESSOES)
    monta_sessoes(pular=antes)
    for cid in set(SESSOES) - antes:
        SESSOES[cid].iniciar()
        abertas.append(cid)
    log("recarregar: novas=%s fechadas=%s" % (abertas or "-", fechadas or "-"))
    return {"ok": True, "novas": abertas, "fechadas": fechadas}


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
        if self.path == "/sair":
            # atualização automática: logout limpo e sai com o código 5
            # (o INICIAR_SESSAO.bat fecha; a Central abre a sessão nova)
            self._responde(200, {"ok": True, "pid": os.getpid()})

            def _sai():
                time.sleep(0.5)
                log("fechando a sessao: logout nas cameras...")
                try:
                    encerrar()
                finally:
                    os._exit(5)
            threading.Thread(target=_sai, daemon=True).start()
            return
        if self.path == "/recarregar":
            try:
                self._responde(200, recarregar())
            except Exception as e:  # noqa: BLE001
                self._responde(200, {"ok": False, "erro": "%s: %s" % (type(e).__name__, e)})
            return
        if self.path == "/reprovisionar":
            try:
                tam = int(self.headers.get("Content-Length") or 0)
                p = json.loads(self.rfile.read(tam).decode("utf-8") or "{}")
            except (ValueError, OSError):
                self._responde(400, {"ok": False, "erro": "pedido inválido"})
                return
            self._responde(200, reprovisionar(p.get("cid"), p.get("modo"), p.get("senha_fixa", ""),
                                              p.get("usuario", ""), p.get("senha", "")))
            return
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
