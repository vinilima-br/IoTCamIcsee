import threading
import time
import urllib.error
import urllib.request

import sys
from pathlib import Path

# Roda como "python gestao\desktop_app.py": a raiz do projeto precisa estar no caminho.
RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import uvicorn  # noqa: E402
import webview  # noqa: E402

from gestao.api.main import app  # noqa: E402

HOST = "127.0.0.1"
PORT = 8000
URL = "http://{}:{}/".format(HOST, PORT)

def main():
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True, name="portaria-api")
    server_thread.start()

    deadline = time.monotonic() + 40
    while time.monotonic() < deadline and server_thread.is_alive():
        try:
            with urllib.request.urlopen(URL + "api/health", timeout=1):
                break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    else:
        server.should_exit = True
        server_thread.join(timeout=5)
        raise RuntimeError("A API local não iniciou dentro de 40 segundos.")

    try:
        webview.create_window(
            "Portaria | Controle de acesso",
            URL,
            width=1440,
            height=920,
            min_size=(1024, 700),
            resizable=True,
            background_color="#101821",
        )
        webview.start(debug=False)
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)

if __name__ == "__main__":
    main()
