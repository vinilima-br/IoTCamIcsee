# =============================================================
#  rosto_etapa1.py - Reconhecimento facial, ETAPA 1
#
#  Objetivo desta etapa: só MEDIR, sem cadastrar ninguém.
#   - baixa os 2 modelos (uma vez só) para modelos\
#       YuNet  -> acha os rostos na imagem
#       SFace  -> transforma o rosto num "código" de 128 números
#                 (é o que vamos comparar na etapa 3)
#   - abre a câmera e desenha os rostos encontrados
#   - mostra o TAMANHO de cada rosto em pixels (o que decide se a
#     câmera serve para reconhecer) e quanto tempo o PC leva
#
#  Não usa a porta 34567 (só vídeo via ONVIF/RTSP), então não tem
#  risco de bloqueio 205 e pode rodar com o servidor ligado.
#
#  Uso (dentro da pasta do projeto):
#    python ferramentas\rosto_etapa1.py cam2          (alta resolução)
#    python ferramentas\rosto_etapa1.py cam2 --leve   (stream leve)
#    python ferramentas\rosto_etapa1.py foto.jpg      (uma imagem)
#    python ferramentas\rosto_etapa1.py 0             (webcam do PC)
#
#  Na janela:  S = salva uma foto marcada   Q ou ESC = sair
# =============================================================

import os
import sys
import threading
import time
import urllib.request

# RTSP via TCP (igual ao servidor). Precisa vir ANTES do import cv2.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

import cv2  # noqa: E402

PASTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PASTA_BASE)

PASTA_MODELOS = os.path.join(PASTA_BASE, "modelos")
PASTA_SAIDA = os.path.join(PASTA_BASE, "rostos", "testes")

MODELOS = {
    "face_detection_yunet_2023mar.onnx": [
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ],
    "face_recognition_sface_2021dec.onnx": [
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ],
}
TAMANHO_MINIMO_MODELO = 100 * 1024   # arquivo menor que isso = download veio errado

LADO_DETECCAO = 960      # a detecção roda numa cópia reduzida (lado maior = 960 px)
ROSTO_BOM_PX = 80        # rosto com 80 px de largura ou mais: bom para reconhecer
ROSTO_MIN_PX = 50        # abaixo disso: pequeno demais
JANELA_MAX = (1280, 900) # tamanho máximo da janela na tela
TIMEOUT_MS = 10000


# -------------------------------------------------------------
#  Modelos
# -------------------------------------------------------------
def garante_modelos():
    os.makedirs(PASTA_MODELOS, exist_ok=True)
    caminhos = {}
    for nome, urls in MODELOS.items():
        destino = os.path.join(PASTA_MODELOS, nome)
        caminhos[nome] = destino
        if os.path.isfile(destino) and os.path.getsize(destino) >= TAMANHO_MINIMO_MODELO:
            continue
        baixou = False
        for url in urls:
            print("Baixando {} ...".format(nome))
            temp = destino + ".part"
            try:
                urllib.request.urlretrieve(url, temp)
                if os.path.getsize(temp) < TAMANHO_MINIMO_MODELO:
                    raise IOError("arquivo veio pequeno demais ({} bytes)".format(os.path.getsize(temp)))
                os.replace(temp, destino)
                print("   ok ({:.1f} MB)".format(os.path.getsize(destino) / 1e6))
                baixou = True
                break
            except Exception as erro:  # noqa: BLE001
                print("   falhou: {}".format(erro))
                if os.path.exists(temp):
                    os.remove(temp)
        if not baixou:
            print("\nNão consegui baixar {}.".format(nome))
            print("Baixe manualmente por este link e salve em {}:".format(PASTA_MODELOS))
            print("   " + urls[0])
            sys.exit(1)
    return (caminhos["face_detection_yunet_2023mar.onnx"],
            caminhos["face_recognition_sface_2021dec.onnx"])


def confere_opencv():
    partes = cv2.__version__.split(".")
    versao = (int(partes[0]), int(partes[1]))
    if versao < (4, 8) or not hasattr(cv2, "FaceDetectorYN") or not hasattr(cv2, "FaceRecognizerSF"):
        print("OpenCV {} é antigo demais para estes modelos (precisa 4.8 ou mais novo).".format(cv2.__version__))
        print("Atualize com:  pip install -U opencv-python")
        sys.exit(1)


# -------------------------------------------------------------
#  Rostos
# -------------------------------------------------------------
class Rostos:
    def __init__(self, modelo_det, modelo_rec):
        self.det = cv2.FaceDetectorYN.create(modelo_det, "", (320, 320), 0.8, 0.3, 5000)
        self.rec = cv2.FaceRecognizerSF.create(modelo_rec, "")
        self.tamanho_atual = None

    def analisa(self, frame):
        """
        Acha os rostos e calcula o 'código' de cada um.
        Retorna (lista_de_rostos, ms_deteccao, ms_codigo).
        Cada rosto: {"caixa": (x, y, w, h) na imagem original, "conf", "codigo"}
        """
        altura, largura = frame.shape[:2]
        escala = min(1.0, LADO_DETECCAO / max(altura, largura))
        if escala < 1.0:
            pequeno = cv2.resize(frame, (int(largura * escala), int(altura * escala)),
                                 interpolation=cv2.INTER_AREA)
        else:
            pequeno = frame
        a, l = pequeno.shape[:2]
        if self.tamanho_atual != (l, a):
            self.det.setInputSize((l, a))
            self.tamanho_atual = (l, a)

        t0 = time.perf_counter()
        _, achados = self.det.detect(pequeno)
        ms_det = (time.perf_counter() - t0) * 1000

        rostos = []
        ms_cod = 0.0
        if achados is None:
            return rostos, ms_det, ms_cod

        for linha in achados:
            # volta caixa + 5 pontos (olhos, nariz, boca) para a resolução original
            original = linha.copy()
            original[:14] = linha[:14] / escala
            t1 = time.perf_counter()
            recorte = self.rec.alignCrop(frame, original)      # rosto alinhado 112x112
            codigo = self.rec.feature(recorte).flatten().copy()
            ms_cod += (time.perf_counter() - t1) * 1000
            x, y, w, h = [int(v) for v in original[:4]]
            rostos.append({"caixa": (x, y, w, h), "conf": float(linha[14]), "codigo": codigo})
        return rostos, ms_det, ms_cod


def desenha(frame, rostos, info):
    altura, largura = frame.shape[:2]
    esp = max(2, largura // 500)
    fonte = max(0.6, largura / 1600)
    for r in rostos:
        x, y, w, h = r["caixa"]
        if w >= ROSTO_BOM_PX:
            cor, rotulo = (0, 200, 0), "bom"
        elif w >= ROSTO_MIN_PX:
            cor, rotulo = (0, 200, 255), "regular"
        else:
            cor, rotulo = (0, 0, 255), "pequeno"
        cv2.rectangle(frame, (x, y), (x + w, y + h), cor, esp)
        texto = "{} px ({}) {:.0f}%".format(w, rotulo, r["conf"] * 100)
        cv2.putText(frame, texto, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                    fonte, cor, max(1, esp - 1), cv2.LINE_AA)
    cv2.rectangle(frame, (0, 0), (largura, int(40 * fonte) + 10), (0, 0, 0), -1)
    cv2.putText(frame, info, (10, int(30 * fonte) + 2), cv2.FONT_HERSHEY_SIMPLEX,
                fonte, (255, 255, 255), max(1, esp - 1), cv2.LINE_AA)
    return frame


def cabe_na_tela(frame):
    altura, largura = frame.shape[:2]
    escala = min(1.0, JANELA_MAX[0] / largura, JANELA_MAX[1] / altura)
    if escala < 1.0:
        return cv2.resize(frame, (int(largura * escala), int(altura * escala)), interpolation=cv2.INTER_AREA)
    return frame


def salva(frame):
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    caminho = os.path.join(PASTA_SAIDA, "teste_{}_{:03d}.jpg".format(
        time.strftime("%Y%m%d_%H%M%S"), int(time.time() * 1000) % 1000))
    cv2.imwrite(caminho, frame)
    print("Foto salva: {}".format(caminho))


# -------------------------------------------------------------
#  Fonte de vídeo
# -------------------------------------------------------------
def url_da_camera(cid, leve):
    import config
    stream = 1 if leve else 0
    if cid == "cam1":
        return "rtsp://{ip}:{porta}/user={u}_password={s}_channel=1_stream={st}.sdp".format(
            ip=config.CAM_IP, porta=config.CAM_PORTA, u=config.CAM_USUARIO, s=config.CAM_SENHA, st=stream)

    import onvif_rtsp
    n = cid[3:]
    ip = getattr(config, "CAM{}_IP".format(n), None)
    if not ip:
        print("{} não existe no config.py".format(cid))
        sys.exit(1)
    usuario = getattr(config, "CAM{}_USUARIO".format(n), None) or getattr(config, "CAM2_USUARIO", "admin")
    senha = getattr(config, "CAM{}_SENHA".format(n), "") or getattr(config, "CAM2_SENHA", "")
    porta = getattr(config, "CAM{}_PORTA_ONVIF".format(n), 0) or None
    print("Perguntando o endereço de vídeo ao ONVIF de {} ({}) ...".format(cid, ip))
    urls = onvif_rtsp.descobre_urls(ip, usuario, senha, porta_onvif=porta)
    return urls[min(stream, len(urls) - 1)]


def abre_captura(fonte):
    if isinstance(fonte, int):
        return cv2.VideoCapture(fonte)
    try:
        return cv2.VideoCapture(fonte, cv2.CAP_FFMPEG,
                                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, TIMEOUT_MS,
                                 cv2.CAP_PROP_READ_TIMEOUT_MSEC, TIMEOUT_MS])
    except (TypeError, AttributeError, cv2.error):
        return cv2.VideoCapture(fonte, cv2.CAP_FFMPEG)


class Leitor:
    """Lê a câmera numa thread e guarda só o quadro mais novo (sem atraso acumulado)."""

    def __init__(self, cap):
        self.cap = cap
        self.quadro = None
        self.numero = 0
        self.rodando = True
        self.trava = threading.Lock()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while self.rodando:
            try:
                ok, quadro = self.cap.read()
            except cv2.error:
                ok, quadro = False, None
            if not self.rodando:
                break
            if not ok:
                time.sleep(0.05)
                continue
            with self.trava:
                self.quadro = quadro
                self.numero += 1

    def pega(self):
        with self.trava:
            return self.numero, (None if self.quadro is None else self.quadro.copy())

    def para(self):
        self.rodando = False
        self.thread.join(timeout=TIMEOUT_MS / 1000 + 2)
        if not self.thread.is_alive():
            self.cap.release()


# -------------------------------------------------------------
#  Modos
# -------------------------------------------------------------
def roda_imagem(rostos, caminho):
    imagem = cv2.imread(caminho)
    if imagem is None:
        print("Não consegui abrir a imagem: {}".format(caminho))
        sys.exit(1)
    rostos.analisa(imagem)                      # aquecimento
    achados, ms_det, ms_cod = rostos.analisa(imagem)
    altura, largura = imagem.shape[:2]
    print("Imagem {}x{}: {} rosto(s)  detecção {:.0f} ms  código {:.0f} ms".format(
        largura, altura, len(achados), ms_det, ms_cod))
    for i, r in enumerate(achados, 1):
        print("  rosto {}: {} px de largura, confiança {:.0f}%".format(i, r["caixa"][2], r["conf"] * 100))
    if len(achados) >= 2:
        s = rostos.rec.match(achados[0]["codigo"].reshape(1, -1), achados[1]["codigo"].reshape(1, -1),
                             cv2.FaceRecognizerSF_FR_COSINE)
        print("  semelhança rosto 1 x rosto 2: {:.2f}  (mesma pessoa costuma dar acima de 0.36)".format(s))
    saida = os.path.splitext(caminho)[0] + "_rostos.jpg"
    cv2.imwrite(saida, desenha(imagem, achados, "{} rosto(s)".format(len(achados))))
    print("Imagem marcada salva em: {}".format(saida))


def roda_video(rostos, fonte, nome):
    print("Abrindo o vídeo ...")
    cap = abre_captura(fonte)
    if not cap.isOpened():
        print("Não consegui abrir o vídeo de {}. A câmera está ligada? O IP mudou?".format(nome))
        sys.exit(1)
    leitor = Leitor(cap)

    inicio = time.time()
    while leitor.pega()[1] is None:
        if time.time() - inicio > TIMEOUT_MS / 1000:
            print("A câmera abriu mas não mandou imagem em {} s.".format(TIMEOUT_MS // 1000))
            leitor.para()
            sys.exit(1)
        time.sleep(0.05)

    janela = "Etapa 1 - rostos - {}  (S salva, Q sai)".format(nome)
    cv2.namedWindow(janela, cv2.WINDOW_NORMAL)
    ultimo_numero = -1
    analises = 0
    conta_fps = 0
    t_janela = time.time()
    soma_det = soma_cod = 0.0
    maior_rosto = 0
    fps = 0.0
    ultimo_rel = time.time()
    tela = None

    try:
        while True:
            numero, quadro = leitor.pega()
            if quadro is not None and numero != ultimo_numero:
                ultimo_numero = numero
                achados, ms_det, ms_cod = rostos.analisa(quadro)
                analises += 1
                conta_fps += 1
                soma_det += ms_det
                soma_cod += ms_cod
                for r in achados:
                    maior_rosto = max(maior_rosto, r["caixa"][2])
                agora = time.time()
                if agora - t_janela >= 1.0:
                    fps = conta_fps / (agora - t_janela)
                    t_janela, conta_fps = agora, 0
                altura, largura = quadro.shape[:2]
                info = "{}x{}  {:.1f} analises/s  deteccao {:.0f} ms  codigo {:.0f} ms  rostos: {}".format(
                    largura, altura, fps, ms_det, ms_cod, len(achados))
                tela = desenha(quadro, achados, info)
                cv2.imshow(janela, cabe_na_tela(tela))
                if agora - ultimo_rel >= 5.0 and analises:
                    print("[{}] {}x{} | {:.1f} análises/s | detecção média {:.0f} ms | "
                          "código média {:.0f} ms | maior rosto nos últimos 5 s: {} px".format(
                              time.strftime("%H:%M:%S"), largura, altura, fps,
                              soma_det / analises, soma_cod / analises, maior_rosto))
                    ultimo_rel = agora
                    analises = 0
                    soma_det = soma_cod = 0.0
                    maior_rosto = 0
            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27):
                break
            if tecla in (ord("s"), ord("S")) and tela is not None:
                salva(tela)
            if cv2.getWindowProperty(janela, cv2.WND_PROP_VISIBLE) < 1:
                break
    except KeyboardInterrupt:
        pass
    finally:
        leitor.para()
        cv2.destroyAllWindows()


def main():
    if len(sys.argv) < 2:
        print("Uso: python ferramentas\\rosto_etapa1.py cam2 [--leve]  |  foto.jpg  |  0")
        sys.exit(1)

    confere_opencv()
    modelo_det, modelo_rec = garante_modelos()
    rostos = Rostos(modelo_det, modelo_rec)
    print("OpenCV {} | {} threads de CPU".format(cv2.__version__, cv2.getNumThreads()))

    alvo = sys.argv[1]
    leve = "--leve" in sys.argv[2:]

    if alvo.lower().startswith("cam") and alvo[3:].isdigit():
        url = url_da_camera(alvo.lower(), leve)
        roda_video(rostos, url, "{} ({})".format(alvo, "leve" if leve else "alta"))
    elif alvo.isdigit():
        roda_video(rostos, int(alvo), "webcam {}".format(alvo))
    elif alvo.lower().startswith("rtsp://"):
        roda_video(rostos, alvo, "rtsp")
    elif os.path.isfile(alvo):
        roda_imagem(rostos, alvo)
    else:
        print("Não entendi '{}'. Use cam1, cam2, cam3, um número de webcam, rtsp://... ou uma imagem.".format(alvo))
        sys.exit(1)


if __name__ == "__main__":
    main()
