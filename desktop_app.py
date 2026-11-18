import threading
import time
import urllib.error
import urllib.request

import uvicorn
import webview

from portaria_api.main import app

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
