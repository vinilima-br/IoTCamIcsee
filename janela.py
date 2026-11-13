# -*- coding: utf-8 -*-
"""
Central de Câmeras em JANELA PRÓPRIA (cara de programa instalado).

  python janela.py        (ou dois cliques em PAINEL.bat)

- Sobe o servidor (o mesmo do servidor.py) e abre o painel numa janela
  sem barra de navegador, com nome e ícone da Central.
- Se o servidor JÁ estiver rodando (INICIAR.bat aberto), só abre a janela
  e não sobe outro (evita sessão dupla nas câmeras).
- Fechar a janela = desligar o servidor (com logout limpo nas câmeras),
  igual ao Ctrl+C. Se o servidor já estava rodando antes, ele continua.
- O celular continua abrindo http://IP-DO-MINI-PC:5050 normalmente.
- Sem pywebview (ou sem o WebView2 no Windows), abre o Edge em modo
  aplicativo (--app), que também fica sem barra de navegador.

Instalar a janela:  pip install pywebview
"""
import atexit
import os
import socket
import subprocess
import sys
import threading
import time

PASTA = os.path.dirname(os.path.abspath(__file__))
os.chdir(PASTA)
sys.path.insert(0, PASTA)

TITULO = "Central de Câmeras"
ICONE = os.path.join(PASTA, "icone.ico")
DADOS_JANELA = os.path.join(PASTA, "janela_dados")   # guarda o que a página lembra (câmeras escondidas, colunas...)

try:
    import config
    PORTA = getattr(config, "WEB_PORTA", 5050)
except Exception:
    PORTA = 5050
URL = "http://127.0.0.1:{}/".format(PORTA)
REINICIAR = threading.Event()      # o servidor pediu reinício (câmera nova) ou atualização
_SERVIDOR = None                   # módulo servidor (quando esta janela subiu o servidor)
CODIGO_REINICIO = 3                # o PAINEL.bat abre de novo quando sai com este código


def servidor_no_ar():
    try:
        with socket.create_connection(("127.0.0.1", PORTA), timeout=0.5):
            return True
    except OSError:
        return False


def espera_servidor(segundos=40):
    fim = time.time() + segundos
    while time.time() < fim:
        if servidor_no_ar():
            return True
        time.sleep(0.3)
    return False


def nome_na_barra_de_tarefas():
    """Faz o Windows mostrar o ícone da Central na barra de tarefas (e não o do Python)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("vinilima.CentralDeCameras")
        except Exception:
            pass


def abre_janela_pywebview():
    """Devolve True se a janela abriu (e já foi fechada); False se não deu para usar o pywebview."""
    try:
        import webview
    except ImportError:
        print(" [janela] pywebview não instalado. Rode:  pip install pywebview")
        return False

    if sys.platform == "win32":
        try:
            import webview.platforms.winforms as wf
            if getattr(wf, "renderer", "") != "edgechromium":
                print(" [janela] WebView2 (Edge) não encontrado no Windows; a janela antiga não serve pro painel.")
                return False
        except Exception as erro:
            print(" [janela] não consegui carregar a parte Windows do pywebview: {!r}".format(erro))
            return False

    try:
        webview.settings["ALLOW_DOWNLOADS"] = True     # botões "baixar" / "salvar" das gravações
    except Exception:
        pass

    os.makedirs(DADOS_JANELA, exist_ok=True)
    webview.create_window(
        TITULO, URL,
        width=1400, height=900, min_size=(900, 600),
        maximized=True,
        background_color="#0e1115",     # mesmo fundo do painel: não pisca branco ao abrir
        text_select=True,
        zoomable=True,                  # Ctrl + roda do mouse
    )
    try:
        webview.start(
            icon=ICONE if os.path.isfile(ICONE) else None,
            private_mode=False,          # senão a página esquece câmeras escondidas, colunas, aba...
            storage_path=DADOS_JANELA,
            gui="edgechromium" if sys.platform == "win32" else None,
        )
    except Exception as erro:
        print(" [janela] o pywebview falhou ao abrir: {!r}".format(erro))
        return False
    return True


def caminho_edge():
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            p = os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")
            if os.path.isfile(p):
                return p
    return None


def abre_edge_modo_app():
    """Plano B: Edge sem barra de endereço. Devolve True se conseguiu abrir."""
    edge = caminho_edge()
    if not edge:
        print(" [janela] Edge não encontrado. Abra no navegador: {}".format(URL))
        return False
    subprocess.Popen([edge, "--app=" + URL,
                      "--user-data-dir=" + os.path.join(DADOS_JANELA, "edge")])
    print(" [janela] Aberto no Edge em modo aplicativo.")
    return True


def desligar_e_sair(codigo=0):
    if codigo == CODIGO_REINICIO:
        print("\n Reiniciando a Central (câmeras mudaram)...")
    elif REINICIAR.is_set():
        print("\n Fechando para atualizar (abre de novo sozinha)...")
    else:
        print("\n Janela fechada: desligando o servidor (logout nas câmeras)...")
    try:
        atexit._run_exitfuncs()        # encerrar_xm / encerrar_gravadores do servidor.py
    finally:
        os._exit(codigo)               # não deixa nenhuma thread segurar o processo aberto


def _codigo_saida():
    """3 = o PAINEL.bat sobe de novo; 0 = atualização (o ajudante abre de novo depois)."""
    return getattr(_SERVIDOR, "CODIGO_SAIDA", CODIGO_REINICIO)


def _ao_reiniciar():
    """Chamado pelo servidor (thread dele) quando precisa subir de novo."""
    REINICIAR.set()
    try:
        import webview
        for w in list(webview.windows):
            w.destroy()                # webview.start() volta e o main() sai com o código 3
    except Exception:
        pass


def main():
    nome_na_barra_de_tarefas()

    ja_rodava = servidor_no_ar()
    if ja_rodava:
        print(" Servidor já está rodando (porta {}). Só vou abrir a janela.".format(PORTA))
    else:
        import servidor
        global _SERVIDOR
        _SERVIDOR = servidor
        servidor.AO_REINICIAR = _ao_reiniciar
        servidor.preparar_servidor()                       # thread principal (signal)
        threading.Thread(target=servidor.rodar_web, daemon=True, name="web").start()
        if not espera_servidor():
            print(" [X] O servidor não respondeu na porta {}. Veja as mensagens acima.".format(PORTA))
            input(" Enter para fechar...")
            desligar_e_sair()

    if abre_janela_pywebview():
        if ja_rodava:
            return                     # o servidor é do INICIAR.bat: deixa ele lá
        desligar_e_sair(_codigo_saida() if REINICIAR.is_set() else 0)

    # Plano B
    abre_edge_modo_app()
    if ja_rodava:
        return
    print(" Servidor rodando. Para desligar: Ctrl+C nesta janela.")
    try:
        while not REINICIAR.is_set():
            time.sleep(1)
        desligar_e_sair(_codigo_saida())
    except (KeyboardInterrupt, SystemExit):
        desligar_e_sair()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:          # Ctrl+C no terminal com a janela aberta
        desligar_e_sair()
