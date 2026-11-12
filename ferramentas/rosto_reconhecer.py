# =============================================================
#  rosto_reconhecer.py - Reconhecimento facial, ETAPA 3: ao vivo
#
#  Reconhece quem aparece na câmera e decide:
#    PERMITIDO -> pessoa cadastrada e permitida
#    NEGADO    -> qualquer rosto NÃO cadastrado (ou cadastrado com --negado)
#
#  Cada decisão aparece na tela/console e salva uma foto em rostos\eventos\.
#
#  ETAPA 4 (--acao): a decisão vira ação na câmera, PELO SERVIDOR
#  (ele é o dono da sessão na porta 34567; este script nunca loga nela):
#    PERMITIDO -> fala "Acesso liberado, <nome>" (e apaga a luz, se acesa)
#    NEGADO    -> acende a luz de alerta (LED vermelho/azul) por 10 s
#  Precisa do servidor rodando (INICIAR.bat).
#
#  Uso (dentro da pasta do projeto):
#    python ferramentas\rosto_reconhecer.py cam2              só mostra
#    python ferramentas\rosto_reconhecer.py cam2 --acao       mostra e age na cam2
#    python ferramentas\rosto_reconhecer.py cam2 --leve       stream leve
#
#  Ajustes opcionais no config.py (se não existirem, valem estes):
#    ROSTO_FRASE_OK = "Acesso liberado, {nome}"
#    ROSTO_FRASE_NEGADO = ""          (vazio = só a luz, sem som)
#    ROSTO_ALERTA_S = 10              (segundos de luz no negado)
#
#  Na janela:  S = salva foto   R = recarrega o cadastro   Q / ESC = sair
#
#  Não usa a porta 34567 (só vídeo), pode rodar com o servidor ligado.
# =============================================================

import json
import os
import queue
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request

PASTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PASTA_BASE)

import rostos_ia as ia  # noqa: E402  (antes do cv2: configura RTSP/TCP e logs)
import cv2  # noqa: E402

TAMANHO_MIN_PX = 80        # rosto menor que isso é ignorado (longe demais / falso rosto)
CONFIANCA_MIN = 0.90
PASTA_EVENTOS = os.path.join(ia.PASTA_ROSTOS, "eventos")
PASTA_FOTOS = os.path.join(ia.PASTA_ROSTOS, "testes")

CORES = {
    "permitido": (0, 200, 0),
    "negado": (0, 0, 255),
    "desconhecido": (0, 0, 255),
    "incerto": (0, 200, 255),
}


def rotulo(r):
    if r["status"] == "permitido":
        return "{} {:.2f}".format(r["nome"], r["sim"])
    if r["status"] == "negado":
        return "{} (NEGADO) {:.2f}".format(r["nome"], r["sim"])
    if r["status"] == "desconhecido":
        return "desconhecido {:.2f}".format(r["sim"])
    return "? {} {:.2f}".format(r["nome"], r["sim"])


def desenha(quadro, rostos, resultados, ignorados, cabecalho, faixa):
    largura = quadro.shape[1]
    esp = max(2, largura // 500)
    fonte = max(0.6, largura / 1500)
    for r in ignorados:
        x, y, w, h = r["caixa"]
        cv2.rectangle(quadro, (x, y), (x + w, y + h), (128, 128, 128), max(1, esp // 2))
    for rosto, res in zip(rostos, resultados):
        x, y, w, h = rosto["caixa"]
        cor = CORES[res["status"]]
        cv2.rectangle(quadro, (x, y), (x + w, y + h), cor, esp)
        texto = ia.texto_simples(rotulo(res))
        cv2.putText(quadro, texto, (x, max(30, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, fonte, (0, 0, 0),
                    esp + 3, cv2.LINE_AA)
        cv2.putText(quadro, texto, (x, max(30, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, fonte, cor, esp, cv2.LINE_AA)
    tela = ia.cabe_na_tela(quadro)
    f = max(0.6, tela.shape[1] / 1300)
    cv2.rectangle(tela, (0, 0), (tela.shape[1], int(36 * f) + 8), (0, 0, 0), -1)
    cv2.putText(tela, cabecalho, (10, int(28 * f)), cv2.FONT_HERSHEY_SIMPLEX, f, (255, 255, 255), 2, cv2.LINE_AA)
    if faixa:
        texto, cor, ate = faixa
        if time.time() < ate:
            altura = tela.shape[0]
            cv2.rectangle(tela, (0, altura - int(60 * f)), (tela.shape[1], altura), cor, -1)
            cv2.putText(tela, texto, (14, altura - int(18 * f)), cv2.FONT_HERSHEY_SIMPLEX, f * 1.4,
                        (255, 255, 255), 3, cv2.LINE_AA)
    return tela


def salva_jpg(pasta, nome, imagem):
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, nome)
    ok, dados = cv2.imencode(".jpg", imagem, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if ok:
        dados.tofile(caminho)
    return caminho


class Estatistica:
    """Junta as semelhanças de 5 em 5 s para calibrar os limites."""

    def __init__(self):
        self.zera()

    def zera(self):
        self.inicio = time.time()
        self.analises = 0
        self.por_chave = {}

    def soma(self, resultados):
        self.analises += 1
        for r in resultados:
            chave = r["nome"] if r["status"] in ("permitido", "negado") else r["status"]
            lista = self.por_chave.setdefault(chave, [])
            lista.append(r["sim"])

    def linha(self):
        dur = max(0.001, time.time() - self.inicio)
        partes = ["{:.1f} análises/s".format(self.analises / dur)]
        for chave, sims in sorted(self.por_chave.items(), key=lambda t: str(t[0])):
            partes.append("{}: {}x  sim {:.2f}–{:.2f}".format(chave, len(sims), min(sims), max(sims)))
        if len(partes) == 1:
            partes.append("nenhum rosto")
        return " | ".join(partes)


# -------------------------------------------------------------
#  Etapa 4: ações pela API do servidor
# -------------------------------------------------------------
def nome_som(texto):
    """Mesmo padrão do biblioteca_sons.nome_seguro: 'Acesso liberado, Vinícius' -> 'rosto_Acesso_liberado_Vinicius.wav'."""
    base = unicodedata.normalize("NFKD", "rosto_" + texto).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")[:60]
    return base + ".wav"


class Acoes:
    """Manda os comandos ao servidor numa fila (um de cada vez, sem travar o vídeo)."""

    def __init__(self, cid):
        import config
        self.cid = cid
        self.base = "http://127.0.0.1:{}".format(getattr(config, "WEB_PORTA", 5050))
        self.frase_ok = getattr(config, "ROSTO_FRASE_OK", "Acesso liberado, {nome}")
        self.frase_negado = getattr(config, "ROSTO_FRASE_NEGADO", "")
        self.alerta_s = float(getattr(config, "ROSTO_ALERTA_S", 10))
        self.pasta_sons = os.path.join(ia.PASTA_BASE, "sons")
        self.luz_ate = 0.0
        self.fila = queue.Queue()
        threading.Thread(target=self._trabalha, daemon=True).start()

    # ---- HTTP ----
    def _pede(self, metodo, caminho, dados=None, timeout=20):
        corpo = json.dumps(dados).encode("utf-8") if dados is not None else None
        pedido = urllib.request.Request(self.base + caminho, data=corpo, method=metodo,
                                        headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as erro:
            try:
                return erro.code, json.loads(erro.read().decode("utf-8") or "{}")
            except ValueError:
                return erro.code, {"erro": "HTTP {}".format(erro.code)}
        except (urllib.error.URLError, OSError, ValueError) as erro:
            return 0, {"erro": str(erro)}

    def confere(self):
        """True se o servidor responde e a câmera tem alto-falante/luz. Mostra o estado."""
        status, dados = self._pede("GET", "/api/xm/{}/status".format(self.cid), timeout=5)
        if status == 0:
            print("O servidor não respondeu em {}. Suba o servidor (INICIAR.bat) e rode de novo.".format(self.base))
            return False
        if status != 200:
            print("A {} não tem controle de alto-falante/luz: {}".format(self.cid, dados.get("erro")))
            return False
        if dados.get("estado") != "conectada":
            print("ATENÇÃO: a {} ainda não está logada na porta 34567 ({}). As ações vão falhar até ela "
                  "ficar verde na página.".format(self.cid, dados.get("erro")))
        else:
            print("Servidor OK, {} conectada. Ações ligadas.".format(self.cid))
        if dados.get("alerta") is None:
            print("ATENÇÃO: o servidor diz que a {} não tem luz de alerta.".format(self.cid))
        return True

    # ---- fila ----
    def evento(self, ev):
        self.fila.put(ev)

    def _trabalha(self):
        while True:
            ev = self.fila.get()
            try:
                if ev["status"] == "permitido":
                    self._permitido(ev["nome"])
                else:
                    self._negado()
            except Exception as erro:  # noqa: BLE001
                print("   ação: erro inesperado: {}".format(erro))

    def _fala(self, texto):
        arquivo = nome_som(texto)
        if os.path.isfile(os.path.join(self.pasta_sons, arquivo)):
            status, r = self._pede("POST", "/api/som/tocar", {"arquivo": arquivo, "cams": [self.cid]})
        else:   # 1ª vez: gera a voz, toca e guarda em sons\ (nas próximas já toca na hora)
            status, r = self._pede("POST", "/api/som/falar",
                                   {"texto": texto, "cams": [self.cid], "salvar_como": arquivo})
            if r.get("ok") and r.get("voz") and "pt" not in r["voz"].lower() and "maria" not in r["voz"].lower():
                print("   aviso: voz usada '{}'. Se saiu em inglês, instale a voz pt-BR no Windows "
                      "e apague sons\\{}".format(r["voz"], arquivo))
        erros = (r.get("erros") or {}).get(self.cid) or r.get("erro")
        if status == 200 and not erros:
            print("   ação: falando \"{}\"".format(texto))
        else:
            print("   ação: não falou ({})".format(erros or "HTTP {}".format(status)))

    def _permitido(self, nome):
        if time.time() < self.luz_ate:            # a luz ficou acesa de um negado anterior
            self._pede("POST", "/api/xm/{}/alerta".format(self.cid), {"ligar": False})
            self.luz_ate = 0.0
            print("   ação: luz de alerta apagada")
        if self.frase_ok:
            self._fala(self.frase_ok.format(nome=nome))

    def _negado(self):
        status, r = self._pede("POST", "/api/xm/{}/alerta".format(self.cid),
                               {"ligar": True, "segundos": self.alerta_s})
        if status == 200 and r.get("ok"):
            self.luz_ate = time.time() + self.alerta_s
            print("   ação: luz de alerta LIGADA por {:.0f} s".format(self.alerta_s))
        else:
            print("   ação: não acendeu a luz ({})".format(r.get("erro") or "HTTP {}".format(status)))
        if self.frase_negado:
            self._fala(self.frase_negado)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    leve = "--leve" in sys.argv[1:]
    if not args or not (args[0].lower().startswith("cam") and args[0][3:].isdigit()):
        print("Uso: python ferramentas\\rosto_reconhecer.py cam2 [--acao] [--leve]")
        return
    cid = args[0].lower()

    acoes = None
    if "--acao" in sys.argv[1:]:
        acoes = Acoes(cid)
        if not acoes.confere():
            return

    rostos = ia.Rostos()
    banco = ia.BancoRostos(rostos).carrega()
    if not banco.pessoas:
        print('Ninguém cadastrado. Rode antes: python ferramentas\\rosto_cadastro.py {} "Nome"'.format(cid))
        return
    print("Cadastro: " + ", ".join("{} ({} fotos, {})".format(
        n, len(p["fotos"]), "permitido" if p["permitido"] else "negado") for n, p in banco.pessoas.items()))
    print("Limites: aceito >= {:.2f} | desconhecido < {:.2f} | rosto mínimo {} px".format(
        ia.LIMIAR_ACEITO, ia.LIMIAR_DESCONHECIDO, TAMANHO_MIN_PX))

    print("Perguntando o endereço de vídeo de {} ...".format(cid))
    try:
        url = ia.url_da_camera(cid, leve)
    except Exception as erro:  # noqa: BLE001
        print("Não consegui o vídeo de {}: {}".format(cid, erro))
        return
    cap = ia.abre_captura(url)
    if not cap.isOpened():
        print("Não consegui abrir o vídeo de {}. A câmera está ligada? O IP mudou?".format(cid))
        return
    leitor = ia.Leitor(cap)
    if not leitor.espera_primeiro():
        print("A câmera abriu mas não mandou imagem.")
        leitor.para()
        return

    janela = "Reconhecimento - {}{}  (S foto, R recarrega, Q sai)".format(cid, " - ACOES LIGADAS" if acoes else "")
    cv2.namedWindow(janela, cv2.WINDOW_NORMAL)
    validador = ia.Validador()
    estat = Estatistica()
    faixa = None
    ultimo_numero = -1
    tela = None
    print("Rodando. Os eventos aparecem aqui embaixo.\n")

    try:
        while True:
            numero, quadro = leitor.pega()
            if quadro is not None and numero != ultimo_numero:
                ultimo_numero = numero
                limpo = quadro.copy()
                achados, ms_det, ms_cod = rostos.analisa(quadro)
                validos = [r for r in achados if r["caixa"][2] >= TAMANHO_MIN_PX and r["conf"] >= CONFIANCA_MIN]
                ignorados = [r for r in achados if not any(r is v for v in validos)]
                resultados = [ia.classifica(banco, r["codigo"]) for r in validos]
                estat.soma(resultados)

                evento = validador.atualiza(resultados)
                if evento:
                    hora = time.strftime("%H:%M:%S")
                    if evento["status"] == "permitido":
                        msg = "PERMITIDO: {} ({:.2f})".format(evento["nome"], evento["sim"])
                        faixa = (ia.texto_simples(msg), (0, 150, 0), time.time() + 3)
                    else:
                        quem = evento["nome"] if evento["nome"] else "desconhecido"
                        msg = "NEGADO: {} ({:.2f})".format(quem, evento["sim"])
                        faixa = (ia.texto_simples(msg), (0, 0, 200), time.time() + 3)
                    nome_arq = "{}_{}_{}.jpg".format(time.strftime("%Y%m%d_%H%M%S"), evento["status"],
                                                      ia.nome_seguro(evento["nome"] or "desconhecido"))
                    caminho = salva_jpg(PASTA_EVENTOS, nome_arq, limpo)
                    print("[{}] >>> {}   foto: {}".format(hora, msg, caminho))
                    if acoes:
                        acoes.evento(evento)

                cabecalho = "{}  det {:.0f} ms  cod {:.0f} ms  rostos {}".format(
                    "{}x{}".format(quadro.shape[1], quadro.shape[0]), ms_det, ms_cod, len(validos))
                tela = desenha(quadro, validos, resultados, ignorados, cabecalho, faixa)
                cv2.imshow(janela, tela)

                if time.time() - estat.inicio >= 5:
                    print("[{}] {}".format(time.strftime("%H:%M:%S"), estat.linha()))
                    estat.zera()

            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27):
                break
            if tecla in (ord("s"), ord("S")) and tela is not None:
                print("Foto salva: " + salva_jpg(PASTA_FOTOS, "reconhecer_{}.jpg".format(
                    time.strftime("%Y%m%d_%H%M%S")), tela))
            if tecla in (ord("r"), ord("R")):
                banco.carrega()
                print("Cadastro recarregado: {} pessoa(s).".format(len(banco.pessoas)))
            if cv2.getWindowProperty(janela, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        leitor.para()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
